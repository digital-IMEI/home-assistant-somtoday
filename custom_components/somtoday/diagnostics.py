"""Allowlisted diagnostics: no tokens, account IDs, names, schedules or calendar titles."""

from homeassistant.const import __version__ as HA_VERSION

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = coordinator.data if coordinator and coordinator.data else {}
    sync = data.get("sync_status", {})
    routes = entry.options.get("exports", {})
    destinations = []
    for index, route in enumerate(routes.values(), 1):
        if not isinstance(route, dict):
            destinations.append({"route_index": index, "invalid_configuration": True})
            continue
        target = route.get("homework_list")
        state = hass.states.get(target) if target else None
        destinations.append({
            "route_index": index,
            "homework_enabled": bool(target),
            "write_back_enabled": bool(route.get("homework_bidirectional", False)),
            "target_exists": state is not None,
            "target_available": state is not None and state.state not in {"unavailable", "unknown"},
            "target_supported_features": state.attributes.get("supported_features", 0) if state else 0,
        })
    return {
        "home_assistant_version": HA_VERSION,
        "homework_destinations": destinations,
        "assignment_checked_at": getattr(coordinator, "_assignment_checked_at", None),
        "assignment_source_results": [
            {key: value for key, value in report.items()
             if (key == "source" and value in {"appointment", "day", "week"})
             or (key == "status" and value in {"ok", "failed"})
             or (key in {"count", "http_status"} and isinstance(value, int))
             or (key == "category" and value in {"invalid_response", "http_error", "timeout", "connection_error", "authentication_error"})}
            for reports in getattr(getattr(coordinator, "client", None), "assignment_reports", {}).values()
            for report in reports
        ],
        "homework_sync_mode": data.get("homework_sync_status", {}).get("mode"),
        "export_ready": bool(getattr(coordinator, "export_ready", False)),
        "version": "0.9.0-beta.4",
        "assignment_source_errors": [
            {key: value for key, value in failure.items()
             if (key == "source" and value in {"appointment", "day", "week", "authentication"})
             or (key == "category" and value in {"invalid_response", "http_error", "timeout", "connection_error", "authentication_error"})
             or (key == "http_status" and isinstance(value, int))}
            for failure in getattr(coordinator, "_assignment_source_errors", [])
        ],
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
