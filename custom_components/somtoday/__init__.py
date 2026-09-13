"""Somtoday integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SomtodayClient
from .const import CONF_TOKEN, DOMAIN
from .coordinator import SomtodayCoordinator
from .export import item_id
from .sync import target_entity

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]
STARTUP_CALENDAR_CHECK_SECONDS = 5
STARTUP_CALENDAR_MAX_WAIT_SECONDS = 120


def _configured_calendar_targets(entry: ConfigEntry) -> set[str]:
    """Return all configured destination calendar entity IDs."""
    return {
        target
        for route in entry.options.get("exports", {}).values()
        for field in ("day_calendar", "lesson_calendar", "holiday_calendar")
        if (target := route.get(field))
    }


def _remove_legacy_school_day_sensors(
    hass: HomeAssistant, entry: ConfigEntry, students: list[dict]
) -> None:
    """Remove timestamp sensors replaced by school-day calendar entities."""
    registry = er.async_get(hass)
    unique_ids = {f"{entry.entry_id}_{item_id(student)}_school_day" for student in students}
    unique_ids.add(f"{entry.entry_id}_school_day")
    for unique_id in unique_ids:
        if entity_id := registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, unique_id
        ):
            registry.async_remove(entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Somtoday from a config entry."""
    client = SomtodayClient(async_get_clientsession(hass), dict(entry.data[CONF_TOKEN]))
    coordinator = SomtodayCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    if "legacy_student_id" not in entry.data and coordinator.data.get("students"):
        hass.config_entries.async_update_entry(entry, data={
            **entry.data, "legacy_student_id": item_id(coordinator.data["students"][0]),
        })
    _remove_legacy_school_day_sensors(
        hass, entry, coordinator.data.get("students", [])
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))

    startup_wait = 0

    async def enable_export(_now):
        nonlocal startup_wait
        startup_wait += STARTUP_CALENDAR_CHECK_SECONDS
        try:
            for target in _configured_calendar_targets(entry):
                target_entity(hass, target)
        except ValueError:
            if startup_wait < STARTUP_CALENDAR_MAX_WAIT_SECONDS:
                entry.async_on_unload(
                    async_call_later(
                        hass, STARTUP_CALENDAR_CHECK_SECONDS, enable_export
                    )
                )
                return
        coordinator.export_ready = True
        await coordinator.async_request_refresh()

    @callback
    def schedule_export(_hass):
        entry.async_on_unload(
            async_call_later(hass, STARTUP_CALENDAR_CHECK_SECONDS, enable_export)
        )

    if hass.state is CoreState.running:
        # An options reload happens after calendar platforms are already ready.
        # Do not apply the full-HA-start grace period to a normal reconfiguration.
        coordinator.export_ready = True
        await coordinator.async_request_refresh()
    else:
        entry.async_on_unload(async_at_started(hass, schedule_export))
    return True


async def async_options_updated(hass, entry):
    """Reload only for actual option changes, not rotated token data."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if (
        coordinator is not None
        and coordinator.options_snapshot == dict(entry.options)
    ):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
