"""Diagnostic button platform for Somtoday."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    async_add_entities([SomtodayRetryCalendarSyncButton(coordinator, entry)])


class SomtodayRetryCalendarSyncButton(
    CoordinatorEntity[SomtodayCoordinator], ButtonEntity
):
    """Clear uncertain writes and request a fresh reconciliation."""

    _attr_has_entity_name = True
    _attr_name = "Retry calendar sync"
    _attr_icon = "mdi:calendar-refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar_sync_retry"

    async def async_press(self) -> None:
        await self.coordinator.calendar_sync.async_reset_pending()
        await self.coordinator.async_request_refresh()
