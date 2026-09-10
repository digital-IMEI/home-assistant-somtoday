from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.somtoday.export import desired_events, select_student, marker, scope_marker
from custom_components.somtoday.sync import CalendarSync

START = datetime.fromisoformat("2026-09-10T00:00:00+02:00")
END = START + timedelta(days=14)


def lesson(identifier="1", hour=9, pupils=("a",)):
    return {"links": [{"id": identifier}], "beginDatumTijd": START.replace(hour=hour).isoformat(),
            "eindDatumTijd": START.replace(hour=hour+1).isoformat(), "titel": "Math",
            "afspraakType": {"categorie": "Rooster"},
            "additionalObjects": {"leerlingen": {"items": [{"links": [{"id": p}]} for p in pupils]}}}


def test_children_are_not_merged():
    students = [{"links": [{"id": s}]} for s in ("a", "b")]
    _, selected = select_student([lesson(), lesson("2", 14, ("b",))], students, "a")
    events = desired_events(selected, {"day_calendar": "calendar.family"}, "a", START, END)
    assert len(events) == 1
    assert next(iter(events.values()))["dtend"].hour == 10
    with pytest.raises(ValueError):
        select_student([{"additionalObjects": {}}], students, "a")


def test_modes_same_calendar_and_status_changes():
    options = {"day_calendar": "calendar.family", "lesson_calendar": "calendar.family"}
    lessons = [lesson(), lesson("2", 14)]
    result = desired_events(lessons, options, "a", START, END)
    assert len(result) == 3
    lessons[-1]["afspraakStatus"] = "GEANNULEERD"
    result = desired_events(lessons, options, "a", START, END)
    assert len(result) == 2
    assert result[("calendar.family", "a:day:2026-09-10")]["dtend"].hour == 10


class MemoryStore:
    def __init__(self): self.data = {}
    async def async_load(self): return dict(self.data)
    async def async_save(self, data): self.data = dict(data)


class FakeCalendar:
    available = True
    supported_features = 3
    def __init__(self): self.events = []; self.creates = 0; self.fail = False
    async def async_get_events(self, hass, start, end): return list(self.events)
    async def async_create_event(self, **values):
        self.creates += 1
        self.events.append(SimpleNamespace(uid=str(self.creates), start=values["dtstart"],
            end=values["dtend"], start_datetime_local=values["dtstart"],
            summary=values["summary"], description=values["description"],
            location=values["location"], recurrence_id=None, rrule=None))
        if self.fail: raise TimeoutError()
    async def async_delete_event(self, uid): self.events = [e for e in self.events if e.uid != uid]
    def async_write_ha_state(self): pass


def synchronizer(calendar, monkeypatch, store=None):
    import custom_components.somtoday.sync as module
    monkeypatch.setattr(module, "Store", lambda *a: store or MemoryStore())
    monkeypatch.setattr(module, "target_entity", lambda *a: calendar)
    return CalendarSync(None, SimpleNamespace(entry_id="test"))


@pytest.mark.asyncio
async def test_preview_idempotence_replacement_cancellation_and_foreign_events(monkeypatch):
    calendar = FakeCalendar()
    sync = synchronizer(calendar, monkeypatch)
    targets = {"calendar.family": {scope_marker("test", "a:lesson")}}
    options = {"lesson_calendar": "calendar.family"}
    desired = desired_events([lesson()], options, "a", START, END)
    assert (await sync.run(desired, targets, START, END, True))["create"] == 1
    assert calendar.creates == 0
    await sync.run(desired, targets, START, END, False)
    await sync.run(desired, targets, START, END, False)
    assert calendar.creates == 1
    changed = desired_events([lesson(hour=11)], options, "a", START, END)
    await sync.run(changed, targets, START, END, False)
    assert calendar.creates == 2 and len(calendar.events) == 1
    foreign = SimpleNamespace(uid="foreign", description="My own appointment")
    disabled_child = SimpleNamespace(uid="disabled", description=marker("test", "b:lesson:1"))
    calendar.events.extend([foreign, disabled_child])
    await sync.run({}, targets, START, END, False)
    assert calendar.events == [foreign, disabled_child]


@pytest.mark.asyncio
async def test_timeout_after_remote_create_recovers_without_duplicate_after_restart(monkeypatch):
    calendar = FakeCalendar(); calendar.fail = True
    store = MemoryStore()
    sync = synchronizer(calendar, monkeypatch, store)
    targets = {"calendar.family": {scope_marker("test", "a:lesson")}}
    desired = desired_events([lesson()], {"lesson_calendar": "calendar.family"}, "a", START, END)
    with pytest.raises(TimeoutError): await sync.run(desired, targets, START, END, False)
    sync = synchronizer(calendar, monkeypatch, store)
    calendar.fail = False
    await sync.run(desired, targets, START, END, False)
    assert calendar.creates == 1


@pytest.mark.asyncio
async def test_uncertain_missing_write_never_blindly_retried(monkeypatch):
    calendar = FakeCalendar(); calendar.fail = True
    store = MemoryStore(); sync = synchronizer(calendar, monkeypatch, store)
    targets = {"calendar.family": {scope_marker("test", "a:lesson")}}
    desired = desired_events([lesson()], {"lesson_calendar": "calendar.family"}, "a", START, END)
    with pytest.raises(TimeoutError): await sync.run(desired, targets, START, END, False)
    calendar.events.clear()
    with pytest.raises(ValueError): await sync.run(desired, targets, START, END, False)
    assert calendar.creates == 1
