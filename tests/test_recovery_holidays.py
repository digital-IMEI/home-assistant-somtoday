from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.somtoday.holidays import holiday_status
from custom_components.somtoday.diagnostics import async_get_config_entry_diagnostics
from custom_components.somtoday.config_flow import SomtodayConfigFlow
from custom_components.somtoday.sync import definitely_rejected


def test_published_holiday_inclusive_boundaries_and_empty_roster_not_inferred():
    items = [{"beginDatum": "2026-10-19T00:00:00+02:00", "eindDatum": "2026-10-23T00:00:00+02:00"}]
    assert holiday_status(items, date(2026, 10, 19))
    assert holiday_status(items, date(2026, 10, 23))
    assert not holiday_status(items, date(2026, 10, 24))
    assert not holiday_status([], date(2026, 10, 19))
    with pytest.raises((ValueError, KeyError)):
        holiday_status([{}], date(2026, 10, 19))


def test_generic_ha_error_is_not_proof_of_rejection():
    assert not definitely_rejected(HomeAssistantError("provider timed out"))


@pytest.mark.asyncio
async def test_diagnostics_excludes_all_personal_and_auth_data():
    coordinator = SimpleNamespace(last_update_success=True, data={
        "students": [{"roepnaam": "PRIVATE_NAME"}],
        "sync_status": {"reason": "PRIVATE_URL", "pending": 1},
        "holidays_by_student": {"PRIVATE_ID": True},
    })
    entry = SimpleNamespace(entry_id="entry", data={"token": "PRIVATE_TOKEN"}, options={"exports": {"PRIVATE_ID": "PRIVATE_CALENDAR"}})
    result = await async_get_config_entry_diagnostics(SimpleNamespace(data={"somtoday": {"entry": coordinator}}), entry)
    assert "PRIVATE" not in str(result)
    assert result["sync_counts"] == {"pending": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("account_matches", [True, False])
async def test_reauth_preserves_entry_and_rejects_different_children(account_matches):
    flow = SomtodayConfigFlow()
    flow.context = {"source": "reauth"}
    flow._organization = {"uuid": "school"}
    flow._state = "state"
    flow._client = SimpleNamespace(exchange_code=AsyncMock(return_value={"access_token": "new"}), students=AsyncMock(return_value=[{"links": [{"id": "a"}]}]))
    flow.async_set_unique_id = AsyncMock()
    entry = SimpleNamespace(unique_id="school:a" if account_matches else "school:b")
    flow._get_reauth_entry = Mock(return_value=entry)
    flow.async_update_reload_and_abort = Mock(return_value={"type": "abort"})
    result = await flow.async_step_authorize({"callback_url": "somtoday://callback?code=test&state=state"})
    if account_matches:
        flow.async_update_reload_and_abort.assert_called_once_with(entry, data_updates={"token": {"access_token": "new"}})
    else:
        assert result["errors"]["base"] == "wrong_account"
        flow.async_update_reload_and_abort.assert_not_called()
