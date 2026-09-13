"""Event entities for Somtoday assessment changes."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .export import item_id


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            SomtodayAssessmentChangeEvent(coordinator, entry, student)
            for student in coordinator.data.get("students", [])
        ]
    )


def _event_data(value):
    start = value.get("start")
    return {
        "assessment_id": value["id"],
        "subject": value["subject"],
        "assessment_type": value["type_label"],
        "topic": value["topic"],
        "date_known": value["date_known"],
        "start": start.isoformat() if start is not None else None,
    }


def _fingerprint(value):
    return (
        value.get("type"),
        value.get("subject"),
        value.get("topic"),
        value.get("start"),
        value.get("end"),
        value.get("made"),
    )


def _has_aged_out(value) -> bool:
    """Do not report a normal window rollover as a removed test."""
    start = value.get("start")
    if start is None:
        return False
    day = start.date() if hasattr(start, "date") else start
    return day < dt_util.now().date()


class SomtodayAssessmentChangeEvent(CoordinatorEntity, EventEntity):
    """Fire when an explicitly typed test is added, changed or removed."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:clipboard-edit-outline"
    _attr_event_types = ["added", "changed", "removed"]

    def __init__(self, coordinator, entry, student):
        super().__init__(coordinator)
        self.student = item_id(student)
        name = student.get("roepnaam") or self.student
        self._attr_name = f"{name} · Toetswijziging"
        self._attr_unique_id = f"{entry.entry_id}_{self.student}_assessment_change"
        self._known = self._current()

    def _current(self):
        values = self.coordinator.data.get("assessments_by_student", {}).get(
            self.student
        )
        if values is None:
            return None
        return {value["id"]: value for value in values}

    def _emit(self, event_type, value) -> None:
        """Publish every change separately so automations see the whole batch."""
        self._trigger_event(event_type, _event_data(value))
        self.async_write_ha_state()

    @property
    def available(self):
        return super().available and self._current() is not None

    def _handle_coordinator_update(self) -> None:
        current = self._current()
        if current is None:
            super()._handle_coordinator_update()
            return
        previous = self._known
        if previous is not None:
            for identifier in sorted(current.keys() - previous.keys()):
                self._emit("added", current[identifier])
            for identifier in sorted(current.keys() & previous.keys()):
                if _fingerprint(current[identifier]) != _fingerprint(
                    previous[identifier]
                ):
                    self._emit("changed", current[identifier])
            for identifier in sorted(previous.keys() - current.keys()):
                if not _has_aged_out(previous[identifier]):
                    self._emit("removed", previous[identifier])
        self._known = current
        super()._handle_coordinator_update()
