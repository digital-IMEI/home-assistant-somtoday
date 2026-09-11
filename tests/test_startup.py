from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.somtoday import async_options_updated
from custom_components.somtoday.const import DOMAIN
from custom_components.somtoday.coordinator import SomtodayCoordinator


@pytest.mark.asyncio
async def test_token_update_does_not_reload_but_options_change_does():
    reload_entry = AsyncMock()
    entry = SimpleNamespace(entry_id="test", options={"days_ahead": 14})
    coordinator = SimpleNamespace(options_snapshot={"days_ahead": 14})
    hass = SimpleNamespace(
        data={DOMAIN: {entry.entry_id: coordinator}},
        config_entries=SimpleNamespace(async_reload=reload_entry),
    )

    await async_options_updated(hass, entry)
    reload_entry.assert_not_awaited()

    entry.options = {"days_ahead": 1}
    await async_options_updated(hass, entry)
    reload_entry.assert_awaited_once_with(entry.entry_id)


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
