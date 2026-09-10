"""Somtoday integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SomtodayClient
from .const import CONF_TOKEN, DOMAIN
from .coordinator import SomtodayCoordinator
from .export import item_id

PLATFORMS = [Platform.CALENDAR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Somtoday from a config entry."""
    client = SomtodayClient(async_get_clientsession(hass), dict(entry.data[CONF_TOKEN]))
    coordinator = SomtodayCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    if "legacy_student_id" not in entry.data and coordinator.data.get("students"):
        hass.config_entries.async_update_entry(entry, data={
            **entry.data, "legacy_student_id": item_id(coordinator.data["students"][0]),
        })
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    return True


async def async_options_updated(hass, entry):
    """Apply options without restarting Home Assistant."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
