"""Allowlisted diagnostics: no tokens, account IDs, names, schedules or calendar titles."""

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = coordinator.data if coordinator and coordinator.data else {}
    sync = data.get("sync_status", {})
    return {
        "version": "0.9.0-beta.2",
        "homework_sync_counts": {
            key: data.get("homework_sync_status", {}).get(key)
            for key in ("created", "updated", "unchanged", "waiting", "errors", "source_updated", "homework_found")
            if isinstance(data.get("homework_sync_status", {}).get(key), int)
        },
        "homework_sync_reasons": {
            key: value
            for key, value in data.get("homework_sync_status", {}).get("reasons", {}).items()
            if key in {
                "homework_source_unavailable", "task_list_missing", "task_list_unavailable",
                "task_list_unsupported", "task_list_read_failed", "invalid_task_snapshot",
                "task_list_write_failed", "somtoday_write_failed", "task_creation_unconfirmed",
                "task_update_unconfirmed", "somtoday_write_unconfirmed", "duplicate_task_marker",
                "invalid_task_identity", "task_sync_failed", "homework_sync_failed",
            } and isinstance(value, int)
        },
        "homework_source_available_count": sum(
            value is not None
            for value in getattr(coordinator, "_assessment_assignments", {}).values()
        ),
        "source_update_success": coordinator.last_update_success if coordinator else False,
        "student_count": len(data.get("students", [])),
        "days_ahead": entry.options.get("days_ahead", 14),
        "scan_interval": entry.options.get("scan_interval", 15),
        "sync_counts": {key: sync[key] for key in ("create", "replace", "delete", "unchanged", "pending", "awaiting_visibility") if isinstance(sync.get(key), int)},
        "holiday_available_count": sum(value is not None for value in data.get("holidays_by_student", {}).values()),
        "assessment_available_count": sum(
            value is not None
            for value in data.get("assessments_by_student", {}).values()
        ),
        "dated_assessment_count": sum(
            value.get("start") is not None
            for values in data.get("assessments_by_student", {}).values()
            if values is not None
            for value in values
        ),
        "undated_assessment_count": sum(
            value.get("start") is None
            for values in data.get("assessments_by_student", {}).values()
            if values is not None
            for value in values
        ),
    }
