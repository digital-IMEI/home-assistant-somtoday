from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.somtoday.config_flow import SomtodayOptionsFlow


def make_flow(options=None, calendar_states=None):
    """Create an options flow with two children and configurable calendars."""
    entry = SimpleNamespace(entry_id="entry", options=options or {})
    students = [
        {"links": [{"id": student_id}], "roepnaam": name}
        for student_id, name in (("a", "Seth"), ("b", "Other child"))
    ]
    hass = SimpleNamespace(
        data={"somtoday": {"entry": SimpleNamespace(data={"students": students})}},
        config_entries=SimpleNamespace(async_get_known_entry=lambda _: entry),
        states=SimpleNamespace(async_all=lambda _: calendar_states or []),
    )
    flow = SomtodayOptionsFlow()
    flow.hass = hass
    flow.handler = "entry"
    return flow, entry


@pytest.mark.asyncio
async def test_enabled_school_day_shows_only_its_destination_and_preserves_sibling():
    flow, entry = make_flow(
        options={
            "exports": {"b": {"day_calendar": "calendar.family"}},
            "preview": True,
        },
        calendar_states=[
            SimpleNamespace(
                entity_id="calendar.family",
                name="Family",
                attributes={"supported_features": 3},
            ),
            SimpleNamespace(
                entity_id="calendar.read_only",
                name="Read only",
                attributes={"supported_features": 0},
            ),
        ],
    )

    first = await flow.async_step_init()
    assert first["data_schema"]({"student_id": "a"})["student_id"] == "a"

    settings = await flow.async_step_init({"student_id": "a"})
    assert settings["step_id"] == "settings"
    assert settings["description_placeholders"] == {"student": "Seth"}
    defaults = settings["data_schema"]({})
    assert defaults["enable_day"] is False
    assert defaults["enable_lessons"] is False
    assert defaults["enable_holidays"] is False

    destinations = await flow.async_step_settings(
        {
            "enable_day": True,
            "enable_lessons": False,
            "enable_holidays": False,
            "preview": False,
            "days_ahead": 14,
            "scan_interval": 15,
        }
    )
    assert destinations["step_id"] == "destinations"
    fields = {key.schema for key in destinations["data_schema"].schema}
    assert fields == {"day_calendar", "day_title"}
    calendar_validator = next(
        validator
        for key, validator in destinations["data_schema"].schema.items()
        if key.schema == "day_calendar"
    )
    assert calendar_validator("calendar.family") == "calendar.family"
    with pytest.raises(vol.Invalid):
        calendar_validator("calendar.read_only")

    result = await flow.async_step_destinations(
        {"day_calendar": "calendar.family", "day_title": "School · {student}"}
    )
    assert result["data"]["exports"]["b"] == entry.options["exports"]["b"]
    assert result["data"]["exports"]["a"] == {
        "day_calendar": "calendar.family",
        "lesson_calendar": "",
        "automatic_day_title": False,
        "holiday_calendar": "",
        "day_title": "School · {student}",
        "lesson_prefix": "{student} · ",
        "holiday_title": "{student} · {holiday}",
    }
    assert "preview" not in result["data"]


@pytest.mark.asyncio
async def test_disabling_both_exports_saves_without_destination_step():
    flow, _ = make_flow(
        options={
            "exports": {
                "a": {
                    "day_calendar": "calendar.family",
                    "lesson_calendar": "calendar.school",
                    "day_title": "Seth school",
                    "lesson_prefix": "Seth · ",
                }
            }
        }
    )
    settings = await flow.async_step_init({"student_id": "a"})
    defaults = settings["data_schema"]({})
    assert defaults["enable_day"] is True
    assert defaults["enable_lessons"] is True
    assert defaults["enable_holidays"] is False
    result = await flow.async_step_settings(
        {
            "enable_day": False,
            "enable_lessons": False,
            "enable_holidays": False,
            "preview": True,
            "days_ahead": 14,
            "scan_interval": 15,
        }
    )
    assert result["type"] == "create_entry"
    assert result["data"]["exports"]["a"] == {
        "day_calendar": "",
        "lesson_calendar": "",
        "automatic_day_title": False,
        "holiday_calendar": "",
        "day_title": "Seth school",
        "lesson_prefix": "Seth · ",
        "holiday_title": "{student} · {holiday}",
    }


@pytest.mark.asyncio
async def test_holiday_export_has_its_own_calendar_and_title():
    flow, _ = make_flow(
        calendar_states=[
            SimpleNamespace(
                entity_id="calendar.school_holidays",
                name="School holidays",
                attributes={"supported_features": 3},
            )
        ]
    )
    await flow.async_step_init({"student_id": "a"})

    destinations = await flow.async_step_settings(
        {
            "enable_day": False,
            "enable_lessons": False,
            "enable_holidays": True,
            "preview": False,
            "days_ahead": 30,
            "scan_interval": 30,
        }
    )

    fields = {key.schema for key in destinations["data_schema"].schema}
    assert fields == {"holiday_calendar", "holiday_title"}
    result = await flow.async_step_destinations(
        {
            "holiday_calendar": "calendar.school_holidays",
            "holiday_title": "{student} · {holiday}",
        }
    )
    assert result["data"]["exports"]["a"]["holiday_calendar"] == (
        "calendar.school_holidays"
    )
    assert result["data"]["days_ahead"] == 30
