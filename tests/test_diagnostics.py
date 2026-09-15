import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.somtoday.diagnostics import async_get_config_entry_diagnostics


@pytest.mark.asyncio
async def test_diagnostics_contains_support_context_without_private_fields():
    coordinator = SimpleNamespace(
        data={"homework_sync_status": {"mode": "waiting", "reasons": {"homework_source_unavailable": 1}}},
        last_update_success=True, export_ready=True,
        _assignment_checked_at="2026-09-15T12:00:00+00:00",
        _assignment_source_errors=[{"source": "day", "category": "http_error", "http_status": 403}],
        client=SimpleNamespace(assignment_reports={"PRIVATE_STUDENT": [
            {"source": "day", "status": "failed", "category": "http_error", "http_status": 403, "secret": "PRIVATE_TOKEN"},
            {"source": "week", "status": "ok", "count": 0},
        ]}),
    )
    entry = SimpleNamespace(entry_id="entry", options={"exports": {"PRIVATE_STUDENT": {
        "homework_list": "todo.PRIVATE_LIST", "homework_bidirectional": True,
        "homework_title": "PRIVATE_TITLE",
    }}})
    hass = SimpleNamespace(data={"somtoday": {"entry": coordinator}},
                           states=SimpleNamespace(get=Mock(return_value=SimpleNamespace(
                               state="0", attributes={"supported_features": 31}))))
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert "PRIVATE" not in json.dumps(result)
    assert result["homework_destinations"][0]["target_available"] is True
    assert result["assignment_source_results"][1]["count"] == 0
    assert result["assignment_source_errors"][0]["http_status"] == 403
    assert result["home_assistant_version"]
