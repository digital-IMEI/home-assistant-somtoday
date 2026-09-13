from datetime import datetime, timedelta
from types import SimpleNamespace

from homeassistant.const import EntityCategory

from custom_components.somtoday.calendar import (
    SomtodayAssessmentCalendar,
    SomtodayCalendar,
    SomtodaySchoolDayCalendar,
)
from custom_components.somtoday.sensor import (
    SomtodayNextAssessmentSensor,
    SomtodaySyncSensor,
)
from custom_components.somtoday.event import SomtodayAssessmentChangeEvent
from custom_components.somtoday.button import SomtodayRetryCalendarSyncButton
from custom_components.somtoday import _remove_legacy_school_day_sensors


START = datetime.fromisoformat("2026-09-10T09:20:00+02:00")


def test_each_child_has_lesson_and_school_day_calendar_entities():
    student = {"links": [{"id": "a"}], "roepnaam": "Seth"}
    lesson = {
        "links": [{"id": "lesson-1"}],
        "beginDatumTijd": START.isoformat(),
        "eindDatumTijd": (START + timedelta(minutes=50)).isoformat(),
        "titel": "Math",
        "afspraakStatus": "ACTIEF",
    }
    coordinator = SimpleNamespace(
        data={
            "appointments_by_student": {"a": [lesson]},
            "school_days_by_student": {
                "a": {
                    "2026-09-10": (START, START + timedelta(hours=5, minutes=40))
                }
            },
        }
    )
    entry = SimpleNamespace(entry_id="entry", options={})

    schedule = SomtodayCalendar(coordinator, entry, student, legacy=True)
    school_day = SomtodaySchoolDayCalendar(coordinator, entry, student, legacy=True)
    schedule_events = schedule._events(START - timedelta(hours=1), START + timedelta(days=1))
    school_day_events = school_day._events(
        START - timedelta(hours=1), START + timedelta(days=1)
    )

    assert schedule._attr_unique_id == "entry_schedule"
    assert schedule._attr_name == "Seth · Rooster"
    assert len(schedule_events) == 1
    assert schedule_events[0].summary == "Math"
    assert school_day._attr_unique_id == "entry_school_day"
    assert school_day._attr_name == "Seth · Schooldag"
    assert school_day._attr_icon == "mdi:school"
    assert len(school_day_events) == 1
    assert school_day_events[0].summary == "Schooldag"
    assert school_day_events[0].start == START
    assert school_day_events[0].end == START + timedelta(hours=5, minutes=40)


def test_calendar_sync_sensor_is_diagnostic():
    coordinator = SimpleNamespace(data={"sync_status": {"mode": "waiting"}})
    sensor = SomtodaySyncSensor(coordinator, SimpleNamespace(entry_id="entry"))

    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.native_value == "waiting"


def test_calendar_sync_retry_button_is_diagnostic():
    coordinator = SimpleNamespace()
    button = SomtodayRetryCalendarSyncButton(
        coordinator, SimpleNamespace(entry_id="entry")
    )

    assert button.entity_category is EntityCategory.DIAGNOSTIC
    assert button.unique_id == "entry_calendar_sync_retry"


def test_each_child_has_assessment_calendar_and_next_sensor(monkeypatch):
    student = {"links": [{"id": "a"}], "roepnaam": "Seth"}
    assessment = {
        "id": "test-1",
        "type": "TOETS",
        "type_label": "Toets",
        "subject": "Wiskunde",
        "topic": "Hoofdstuk 3",
        "description": "Leer paragraaf 3.1",
        "made": False,
        "date_known": True,
        "all_day": True,
        "start": START.date(),
        "end": START.date() + timedelta(days=1),
    }
    coordinator = SimpleNamespace(
        data={"assessments_by_student": {"a": [assessment]}}
    )
    entry = SimpleNamespace(entry_id="entry")
    calendar = SomtodayAssessmentCalendar(coordinator, entry, student)
    sensor = SomtodayNextAssessmentSensor(coordinator, entry, student)
    monkeypatch.setattr(
        "custom_components.somtoday.sensor.dt_util.now",
        lambda: datetime.fromisoformat("2026-09-09T12:00:00+02:00"),
    )

    events = calendar._events(
        START - timedelta(days=1), START + timedelta(days=1)
    )
    assert calendar._attr_name == "Seth · Toetsen"
    assert calendar._attr_icon == "mdi:clipboard-text-clock-outline"
    assert events[0].summary == "Wiskunde · Toets · Hoofdstuk 3"
    assert events[0].description.endswith("Afgerond: nee")
    assert sensor.native_value.date() == START.date()
    assert sensor.extra_state_attributes == {
        "undated_count": 0,
        "subject": "Wiskunde",
        "assessment_type": "Toets",
        "topic": "Hoofdstuk 3",
        "days_until": 1,
        "all_day": True,
        "made": False,
    }


def test_assessment_change_event_does_not_fire_initial_snapshot_and_reports_additions():
    student = {"links": [{"id": "a"}], "roepnaam": "Seth"}
    coordinator = SimpleNamespace(data={"assessments_by_student": {"a": []}})
    entity = SomtodayAssessmentChangeEvent(
        coordinator, SimpleNamespace(entry_id="entry"), student
    )
    fired = []
    entity._trigger_event = lambda event_type, data: fired.append((event_type, data))
    entity.async_write_ha_state = lambda: None
    coordinator.data["assessments_by_student"]["a"] = [
        {
            "id": "test-1",
            "type": "TOETS",
            "type_label": "Toets",
            "subject": "Wiskunde",
            "topic": "Hoofdstuk 3",
            "made": False,
            "date_known": False,
            "start": None,
            "end": None,
        }
    ]

    entity._handle_coordinator_update()

    assert fired == [
        (
            "added",
            {
                "assessment_id": "test-1",
                "subject": "Wiskunde",
                "assessment_type": "Toets",
                "topic": "Hoofdstuk 3",
                "date_known": False,
                "start": None,
            },
        )
    ]


def test_assessment_change_ignores_items_that_only_aged_out(monkeypatch):
    student = {"links": [{"id": "a"}], "roepnaam": "Seth"}
    old = {
        "id": "old-test",
        "type": "TOETS",
        "type_label": "Toets",
        "subject": "Wiskunde",
        "topic": "",
        "made": None,
        "date_known": True,
        "start": datetime.fromisoformat("2026-09-12T09:00:00+02:00"),
        "end": datetime.fromisoformat("2026-09-12T10:00:00+02:00"),
    }
    coordinator = SimpleNamespace(data={"assessments_by_student": {"a": [old]}})
    entity = SomtodayAssessmentChangeEvent(
        coordinator, SimpleNamespace(entry_id="entry"), student
    )
    fired = []
    entity._trigger_event = lambda event_type, data: fired.append((event_type, data))
    entity.async_write_ha_state = lambda: None
    monkeypatch.setattr(
        "custom_components.somtoday.event.dt_util.now",
        lambda: datetime.fromisoformat("2026-09-13T12:00:00+02:00"),
    )
    coordinator.data["assessments_by_student"]["a"] = []

    entity._handle_coordinator_update()

    assert fired == []


def test_old_school_day_timestamp_sensors_are_removed(monkeypatch):
    removed = []
    known = {
        "entry_school_day": "sensor.seth_schooldag",
        "entry_b_school_day": "sensor.other_schooldag",
    }
    registry = SimpleNamespace(
        async_get_entity_id=lambda domain, platform, unique_id: known.get(unique_id),
        async_remove=removed.append,
    )
    import custom_components.somtoday as integration

    monkeypatch.setattr(integration.er, "async_get", lambda hass: registry)
    students = [
        {"links": [{"id": "a"}]},
        {"links": [{"id": "b"}]},
    ]

    _remove_legacy_school_day_sensors(
        SimpleNamespace(), SimpleNamespace(entry_id="entry"), students
    )

    assert set(removed) == {"sensor.seth_schooldag", "sensor.other_schooldag"}
