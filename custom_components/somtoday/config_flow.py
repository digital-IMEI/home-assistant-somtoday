"""Config flow for Somtoday."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.calendar.const import CalendarEntityFeature
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

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

    async def async_step_reauth(self, entry_data):
        """Renew credentials in place, retaining calendar ownership and options."""
        self._client = SomtodayClient(async_get_clientsession(self.hass))
        self._organization = entry_data[CONF_ORGANIZATION]
        self._provider = entry_data.get(CONF_PROVIDER)
        return await self._start_authorization()

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
                    if self.context.get("source") == "reauth":
                        entry = self._get_reauth_entry()
                        if entry.unique_id != unique_id:
                            errors["base"] = "wrong_account"
                            return self.async_show_form(
                                step_id="authorize",
                                description_placeholders={"authorize_url": self._authorize_url},
                                data_schema=vol.Schema({vol.Required("callback_url"): str}),
                                errors=errors,
                            )
                        return self.async_update_reload_and_abort(
                            entry, data_updates={CONF_TOKEN: token}
                        )
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

    def _students(self) -> dict[str, str]:
        """Return the currently available children."""
        from .export import item_id

        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]
        return {
            item_id(student): str(
                student.get("roepnaam")
                or student.get("achternaam")
                or item_id(student)
            )
            for student in coordinator.data.get("students", [])
            if item_id(student)
        }

    def _old_options(self) -> dict[str, Any]:
        """Combine account defaults with this child's saved route."""
        return {
            **self.config_entry.options,
            **self.config_entry.options.get("exports", {}).get(self.student, {}),
        }

    def _calendar_choices(self) -> dict[str, str]:
        """Return calendars that support both creation and deletion."""
        choices = {}
        required = (
            CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
        )
        for state in self.hass.states.async_all("calendar"):
            if getattr(state, "state", None) in ("unavailable", "unknown"):
                continue
            supported = state.attributes.get("supported_features", 0)
            if isinstance(supported, int) and (supported & required) == required:
                choices[state.entity_id] = state.name
        return choices

    def _save_options(self, route: dict[str, Any]):
        """Save this child's route without changing routes for other children."""
        options = dict(self.config_entry.options)
        routes = dict(options.get("exports", {}))
        routes[self.student] = route
        options.update(self._pending_settings)
        options["exports"] = routes
        return self.async_create_entry(title="", data=options)

    async def async_step_init(self, user_input=None):
        students = self._students()
        if user_input is not None:
            student = user_input.get("student_id")
            if student not in students:
                return self.async_show_form(
                    step_id="init",
                    data_schema=vol.Schema(
                        {vol.Required("student_id"): vol.In(students)}
                    ),
                    errors={"base": "invalid_student"},
                )
            self.student = student
            return await self.async_step_settings()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required("student_id"): vol.In(students)}
            ),
        )

    async def async_step_settings(self, user_input=None):
        students = self._students()
        old = self._old_options()
        schema = vol.Schema(
            {
                vol.Required(
                    "enable_day", default=bool(old.get("day_calendar"))
                ): bool,
                vol.Required(
                    "enable_lessons", default=bool(old.get("lesson_calendar"))
                ): bool,
                vol.Required("preview", default=old.get("preview", True)): bool,
                vol.Required(
                    "days_ahead", default=old.get("days_ahead", 14)
                ): NumberSelector(NumberSelectorConfig(min=1, max=30, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    "scan_interval", default=old.get("scan_interval", 15)
                ): NumberSelector(NumberSelectorConfig(min=5, max=120, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        if user_input is not None:
            if self.student not in students:
                return self.async_show_form(
                    step_id="settings",
                    data_schema=schema,
                    errors={"base": "invalid_student"},
                    description_placeholders={"student": self.student},
                )
            self._enable_day = user_input["enable_day"]
            self._enable_lessons = user_input["enable_lessons"]
            self._pending_settings = {
                key: user_input[key]
                for key in ("preview", "days_ahead", "scan_interval")
            }
            for key in ("days_ahead", "scan_interval"):
                self._pending_settings[key] = int(self._pending_settings[key])
            if self._enable_day or self._enable_lessons:
                return await self.async_step_destinations()
            return self._save_options(
                {
                    "day_calendar": "",
                    "lesson_calendar": "",
                    "day_title": old.get("day_title", "School · {student}"),
                    "lesson_prefix": old.get("lesson_prefix", "{student} · "),
                }
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=schema,
            description_placeholders={
                "student": students.get(self.student, self.student)
            },
        )

    async def async_step_destinations(self, user_input=None):
        """Choose a destination for each enabled export."""
        students = self._students()
        choices = self._calendar_choices()
        old = self._old_options()
        errors = {}
        enabled_fields = []
        if self._enable_day:
            enabled_fields.append("day_calendar")
        if self._enable_lessons:
            enabled_fields.append("lesson_calendar")

        if user_input is not None:
            if self.student not in students:
                errors["base"] = "invalid_student"
            elif any(user_input.get(field) not in choices for field in enabled_fields):
                errors["base"] = "invalid_calendar"
            else:
                return self._save_options(
                    {
                        "day_calendar": user_input.get("day_calendar", ""),
                        "lesson_calendar": user_input.get("lesson_calendar", ""),
                        "day_title": user_input.get(
                            "day_title", old.get("day_title", "School · {student}")
                        ),
                        "lesson_prefix": user_input.get(
                            "lesson_prefix", old.get("lesson_prefix", "{student} · ")
                        ),
                    }
                )

        schema = {}
        if self._enable_day:
            day_default = old.get("day_calendar")
            day_key = vol.Required("day_calendar")
            if day_default in choices:
                day_key = vol.Required("day_calendar", default=day_default)
            schema[day_key] = vol.In(choices)
            schema[
                vol.Required(
                    "day_title", default=old.get("day_title", "School · {student}")
                )
            ] = vol.All(str, vol.Length(min=1, max=100))
        if self._enable_lessons:
            lesson_default = old.get("lesson_calendar")
            lesson_key = vol.Required("lesson_calendar")
            if lesson_default in choices:
                lesson_key = vol.Required("lesson_calendar", default=lesson_default)
            schema[lesson_key] = vol.In(choices)
            schema[
                vol.Optional(
                    "lesson_prefix",
                    default=old.get("lesson_prefix", "{student} · "),
                )
            ] = str
        if not choices:
            errors["base"] = "no_writable_calendars"
        return self.async_show_form(
            step_id="destinations",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "student": students.get(self.student, self.student),
                "student_placeholder": "{student}",
            },
        )
