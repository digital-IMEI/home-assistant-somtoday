"""Allowlisted diagnostics: no tokens, account IDs, names, schedules or calendar titles."""

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = coordinator.data if coordinator and coordinator.data else {}
    sync = data.get("sync_status", {})
    return {
        "version": "0.6.3",
        "source_update_success": coordinator.last_update_success if coordinator else False,
        "student_count": len(data.get("students", [])),
        "days_ahead": entry.options.get("days_ahead", 14),
        "scan_interval": entry.options.get("scan_interval", 15),
        "sync_counts": {key: sync[key] for key in ("create", "replace", "delete", "unchanged", "pending", "awaiting_visibility") if isinstance(sync.get(key), int)},
        "holiday_available_count": sum(value is not None for value in data.get("holidays_by_student", {}).values()),
    }
