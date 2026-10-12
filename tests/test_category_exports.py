from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.somtoday.calendar import SomtodayCalendar
from custom_components.somtoday.export import desired_events
from test_options import make_flow

START = datetime.fromisoformat("2026-10-12T00:00:00+02:00")
END = START + timedelta(days=1)


def appointment(identifier, category, title, subject=None, status="ACTIEF"):
    return {"links": [{"id": identifier}], "titel": title,
            "beginDatumTijd": START.replace(hour=8, minute=30).isoformat(),
            "eindDatumTijd": START.replace(hour=9, minute=20).isoformat(),
            "afspraakStatus": status, "afspraakType": {"categorie": category, "standaardKleur": 0},
            "omschrijving": "<p>Leren hoofdstuk 1</p>", "locatie": "211",
            "additionalObjects": {"vak": {"naam": subject}} if subject else {}}


def test_real_school_categories_route_independently_of_titles_and_colors():
    items = [appointment("green", "Individueel", "proefwerk Nederlands "),
             appointment("blue", "Toets", "211 - Toets SP - ne - lic31", "Nederlandse taal"),
             appointment("lesson", "Rooster", "224 - gah1.la3 - BRA31", "Latijn"),
             appointment("activity", "Activiteit", "Excursie"),
             appointment("cancelled", "Toets", "Toets", status="GEANNULEERD")]
    original = deepcopy(items)
    route = {"lesson_calendar": "calendar.family", "schedule_test_calendar": "calendar.family",
             "other_calendar": "calendar.family", "other_prefix": "Seth · ", "schedule_test_prefix": "Seth · "}
    events = desired_events(items, route, "a", START, END)
    assert len(events) == 4
    assert events[("calendar.family", "a:other:green")]["summary"] == "Seth · proefwerk Nederlands "
    assert events[("calendar.family", "a:schedule_test:blue")]["summary"] == "Seth · Nederlandse taal"
    assert events[("calendar.family", "a:lesson:lesson")]["summary"] == "Latijn"
    assert events[("calendar.family", "a:other:green")]["description"] == "<p>Leren hoofdstuk 1</p>"
    assert events[("calendar.family", "a:schedule_test:blue")]["location"] == "211"
    assert items == original
    coordinator = SimpleNamespace(data={"appointments_by_student": {"a": items}})
    calendar = SomtodayCalendar(coordinator, SimpleNamespace(entry_id="e"), {"links": [{"id": "a"}]})
    assert [event.summary for event in calendar._events(START, END)] == ["Latijn"]
    assert len(calendar.extra_state_attributes["appointment_debug"]) == 5


def test_new_exports_are_opt_in_and_do_not_require_study_guide_data():
    items = [appointment("test", "Toets", "Reading period"), appointment("individual", "Individueel", "Meeting")]
    assert desired_events(items, {"lesson_calendar": "calendar.lessons"}, "a", START, END) == {}
    assert len(desired_events(items, {"schedule_test_calendar": "calendar.tests"}, "a", START, END)) == 1
    assert len(desired_events(items, {"other_calendar": "calendar.other"}, "a", START, END)) == 1


@pytest.mark.asyncio
async def test_category_export_options_roundtrip_disable_and_preserve_sibling():
    sibling = {"other_calendar": "calendar.sibling"}
    states = [SimpleNamespace(entity_id="calendar.family", name="Family", attributes={"supported_features": 3})]
    flow, _ = make_flow({"exports": {"b": sibling}}, states)
    settings = await flow.async_step_init({"student_id": "a"})
    values = settings["data_schema"]({})
    assert values["exports"]["enable_schedule_tests"] is False
    assert values["exports"]["enable_other"] is False
    values["exports"].update(enable_schedule_tests=True, enable_other=True)
    destinations = await flow.async_step_settings(values)
    submitted = destinations["data_schema"]({
        "schedule_tests": {"schedule_test_calendar": "calendar.family", "schedule_test_prefix": "Seth · "},
        "other_appointments": {"other_calendar": "calendar.family", "other_prefix": ""}})
    result = await flow.async_step_destinations(submitted)
    route = result["data"]["exports"]["a"]
    assert route["schedule_test_calendar"] == route["other_calendar"] == "calendar.family"
    assert route["other_prefix"] == ""
    assert result["data"]["exports"]["b"] == sibling
    reopened, _ = make_flow(result["data"], states)
    settings = await reopened.async_step_init({"student_id": "a"})
    values = settings["data_schema"]({})
    assert values["exports"]["enable_schedule_tests"] is True
    assert values["exports"]["enable_other"] is True
    values["exports"].update(enable_schedule_tests=False, enable_other=False)
    destinations = await reopened.async_step_settings(values)
    disabled = await reopened.async_step_destinations(destinations["data_schema"]({}))
    assert disabled["data"]["exports"]["a"]["other_calendar"] == ""
    assert disabled["data"]["exports"]["a"]["schedule_test_calendar"] == ""
    assert disabled["data"]["exports"]["b"] == sibling
