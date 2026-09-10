"""Config flow for Somtoday."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SomtodayOptionsFlow()

    def __init__(self) -> None:
        self._client: SomtodayClient | None = None
        self._organizations: list[dict[str, Any]] = []
        self._organization: dict[str, Any] | None = None
        self._providers: list[dict[str, Any]] = []
        self._provider: dict[str, Any] | None = None
        self._verifier = ""
        self._state = ""
        self._authorize_url = ""

    async def async_step_user(self, user_input=None):
        """Show all available Somtoday organizations in a dropdown."""
        errors: dict[str, str] = {}
        if self._client is None:
            self._client = SomtodayClient(async_get_clientsession(self.hass))

        if not self._organizations:
            try:
                organizations = await self._client.organizations()
            except SomtodayApiError:
                errors["base"] = "cannot_connect"
            else:
                self._organizations = sorted(
                    organizations,
                    key=lambda item: (
                        str(item.get("naam", "")).casefold(),
                        str(item.get("plaats", "")).casefold(),
                    ),
                )

        if user_input is not None and self._organizations:
            selected_uuid = user_input[CONF_ORGANIZATION]
            selected = next(
                (
                    item
                    for item in self._organizations
                    if item.get("uuid") == selected_uuid
                ),
                None,
            )
            if selected is None:
                errors["base"] = "organization_not_found"
            else:
                return await self._select_organization(selected)

        choices = {
            str(item["uuid"]): self._organization_label(item)
            for item in self._organizations
            if item.get("uuid")
        }
        schema = (
            vol.Schema({vol.Required(CONF_ORGANIZATION): vol.In(choices)})
            if choices
            else vol.Schema({})
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def _organization_label(organization: dict[str, Any]) -> str:
        """Build a readable organization label."""
        name = str(organization.get("naam", "Onbekende school"))
        place = str(organization.get("plaats", "")).strip()
        return f"{name} — {place}" if place and place.casefold() != name.casefold() else name

    async def _select_organization(self, organization: dict[str, Any]):
        self._organization = organization
        self._providers = organization.get("oidcurls") or []
        self._provider = self._providers[0] if self._providers else None
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
            self._organization["uuid"], challenge, self._state
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
                    student_ids = sorted(
                        str((item.get("links") or [{}])[0].get("id", ""))
                        for item in students
                        if (item.get("links") or [{}])[0].get("id")
                    )
                    unique_id = f"{self._organization['uuid']}:{','.join(student_ids)}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    student_names = ", ".join(
                        str(item.get("roepnaam") or item.get("achternaam") or "Leerling")
                        for item in students
                    )
                    title = student_names or str(
                        self._organization.get("naam", "Somtoday")
                    )
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


class SomtodayOptionsFlow(config_entries.OptionsFlow):
    """Configure independent school-day and lesson calendar exports."""

    async def async_step_init(self, user_input=None):
        from .export import item_id

        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]
        students = {item_id(s): str(s.get("roepnaam") or item_id(s))
                    for s in coordinator.data.get("students", []) if item_id(s)}
        if user_input is not None:
            self.student = user_input["student_id"]
            return await self.async_step_settings()
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required("student_id"): vol.In(students),
        }))

    async def async_step_settings(self, user_input=None):
        from .export import item_id
        from .sync import target_entity

        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]
        students = {item_id(s): str(s.get("roepnaam") or s.get("achternaam") or item_id(s))
                    for s in coordinator.data.get("students", [])}
        students.pop("", None)
        choices = {"": "Disabled"}
        registry = er.async_get(self.hass)
        for state in self.hass.states.async_all("calendar"):
            registered = registry.async_get(state.entity_id)
            if registered and registered.platform == DOMAIN:
                continue
            try:
                target_entity(self.hass, state.entity_id)
            except ValueError:
                continue
            choices[state.entity_id] = state.name
        errors = {}
        if user_input is not None:
            if any(user_input.get(k) not in choices for k in ("day_calendar", "lesson_calendar")):
                errors["base"] = "invalid_calendar"
            elif self.student not in students:
                errors["base"] = "invalid_student"
            else:
                options = dict(self.config_entry.options)
                routes = dict(options.get("exports", {}))
                routes[self.student] = {k: user_input[k] for k in (
                    "day_calendar", "lesson_calendar", "day_title", "lesson_prefix"
                )}
                options.update({k: user_input[k] for k in ("preview", "days_ahead", "scan_interval")})
                options["exports"] = routes
                return self.async_create_entry(title="", data=options)
        old = {**self.config_entry.options, **self.config_entry.options.get("exports", {}).get(self.student, {})}
        schema = {
            vol.Required("day_calendar", default=old.get("day_calendar", "")): vol.In(choices),
            vol.Required("lesson_calendar", default=old.get("lesson_calendar", "")): vol.In(choices),
            vol.Required("preview", default=old.get("preview", True)): bool,
            vol.Required("days_ahead", default=old.get("days_ahead", 14)): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Required("scan_interval", default=old.get("scan_interval", 15)): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
            vol.Required("day_title", default=old.get("day_title", "School · {student}")): vol.All(str, vol.Length(min=1, max=100)),
            vol.Optional("lesson_prefix", default=old.get("lesson_prefix", "{student} · ")): str,
        }
        return self.async_show_form(step_id="settings", data_schema=vol.Schema(schema), errors=errors,
                                    description_placeholders={"student": students.get(self.student, self.student)})
