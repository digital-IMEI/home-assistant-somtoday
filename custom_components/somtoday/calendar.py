"""Calendar platform for Somtoday appointments."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SomtodayCoordinator
from .models import parse_datetime
from .export import item_id


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SomtodayCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for student in coordinator.data.get("students", []):
        legacy = item_id(student) == entry.data.get("legacy_student_id")
        entities.extend(
            (
                SomtodayCalendar(coordinator, entry, student, legacy),
                SomtodaySchoolDayCalendar(coordinator, entry, student, legacy),
            )
        )
    async_add_entities(entities)


class SomtodayCalendar(CoordinatorEntity[SomtodayCoordinator], CalendarEntity):
    """Calendar containing active Somtoday schedule appointments."""

    _attr_has_entity_name = True
    _attr_name = "Rooster"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: SomtodayCoordinator, entry: ConfigEntry, student, legacy=False) -> None:
        super().__init__(coordinator)
        self.student = item_id(student)
        self._attr_name = f"{student.get('roepnaam') or self.student} · Rooster"
        self._attr_unique_id = f"{entry.entry_id}_schedule" if legacy else f"{entry.entry_id}_{self.student}_schedule"

    @property
    def event(self) -> CalendarEvent | None:
        now = datetime.now().astimezone()
        events = self._events(now, None)
        return next((event for event in events if event.end > now), None)

    async def async_get_events(self, hass, start_date, end_date):
        return self._events(start_date, end_date)

    def _events(self, start: datetime, end: datetime | None) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for item in self.coordinator.data.get("appointments_by_student", {}).get(self.student, []):
            if str(item.get("afspraakStatus", "ACTIEF")).upper() != "ACTIEF":
                continue
            try:
                event_start = parse_datetime(item["beginDatumTijd"])
                event_end = parse_datetime(item["eindDatumTijd"])
            except (KeyError, TypeError, ValueError):
                continue
            if event_end < start or (end is not None and event_start > end):
                continue
            additional = item.get("additionalObjects") or {}
            subject = (additional.get("vak") or {}).get("naam")
            summary = subject or item.get("titel") or "Somtoday"
            events.append(
                CalendarEvent(
                    start=event_start,
                    end=event_end,
                    summary=str(summary),
                    location=item.get("locatie"),
                    description=item.get("omschrijving"),
                    uid=str((item.get("links") or [{}])[0].get("id", "")) or None,
                )
            )
        return sorted(events, key=lambda event: event.start)


class SomtodaySchoolDayCalendar(
    CoordinatorEntity[SomtodayCoordinator], CalendarEntity
):
    """Calendar containing one event spanning every calculated school day."""

    _attr_has_entity_name = True
    _attr_name = "Schooldag"
    _attr_icon = "mdi:school-clock"

    def __init__(
        self,
        coordinator: SomtodayCoordinator,
        entry: ConfigEntry,
        student,
        legacy=False,
    ) -> None:
        super().__init__(coordinator)
        self.student = item_id(student)
        self._attr_name = f"{student.get('roepnaam') or self.student} · Schooldag"
        self._attr_unique_id = (
            f"{entry.entry_id}_school_day"
            if legacy
            else f"{entry.entry_id}_{self.student}_school_day"
        )

    @property
    def event(self) -> CalendarEvent | None:
        now = datetime.now().astimezone()
        events = self._events(now, None)
        return next((event for event in events if event.end > now), None)

    async def async_get_events(self, hass, start_date, end_date):
        return self._events(start_date, end_date)

    def _events(self, start: datetime, end: datetime | None) -> list[CalendarEvent]:
        events = []
        school_days = self.coordinator.data.get("school_days_by_student", {}).get(
            self.student, {}
        )
        for day, (event_start, event_end) in school_days.items():
            if event_end < start or (end is not None and event_start > end):
                continue
            events.append(
                CalendarEvent(
                    start=event_start,
                    end=event_end,
                    summary="Schooldag",
                    description="Somtoday school day",
                    uid=f"{self.student}:school-day:{day}",
                )
            )
        return sorted(events, key=lambda event: event.start)
