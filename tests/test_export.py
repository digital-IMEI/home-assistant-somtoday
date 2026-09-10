from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.somtoday.export import (
    desired_events,
    desired_holiday_events,
    marker,
    scope_marker,
    select_student,
)
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
    def __init__(self): self.events = []; self.creates = 0; self.reads = 0; self.fail = False
    async def async_get_events(self, hass, start, end):
        self.reads += 1
        return list(self.events)
    async def async_create_event(self, **values):
        self.creates += 1
        self.events.append(SimpleNamespace(uid=str(self.creates), start=values["dtstart"],
            end=values["dtend"], start_datetime_local=values["dtstart"],
            summary=values["summary"], description=values["description"],
            location=values["location"], recurrence_id=None, rrule=None))
        if self.fail: raise TimeoutError()
    async def async_delete_event(self, uid): self.events = [e for e in self.events if e.uid != uid]
    def async_write_ha_state(self): pass


class DelayedCalendar(FakeCalendar):
    """Hide a successful create until a later provider refresh."""

    def __init__(self):
        super().__init__()
        self.hidden = []
    async def async_get_events(self, hass, start, end):
        self.reads += 1
        if self.reads >= 3:
            self.events.extend(self.hidden)
            self.hidden.clear()
        return list(self.events)

    async def async_create_event(self, **values):
        await super().async_create_event(**values)
        self.hidden.append(self.events.pop())


class FakeServices:
    def __init__(self, calendar):
        self.calendar = calendar
        self.calls = []

    def has_service(self, domain, service):
        return domain == "google" and service == "create_event"

    async def async_call(
        self, domain, service, data, blocking=False, target=None, **kwargs
    ):
        self.calls.append((domain, service, data, target, blocking))
        await self.calendar.async_create_event(
            dtstart=data.get("start_date_time", data.get("start_date")),
            dtend=data.get("end_date_time", data.get("end_date")),
            summary=data["summary"],
            description=data["description"],
            location=data.get("location", ""),
        )


def synchronizer(calendar, monkeypatch, store=None, provider="local_calendar"):
    import custom_components.somtoday.sync as module
    services = FakeServices(calendar)
    hass = SimpleNamespace(services=services)
    monkeypatch.setattr(module, "Store", lambda *a: store or MemoryStore())
    monkeypatch.setattr(module, "target_entity", lambda *a: calendar)
    monkeypatch.setattr(
        module.er,
        "async_get",
        lambda _: SimpleNamespace(
            async_get=lambda entity_id: SimpleNamespace(platform=provider)
        ),
    )
    sync = CalendarSync(hass, SimpleNamespace(entry_id="test"))
    sync.test_services = services
    return sync


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
async def test_successful_delayed_create_waits_and_recovers_without_duplicate(monkeypatch):
    calendar = DelayedCalendar()
    store = MemoryStore()
    sync = synchronizer(calendar, monkeypatch, store)
    targets = {"calendar.family": {scope_marker("test", "a:lesson")}}
    desired = desired_events([lesson()], {"lesson_calendar": "calendar.family"}, "a", START, END)

    waiting = await sync.run(desired, targets, START, END, False)
    assert waiting["mode"] == "waiting"
    assert waiting["pending"] == 1
    assert calendar.creates == 1

    completed = await sync.run(desired, targets, START, END, False)
    assert completed["mode"] == "enabled"
    assert completed["unchanged"] == 1
    assert calendar.creates == 1


@pytest.mark.asyncio
async def test_legacy_uncertain_write_becomes_waiting_without_retry(monkeypatch):
    calendar = FakeCalendar()
    store = MemoryStore()
    sync = synchronizer(calendar, monkeypatch, store)
    targets = {"calendar.family": {scope_marker("test", "a:lesson")}}
    desired = desired_events(
        [lesson()], {"lesson_calendar": "calendar.family"}, "a", START, END
    )
    tag = marker("test", "a:lesson:1")
    store.data["calendar.family|" + tag] = True
    sync.pending = None

    result = await sync.run(desired, targets, START, END, False)
    assert result["mode"] == "waiting"
    assert result["pending"] == 1
    assert calendar.creates == 0
    assert isinstance(next(iter(store.data.values())), str)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "expected_domain"),
    (("google", "google"), ("local_calendar", "calendar")),
)
async def test_create_uses_provider_appropriate_ha_action(
    monkeypatch, provider, expected_domain
):
    calendar = FakeCalendar()
    sync = synchronizer(calendar, monkeypatch, provider=provider)
    targets = {"calendar.family": {scope_marker("test", "a:lesson")}}
    desired = desired_events(
        [lesson()], {"lesson_calendar": "calendar.family"}, "a", START, END
    )

    await sync.run(desired, targets, START, END, False)

    domain, service, data, target, blocking = sync.test_services.calls[0]
    assert (domain, service) == (expected_domain, "create_event")
    assert target == {"entity_id": "calendar.family"}
    assert blocking is True
    assert data["description"].startswith("[somtoday:")


def test_one_all_day_event_is_created_per_published_holiday():
    holidays = [
        {
            "links": [{"id": "autumn-2026"}],
            "naam": "Herfstvakantie",
            "beginDatum": "2026-09-12",
            "eindDatum": "2026-09-18",
        }
    ]
    desired = desired_holiday_events(
        holidays,
        {
            "holiday_calendar": "calendar.family",
            "holiday_title": "Seth · {holiday}",
        },
        "a",
        START,
        END,
    )

    assert len(desired) == 1
    event = desired[("calendar.family", "a:holiday:autumn-2026")]
    assert event["summary"] == "Seth · Herfstvakantie"
    assert event["dtstart"] == date(2026, 9, 12)
    assert event["dtend"] == date(2026, 9, 19)


@pytest.mark.asyncio
async def test_holiday_uses_all_day_action_fields(monkeypatch):
    calendar = FakeCalendar()
    sync = synchronizer(calendar, monkeypatch, provider="google")
    targets = {"calendar.family": {scope_marker("test", "a:holiday")}}
    desired = desired_holiday_events(
        [{
            "links": [{"id": "summer"}],
            "naam": "Zomervakantie",
            "beginDatum": "2026-09-10",
            "eindDatum": "2026-09-11",
        }],
        {"holiday_calendar": "calendar.family"},
        "a",
        START,
        END,
    )

    await sync.run(desired, targets, START, END, False)

    data = sync.test_services.calls[0][2]
    assert data["start_date"] == date(2026, 9, 10)
    assert data["end_date"] == date(2026, 9, 12)
    assert "start_date_time" not in data


@pytest.mark.asyncio
async def test_multiple_creates_use_one_initial_and_one_verification_read(monkeypatch):
    calendar = FakeCalendar()
    sync = synchronizer(calendar, monkeypatch)
    targets = {"calendar.family": {scope_marker("test", "a:lesson")}}
    desired = desired_events(
        [lesson("1", 9), lesson("2", 11), lesson("3", 13)],
        {"lesson_calendar": "calendar.family"},
        "a",
        START,
        END,
    )

    await sync.run(desired, targets, START, END, False)

    assert calendar.creates == 3
    assert calendar.reads == 2


@pytest.mark.asyncio
async def test_definitive_create_failure_clears_pending_for_retry(monkeypatch):
    calendar = FakeCalendar()
    store = MemoryStore()
    sync = synchronizer(calendar, monkeypatch, store, provider="google")
    targets = {"calendar.family": {scope_marker("test", "a:lesson")}}
    desired = desired_events(
        [lesson()], {"lesson_calendar": "calendar.family"}, "a", START, END
    )

    async def rejected_create(**values):
        from aiohttp import ClientResponseError
        raise HomeAssistantError("Forbidden") from ClientResponseError(None, (), status=403)

    calendar.async_create_event = rejected_create
    with pytest.raises(HomeAssistantError):
        await sync.run(desired, targets, START, END, False)

    assert store.data == {}
