from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.somtoday.coordinator import SomtodayCoordinator


@pytest.mark.asyncio
async def test_startup_defers_export_but_preserves_source(monkeypatch):
    import custom_components.somtoday.coordinator as module

    coordinator = object.__new__(SomtodayCoordinator)
    coordinator.entry = SimpleNamespace(
        entry_id="test", data={"token": {}},
        options={"exports": {"a": {"day_calendar": "calendar.family"}}},
    )
    coordinator.hass = SimpleNamespace()
    coordinator.client = SimpleNamespace(
        token={}, students=AsyncMock(return_value=[{"links": [{"id": "a"}]}]),
        appointments=AsyncMock(return_value=[]), holidays=AsyncMock(return_value=[]),
    )
    coordinator._holidays = {}
    coordinator._holidays_checked = None
    coordinator.export_ready = False
    coordinator.calendar_sync = SimpleNamespace(run=AsyncMock(return_value={"mode": "enabled"}))
    create_issue = Mock()
    monkeypatch.setattr(module.ir, "async_create_issue", create_issue)
    monkeypatch.setattr(module.ir, "async_delete_issue", Mock())

    result = await coordinator._async_update_data()
    assert result["sync_status"]["mode"] == "starting"
    assert len(result["students"]) == 1
    coordinator.calendar_sync.run.assert_not_called()
    create_issue.assert_not_called()

    coordinator.export_ready = True
    result = await coordinator._async_update_data()
    assert result["sync_status"]["mode"] == "enabled"
    assert coordinator.calendar_sync.run.call_args.args[-1] is False

    coordinator.calendar_sync.run.side_effect = ValueError("Target unavailable")
    result = await coordinator._async_update_data()
    assert result["sync_status"]["mode"] == "error"
    create_issue.assert_called_once()
