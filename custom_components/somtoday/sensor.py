"""Sensor platform for Somtoday."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import SomtodayCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SomtodayCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SomtodaySchoolDaySensor(coordinator, entry)])


class SomtodaySchoolDaySensor(CoordinatorEntity[SomtodayCoordinator], SensorEntity):
    """Show today's calculated school-day interval."""

    _attr_has_entity_name = True
    _attr_name = "Schooldag"
    _attr_icon = "mdi:school-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SomtodayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_school_day"

    @property
    def native_value(self):
        bounds = self.coordinator.data.get("school_days", {}).get(
            dt_util.now().date().isoformat()
        )
        return bounds[0] if bounds else None

    @property
    def extra_state_attributes(self):
        bounds = self.coordinator.data.get("school_days", {}).get(
            dt_util.now().date().isoformat()
        )
        if not bounds:
            return {"has_school": False}
        return {"has_school": True, "start": bounds[0].isoformat(), "end": bounds[1].isoformat()}
