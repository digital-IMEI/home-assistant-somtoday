"""Config flow for Somtoday."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    SomtodayApiError,
    SomtodayAuthenticationError,
    SomtodayClient,
    build_authorize_url,
    generate_pkce,
)
from .const import CONF_ORGANIZATION, CONF_PROVIDER, CONF_TOKEN, DOMAIN


class SomtodayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Somtoday config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: SomtodayClient | None = None
        self._organization: dict[str, Any] | None = None
        self._providers: list[dict[str, Any]] = []
        self._provider: dict[str, Any] | None = None
        self._verifier = ""
        self._state = ""
        self._authorize_url = ""

    async def async_step_user(self, user_input=None):
        """Find the requested school organization."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._client = SomtodayClient(async_get_clientsession(self.hass))
            try:
                organizations = await self._client.organizations()
            except SomtodayApiError:
                errors["base"] = "cannot_connect"
            else:
                query = user_input[CONF_ORGANIZATION].strip().casefold()
                matches = [
                    item
                    for item in organizations
                    if query in str(item.get("naam", "")).casefold()
                    or query in str(item.get("plaats", "")).casefold()
                ]
                if len(matches) == 1:
                    return await self._select_organization(matches[0])
                if not matches:
                    errors["base"] = "organization_not_found"
                else:
                    self._providers = matches
                    return await self.async_step_organization()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ORGANIZATION, default="Sophianum"): str}
            ),
            errors=errors,
        )

    async def async_step_organization(self, user_input=None):
        """Disambiguate matching organizations."""
        choices = {
            item["uuid"]: f"{item.get('naam')} ({item.get('plaats', '')})"
            for item in self._providers
        }
        if user_input is not None:
            selected = next(
                item for item in self._providers if item["uuid"] == user_input["uuid"]
            )
            return await self._select_organization(selected)
        return self.async_show_form(
            step_id="organization",
            data_schema=vol.Schema({vol.Required("uuid"): vol.In(choices)}),
        )

    async def _select_organization(self, organization: dict[str, Any]):
        self._organization = organization
        self._providers = organization.get("oidcurls") or []
        if not self._providers:
            return self.async_abort(reason="sso_not_available")
        if len(self._providers) > 1:
            return await self.async_step_provider()
        self._provider = self._providers[0]
        return await self._start_authorization()

    async def async_step_provider(self, user_input=None):
        """Select an SSO provider when a school advertises more than one."""
        choices = {
            str(index): provider.get("omschrijving", provider.get("url", str(index)))
            for index, provider in enumerate(self._providers)
        }
        if user_input is not None:
            self._provider = self._providers[int(user_input[CONF_PROVIDER])]
            return await self._start_authorization()
        return self.async_show_form(
            step_id="provider",
            data_schema=vol.Schema({vol.Required(CONF_PROVIDER): vol.In(choices)}),
        )

    async def _start_authorization(self):
        self._verifier, challenge = generate_pkce()
        self._state = secrets.token_urlsafe(16)
        self._authorize_url = build_authorize_url(
            self._organization["uuid"], self._provider["url"], challenge, self._state
        )
        return await self.async_step_authorize()

    async def async_step_authorize(self, user_input=None):
        """Accept the callback URI after interactive SSO login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            parsed = urlparse(user_input["callback_url"].strip())
            query = parse_qs(parsed.query)
            code = query.get("code", [None])[0]
            state = query.get("state", [None])[0]
            if not code or state != self._state:
                errors["base"] = "invalid_callback"
            else:
                try:
                    token = await self._client.exchange_code(code, self._verifier)
                    students = await self._client.students()
                except SomtodayAuthenticationError:
                    errors["base"] = "invalid_auth"
                except SomtodayApiError:
                    errors["base"] = "cannot_connect"
                else:
                    unique_id = str(self._organization["uuid"])
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    student_names = ", ".join(
                        str(item.get("roepnaam") or item.get("achternaam") or "Leerling")
                        for item in students
                    )
                    title = student_names or str(self._organization.get("naam", "Somtoday"))
                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_ORGANIZATION: self._organization,
                            CONF_PROVIDER: self._provider,
                            CONF_TOKEN: token,
                        },
                    )

        return self.async_show_form(
            step_id="authorize",
            description_placeholders={"authorize_url": self._authorize_url},
            data_schema=vol.Schema({vol.Required("callback_url"): str}),
            errors=errors,
        )
