from types import SimpleNamespace

import pytest

from custom_components.somtoday.config_flow import SomtodayOptionsFlow


@pytest.mark.asyncio
async def test_per_child_options_preserve_other_child_and_schema(monkeypatch):
    import custom_components.somtoday.config_flow as module
    from homeassistant.helpers import entity_registry

    entry = SimpleNamespace(entry_id="entry", options={
        "exports": {"b": {"day_calendar": "calendar.family"}}, "preview": True,
    })
    students = [{"links": [{"id": s}], "roepnaam": name}
                for s, name in (("a", "Seth"), ("b", "Other child"))]
    hass = SimpleNamespace(
        data={"somtoday": {"entry": SimpleNamespace(data={"students": students})}},
        config_entries=SimpleNamespace(async_get_known_entry=lambda _: entry),
        states=SimpleNamespace(async_all=lambda _: []),
    )
    monkeypatch.setattr(entity_registry, "async_get", lambda _: SimpleNamespace(async_get=lambda _: None))
    flow = SomtodayOptionsFlow(); flow.hass = hass; flow.handler = "entry"
    first = await flow.async_step_init()
    assert first["data_schema"]({"student_id": "a"})["student_id"] == "a"
    settings = await flow.async_step_init({"student_id": "a"})
    assert settings["step_id"] == "settings"
    assert settings["description_placeholders"] == {"student": "Seth"}
    data = settings["data_schema"]({})
    assert data["preview"] is True
    assert data["day_title"] == "School · {student}"
    result = await flow.async_step_settings(data)
    assert result["data"]["exports"]["b"] == entry.options["exports"]["b"]
    assert result["data"]["exports"]["a"]["day_calendar"] == ""
