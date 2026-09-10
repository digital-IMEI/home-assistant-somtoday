from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.somtoday.config_flow import SomtodayOptionsFlow


@pytest.mark.asyncio
async def test_per_child_options_preserve_other_child_and_schema():
    entry = SimpleNamespace(
        entry_id="entry",
        options={
            "exports": {"b": {"day_calendar": "calendar.family"}},
            "preview": True,
        },
    )
    students = [
        {"links": [{"id": student_id}], "roepnaam": name}
        for student_id, name in (("a", "Seth"), ("b", "Other child"))
    ]
    hass = SimpleNamespace(
        data={"somtoday": {"entry": SimpleNamespace(data={"students": students})}},
        config_entries=SimpleNamespace(async_get_known_entry=lambda _: entry),
        states=SimpleNamespace(
            async_all=lambda _: [
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
            ]
        ),
    )
    flow = SomtodayOptionsFlow()
    flow.hass = hass
    flow.handler = "entry"
    first = await flow.async_step_init()
    assert first["data_schema"]({"student_id": "a"})["student_id"] == "a"
    settings = await flow.async_step_init({"student_id": "a"})
    assert settings["step_id"] == "settings"
    assert settings["description_placeholders"] == {"student": "Seth"}
    day_calendar_validator = next(
        validator
        for key, validator in settings["data_schema"].schema.items()
        if key.schema == "day_calendar"
    )
    assert day_calendar_validator("calendar.family") == "calendar.family"
    with pytest.raises(vol.Invalid):
        day_calendar_validator("calendar.read_only")
    data = settings["data_schema"]({})
    assert data["preview"] is True
    assert data["day_title"] == "School · {student}"
    result = await flow.async_step_settings(data)
    assert result["data"]["exports"]["b"] == entry.options["exports"]["b"]
    assert result["data"]["exports"]["a"]["day_calendar"] == ""
