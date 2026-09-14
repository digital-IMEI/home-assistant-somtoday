"""Config flow for Somtoday."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.calendar.const import CalendarEntityFeature
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .api import (
    SomtodayApiError,
    SomtodayAuthenticationError,
    SomtodayClient,
    build_authorize_url,
    generate_pkce,
)
from .const import (
    CONF_ORGANIZATION,
    CONF_PROVIDER,
    CONF_TOKEN,
    DOMAIN,
    HOLIDAY_MODE_DAILY,
    HOLIDAY_MODE_FULL_WEEKS,
    HOLIDAY_MODE_SCHOOL_DAYS,
)

HOLIDAY_MODE_CHOICES = {
    HOLIDAY_MODE_SCHOOL_DAYS: "One event · Somtoday dates",
    HOLIDAY_MODE_FULL_WEEKS: "One event · include surrounding weekends",
    HOLIDAY_MODE_DAILY: "One all-day event per Somtoday date",
}


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
        options.pop("preview", None)
        routes = dict(options.get("exports", {}))
        route["automatic_day_title"] = self._automatic_day_title
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
                vol.Required(
                    "enable_holidays", default=bool(old.get("holiday_calendar"))
                ): bool,
                vol.Required(
                    "enable_assessments",
                    default=bool(old.get("assessment_calendar")),
                ): bool,
                vol.Required(
                    "days_ahead", default=old.get("days_ahead", 14)
                ): NumberSelector(NumberSelectorConfig(min=1, max=60, step=1, mode=NumberSelectorMode.BOX)),
                vol.Required(
                    "scan_interval", default=old.get("scan_interval", 15)
                ): NumberSelector(NumberSelectorConfig(min=5, max=120, step=1, mode=NumberSelectorMode.BOX)),
            }
        )
        groups = {
            "exports": ("enable_day", "enable_lessons", "enable_holidays", "enable_assessments"),
            "synchronization": ("days_ahead", "scan_interval"),
        }
        schema = vol.Schema({
            vol.Required(name, default=dict): section(
                vol.Schema({key: value for key, value in schema.schema.items() if key.schema in fields}),
                {"collapsed": False},
            )
            for name, fields in groups.items()
        })
        if user_input is not None:
            # Sections are presentation only; retain the existing option storage format.
            user_input = dict(user_input)
            for name in groups:
                user_input.update(user_input.pop(name, {}))
            if self.student not in students:
                return self.async_show_form(
                    step_id="settings",
                    data_schema=schema,
                    errors={"base": "invalid_student"},
                    description_placeholders={"student": self.student},
                )
            self._enable_day = user_input["enable_day"]
            self._enable_lessons = user_input["enable_lessons"]
            self._enable_holidays = user_input["enable_holidays"]
            self._enable_assessments = user_input.get("enable_assessments", False)
            self._automatic_day_title = old.get("automatic_day_title", False)
            self._pending_settings = {
                key: user_input[key]
                for key in ("days_ahead", "scan_interval")
            }
            for key in ("days_ahead", "scan_interval"):
                self._pending_settings[key] = int(self._pending_settings[key])
            return await self.async_step_destinations()

        return self.async_show_form(
            step_id="settings",
            data_schema=schema,
            description_placeholders={
                "student": students.get(self.student, self.student)
            },
        )

    async def async_step_destinations(self, user_input=None):
        """Choose destination calendars and event titles."""
        students = self._students()
        choices = self._calendar_choices()
        old = self._old_options()
        errors = {}
        enabled_fields = []
        if self._enable_day:
            enabled_fields.append("day_calendar")
        if self._enable_lessons:
            enabled_fields.append("lesson_calendar")
        if self._enable_holidays:
            enabled_fields.append("holiday_calendar")
        if self._enable_assessments:
            enabled_fields.append("assessment_calendar")

        if user_input is not None:
            # Sections are presentation-only. Accept both the sectioned form used by
            # current HA and the flat form used by older clients/tests.
            user_input = dict(user_input)
            for name in ("calendar_destinations", "event_titles"):
                nested = user_input.pop(name, None)
                if isinstance(nested, dict):
                    user_input.update(nested)
            if self.student not in students:
                errors["base"] = "invalid_student"
            elif any(user_input.get(field) not in choices for field in enabled_fields):
                errors["base"] = "invalid_calendar"
            else:
                self._automatic_day_title = user_input.get(
                    "automatic_day_title", old.get("automatic_day_title", False)
                )
                return self._save_options(
                    {
                        "day_calendar": user_input.get("day_calendar", ""),
                        "lesson_calendar": user_input.get("lesson_calendar", ""),
                        "holiday_calendar": user_input.get("holiday_calendar", ""),
                        "assessment_calendar": user_input.get(
                            "assessment_calendar", ""
                        ),
                        "day_title": user_input.get(
                            "day_title", old.get("day_title", "School · {student}")
                        ),
                        "lesson_prefix": user_input.get(
                            "lesson_prefix", old.get("lesson_prefix", "{student} · ")
                        ),
                        "holiday_title": user_input.get(
                            "holiday_title",
                            old.get("holiday_title", "{student} · {holiday}"),
                        ),
                        "holiday_mode": user_input.get(
                            "holiday_mode",
                            old.get("holiday_mode", HOLIDAY_MODE_SCHOOL_DAYS),
                        ),
                        "assessment_title": user_input.get(
                            "assessment_title",
                            old.get(
                                "assessment_title",
                                "{student} · {subject} · {type}",
                            ),
                        ),
                    }
                )

        calendar_schema = {}
        if self._enable_day:
            day_default = old.get("day_calendar")
            day_key = vol.Required("day_calendar")
            if day_default in choices:
                day_key = vol.Required("day_calendar", default=day_default)
            calendar_schema[day_key] = vol.In(choices)
        if self._enable_lessons:
            lesson_default = old.get("lesson_calendar")
            lesson_key = vol.Required("lesson_calendar")
            if lesson_default in choices:
                lesson_key = vol.Required("lesson_calendar", default=lesson_default)
            calendar_schema[lesson_key] = vol.In(choices)
        if self._enable_holidays:
            holiday_default = old.get("holiday_calendar")
            holiday_key = vol.Required("holiday_calendar")
            if holiday_default in choices:
                holiday_key = vol.Required("holiday_calendar", default=holiday_default)
            calendar_schema[holiday_key] = vol.In(choices)
        if self._enable_assessments:
            assessment_default = old.get("assessment_calendar")
            assessment_key = vol.Required("assessment_calendar")
            if assessment_default in choices:
                assessment_key = vol.Required(
                    "assessment_calendar", default=assessment_default
                )
            calendar_schema[assessment_key] = vol.In(choices)

        title_schema = {
            vol.Required(
                "automatic_day_title", default=old.get("automatic_day_title", False)
            ): bool,
            vol.Required(
                "day_title", default=old.get("day_title", "School · {student}")
            ): vol.All(str, vol.Length(min=1, max=100)),
        }
        if self._enable_lessons:
            title_schema[vol.Optional(
                "lesson_prefix", default=old.get("lesson_prefix", "{student} · ")
            )] = str
        if self._enable_holidays:
            title_schema[vol.Required(
                "holiday_title", default=old.get("holiday_title", "{student} · {holiday}")
            )] = vol.All(str, vol.Length(min=1, max=100))
            title_schema[vol.Required(
                "holiday_mode", default=old.get("holiday_mode", HOLIDAY_MODE_SCHOOL_DAYS)
            )] = vol.In(HOLIDAY_MODE_CHOICES)
        if self._enable_assessments:
            title_schema[vol.Required(
                "assessment_title",
                default=old.get("assessment_title", "{student} · {subject} · {type}"),
            )] = vol.All(str, vol.Length(min=1, max=100))

        schema = {}
        if calendar_schema:
            schema[vol.Required("calendar_destinations", default=dict)] = section(
                vol.Schema(calendar_schema), {"collapsed": False}
            )
        schema[vol.Required("event_titles", default=dict)] = section(
            vol.Schema(title_schema), {"collapsed": False}
        )
        if enabled_fields and not choices:
            errors["base"] = "no_writable_calendars"
        return self.async_show_form(
            step_id="destinations",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "student": students.get(self.student, self.student),
                "student_placeholder": "{student}",
                "holiday_placeholder": "{holiday}",
                "subject_placeholder": "{subject}",
                "type_placeholder": "{type}",
                "topic_placeholder": "{topic}",
                "help_url": "https://github.com/digital-IMEI/home-assistant-somtoday#calendar-provider-compatibility",
            },
        )
