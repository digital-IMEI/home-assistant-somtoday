"""Sensor platform for Somtoday."""

from __future__ import annotations

from datetime import datetime, time

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .export import item_id
from .coordinator import SomtodayCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SomtodayCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [SomtodaySyncSensor(coordinator, entry)]
    entities.extend(
        SomtodayNextAssessmentSensor(coordinator, entry, student)
        for student in coordinator.data.get("students", [])
    )
    async_add_entities(entities)


class SomtodaySyncSensor(CoordinatorEntity[SomtodayCoordinator], SensorEntity):
    """Expose preview counts and synchronization failures without private data."""

    _attr_has_entity_name = True
    _attr_name = "Calendar sync"
    _attr_icon = "mdi:calendar-sync"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar_sync"

    @property
    def native_value(self):
        return self.coordinator.data.get("sync_status", {}).get("mode", "disabled")

    @property
    def extra_state_attributes(self):
        return self.coordinator.data.get("sync_status", {})


class SomtodayNextAssessmentSensor(
    CoordinatorEntity[SomtodayCoordinator], SensorEntity
):
    """Expose the next dated assessment and count undated test assignments."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clipboard-text-clock-outline"

    def __init__(self, coordinator, entry, student):
        super().__init__(coordinator)
        self.student = item_id(student)
        name = student.get("roepnaam") or self.student
        self._attr_name = f"{name} · Volgende toets"
        self._attr_unique_id = f"{entry.entry_id}_{self.student}_next_assessment"

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.data.get("assessments_by_student", {}).get(
                self.student
            )
            is not None
        )

    def _dated(self):
        now = dt_util.now()
        return [
            value
            for value in self.coordinator.data.get(
                "assessments_by_student", {}
            ).get(self.student, []) or []
            if value.get("start") is not None
            and value.get("end") is not None
            and (
                value["end"] > now
                if isinstance(value["end"], datetime)
                else value["end"] > now.date()
            )
        ]

    @property
    def native_value(self):
        values = self._dated()
        if not values:
            return None
        start = values[0]["start"]
        if isinstance(start, datetime):
            return start
        return datetime.combine(start, time.min, tzinfo=dt_util.DEFAULT_TIME_ZONE)

    @property
    def extra_state_attributes(self):
        all_values = self.coordinator.data.get("assessments_by_student", {}).get(
            self.student, []
        ) or []
        dated = self._dated()
        attributes = {
            "undated_count": sum(
                value.get("start") is None for value in all_values
            )
        }
        if dated:
            value = dated[0]
            start = value["start"]
            start_day = start.date() if isinstance(start, datetime) else start
            attributes.update(
                subject=value["subject"],
                assessment_type=value["type_label"],
                topic=value["topic"],
                days_until=(start_day - dt_util.now().date()).days,
                all_day=value["all_day"],
                made=value["made"],
            )
        return attributes
