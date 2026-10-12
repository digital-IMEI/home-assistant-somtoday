from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

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
    assert schedule._attr_name == "Rooster"
    assert len(schedule_events) == 1
    assert schedule_events[0].summary == "Math"
    assert school_day._attr_unique_id == "entry_school_day"
    assert school_day._attr_name == "Schooldag"
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
    assert calendar._attr_name == "Toetsen"
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


def test_all_child_entities_group_by_stable_student_identity():
    from custom_components.somtoday.binary_sensor import SomtodayHolidaySensor
    from custom_components.somtoday.sensor import SomtodayAbsenceSensor, SomtodayLessonRegistrationSensor
    from custom_components.somtoday.switch import SomtodayLiveActivitySwitch
    from custom_components.somtoday.device import student_device_info, account_device_info
    entry = SimpleNamespace(entry_id="entry", options={})
    coordinator = SimpleNamespace(data={})
    child = {"links": [{"id": "a"}], "roepnaam": "Seth"}
    factories = [SomtodayCalendar, SomtodaySchoolDayCalendar, SomtodayAssessmentCalendar,
                 SomtodayNextAssessmentSensor, SomtodayAbsenceSensor,
                 SomtodayLessonRegistrationSensor, SomtodayHolidaySensor,
                 SomtodayAssessmentChangeEvent, SomtodayLiveActivitySwitch]
    for factory in factories:
        entity = factory(coordinator, entry, child)
        assert entity.device_info == student_device_info(entry, child)
    renamed = {**child, "roepnaam": "Sam"}
    sibling = {"links": [{"id": "b"}], "roepnaam": "Seth"}
    assert student_device_info(entry, renamed)["identifiers"] == student_device_info(entry, child)["identifiers"]
    assert student_device_info(entry, sibling)["identifiers"] != student_device_info(entry, child)["identifiers"]
    other_entry = SimpleNamespace(entry_id="other", options={})
    assert student_device_info(other_entry, child)["identifiers"] != student_device_info(entry, child)["identifiers"]
    for factory in (SomtodaySyncSensor, SomtodayRetryCalendarSyncButton):
        assert factory(coordinator, entry).device_info == account_device_info(entry)
    assert SomtodayCalendar(coordinator, entry, child, legacy=True).unique_id == "entry_schedule"
    assert SomtodaySchoolDayCalendar(coordinator, entry, child, legacy=True).unique_id == "entry_school_day"


@pytest.mark.asyncio
async def test_device_attachment_preserves_registered_ids_and_user_names(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import entity_registry as er
    hass = HomeAssistant(str(tmp_path))
    registry = er.EntityRegistry(hass)
    # The entity registry resolves device IDs through the device registry.
    devices = SimpleNamespace(devices={"child-a": Mock(), "child-b": Mock()},
                              async_is_composite_device_id=lambda _: False,
                              async_wait_loaded=AsyncMock())
    monkeypatch.setattr(er.dr, "async_get", lambda _: devices)
    await registry.async_load()
    for uid, device in (("entry_schedule", "child-a"), ("entry_b_schedule", "child-b")):
        original = registry.async_get_or_create("calendar", "somtoday", uid,
                                               suggested_object_id=uid)
        registry.async_update_entity(original.entity_id, name="Mijn agenda")
        updated = registry.async_get_or_create("calendar", "somtoday", uid,
                                              device_id=device, original_name="Rooster",
                                              has_entity_name=True)
        assert updated.entity_id == original.entity_id
        assert updated.id == original.id
        assert updated.name == "Mijn agenda"
        assert updated.device_id == device
    assert len(registry.entities) == 2
    await hass.async_stop()
