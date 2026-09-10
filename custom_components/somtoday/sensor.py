"""Sensor platform for Somtoday."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SomtodayCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SomtodayCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SomtodaySyncSensor(coordinator, entry)])


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
