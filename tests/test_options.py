from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.somtoday.config_flow import SomtodayOptionsFlow
from homeassistant.helpers.config_validation import custom_serializer
from voluptuous_serialize import convert
import json
from pathlib import Path


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
    assert settings["step_id"] == "calendar_settings"
    assert settings["description_placeholders"] == {"student": "Seth"}
    defaults = settings["data_schema"]({})["exports"]
    assert defaults["enable_day"] is False
    assert defaults["enable_lessons"] is False
    assert defaults["enable_holidays"] is False
    assert defaults["enable_assessments"] is False

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
    assert destinations["step_id"] == "calendar_destinations"
    fields = [key.schema for key in destinations["data_schema"].schema]
    assert fields == ["school_days"]
    calendar_section = next(
        value
        for key, value in destinations["data_schema"].schema.items()
        if key.schema == "school_days"
    )
    calendar_fields = {key.schema for key in calendar_section.schema.schema}
    assert calendar_fields == {"day_calendar", "day_title", "automatic_day_title"}
    calendar_validator = next(
        validator
        for key, validator in calendar_section.schema.schema.items()
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
        "assessment_calendar": "",
        "day_title": "School · {student}",
        "lesson_prefix": "{student} · ",
        "holiday_title": "{student} · {holiday}",
        "holiday_mode": "school_days",
        "assessment_title": "{student} · {subject} · {type}",
    }
    assert "preview" not in result["data"]


@pytest.mark.asyncio
async def test_disabled_exports_still_offer_titles_without_writable_calendars():
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
    defaults = settings["data_schema"]({})["exports"]
    assert defaults["enable_day"] is True
    assert defaults["enable_lessons"] is True
    assert defaults["enable_holidays"] is False
    assert defaults["enable_assessments"] is False
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
    assert result["step_id"] == "calendar_destinations"
    assert not result["errors"]
    result = await flow.async_step_destinations(result["data_schema"]({}))
    assert result["type"] == "create_entry"
    assert result["data"]["exports"]["a"] == {
        "day_calendar": "",
        "lesson_calendar": "",
        "automatic_day_title": False,
        "holiday_calendar": "",
        "assessment_calendar": "",
        "day_title": "Seth school",
        "lesson_prefix": "Seth · ",
        "holiday_title": "{student} · {holiday}",
        "holiday_mode": "school_days",
        "assessment_title": "{student} · {subject} · {type}",
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
            "days_ahead": 60,
            "scan_interval": 30,
        }
    )

    fields = [key.schema for key in destinations["data_schema"].schema]
    assert fields == ["school_days", "holidays", "holiday_layout"]
    result = await flow.async_step_destinations(
        {
            "holiday_calendar": "calendar.school_holidays",
            "holiday_title": "{student} · {holiday}",
            "holiday_mode": "full_weeks",
        }
    )
    assert result["data"]["exports"]["a"]["holiday_calendar"] == (
        "calendar.school_holidays"
    )
    assert result["data"]["exports"]["a"]["holiday_mode"] == "full_weeks"
    assert result["data"]["days_ahead"] == 60


@pytest.mark.asyncio
async def test_assessment_export_has_its_own_destination_and_title():
    flow, _ = make_flow(
        calendar_states=[
            SimpleNamespace(
                entity_id="calendar.tests",
                name="Tests",
                attributes={"supported_features": 3},
            )
        ]
    )
    await flow.async_step_init({"student_id": "a"})

    destinations = await flow.async_step_settings(
        {
            "enable_day": False,
            "enable_lessons": False,
            "enable_holidays": False,
            "enable_assessments": True,
            "days_ahead": 30,
            "scan_interval": 15,
        }
    )

    fields = [key.schema for key in destinations["data_schema"].schema]
    assert fields == ["school_days", "tests"]
    result = await flow.async_step_destinations(
        {
            "assessment_calendar": "calendar.tests",
            "assessment_title": "{student} · {subject} · {type}",
        }
    )
    route = result["data"]["exports"]["a"]
    assert route["assessment_calendar"] == "calendar.tests"
    assert route["assessment_title"] == "{student} · {subject} · {type}"


@pytest.mark.asyncio
async def test_sectioned_settings_preserve_account_and_sibling_options():
    sibling = {"day_calendar": "calendar.other", "day_title": "Other"}
    flow, _ = make_flow(options={
        "days_ahead": 30, "scan_interval": 60,
        "exports": {"b": sibling, "a": {"automatic_day_title": True}},
    })
    form = await flow.async_step_init({"student_id": "a"})
    values = form["data_schema"]({})
    assert [key.schema for key in form["data_schema"].schema] == ["exports", "synchronization"]
    assert values["synchronization"] == {"days_ahead": 30, "scan_interval": 60}
    destinations = await flow.async_step_settings(values)
    titles = destinations["data_schema"]({})
    assert titles["school_days"]["automatic_day_title"] is True
    result = await flow.async_step_destinations(titles)
    assert result["data"]["exports"]["b"] == sibling
    assert result["data"]["exports"]["a"]["automatic_day_title"] is True
    assert result["data"]["days_ahead"] == 30
    assert result["data"]["scan_interval"] == 60


@pytest.mark.asyncio
async def test_serialized_forms_defaults_translations_and_roundtrip():
    route = {"day_calendar": "calendar.family", "lesson_calendar": "calendar.family",
             "holiday_calendar": "calendar.family", "assessment_calendar": "calendar.family",
             "day_title": "School · {student}", "automatic_day_title": True,
             "holiday_mode": "full_weeks"}
    states = [SimpleNamespace(entity_id="calendar.family", name="Family", attributes={"supported_features": 3})]
    flow, entry = make_flow({"exports": {"a": route, "b": {"day_title": "Sibling"}}, "days_ahead": 30, "scan_interval": 60}, states)
    settings = await flow.async_step_init({"student_id": "a"})
    serialized = convert(settings["data_schema"], custom_serializer=custom_serializer)
    # Match the actual data supplied to the frontend, not schema({}) which fills
    # missing nested defaults and used to hide the empty-section regression.
    values = {field["name"]: field["default"] for field in serialized}
    assert values["exports"]["enable_day"] is True
    assert values["synchronization"] == {"days_ahead": 30, "scan_interval": 60}
    destinations = await flow.async_step_calendar_settings(values)
    serialized_dest = convert(destinations["data_schema"], custom_serializer=custom_serializer)
    values = {field["name"]: field["default"] for field in serialized_dest}
    assert values["school_days"]["automatic_day_title"] is True
    assert values["holiday_layout"]["holiday_mode"] == "full_weeks"
    assert [field["name"] for field in serialized_dest] == ["school_days", "lessons", "holidays", "holiday_layout", "tests"]
    for language in ("en", "nl"):
        translations = json.loads((Path(__file__).parents[1] / "custom_components/somtoday/translations" / f"{language}.json").read_text())
        for form, fields in ((settings, serialized), (destinations, serialized_dest)):
            step = translations["options"]["step"][form["step_id"]]
            for group in fields:
                section_text = step["sections"][group["name"]]
                assert section_text["name"]
                for field in group["schema"]:
                    assert section_text["data"][field["name"]]
        layout = translations["options"]["step"]["calendar_destinations"]["sections"]["holiday_layout"]
        assert layout["description"]
        assert "holiday_mode" not in layout["data_description"]
        assert set(translations["selector"]["holiday_mode"]["options"]) == {"school_days", "full_weeks", "daily"}
    values["school_days"]["day_title"] = "New · {student}"
    result = await flow.async_step_calendar_destinations(values)
    assert result["data"]["exports"]["b"] == entry.options["exports"]["b"]
    reopened, _ = make_flow(result["data"], states)
    again = await reopened.async_step_init({"student_id": "a"})
    dest = await reopened.async_step_calendar_settings(again["data_schema"]({}))
    assert dest["data_schema"]({})["school_days"]["day_title"] == "New · {student}"


@pytest.mark.asyncio
async def test_invalid_destination_keeps_edited_title():
    flow, _ = make_flow()
    await flow.async_step_init({"student_id": "a"})
    await flow.async_step_settings({"enable_day": True, "enable_lessons": False, "enable_holidays": False, "days_ahead": 1, "scan_interval": 15})
    form = await flow.async_step_destinations({"school_days": {"day_calendar": "calendar.missing", "day_title": "Keep this"}})
    fields = convert(form["data_schema"], custom_serializer=custom_serializer)
    assert fields[0]["default"]["day_title"] == "Keep this"
