from unittest.mock import AsyncMock

import pytest

from custom_components.somtoday.api import SomtodayClient, SomtodayApiError


@pytest.mark.asyncio
async def test_pagination_collects_all_and_rejects_repeats():
    client = SomtodayClient(None)
    page = [{"links": [{"id": str(i)}]} for i in range(100)]
    client._get = AsyncMock(side_effect=[{"items": page, "_has_more": True},
                                        {"items": [{"links": [{"id": "100"}]}], "_has_more": False}])
    assert len(await client._get_all("/rest/v1/afspraken")) == 101
    client._get = AsyncMock(side_effect=[{"items": page}, {"items": page}])
    with pytest.raises(SomtodayApiError): await client._get_all("/rest/v1/afspraken")


@pytest.mark.asyncio
async def test_malformed_snapshot_and_exact_full_last_page():
    client = SomtodayClient(None)
    client._get = AsyncMock(return_value={})
    with pytest.raises(SomtodayApiError): await client._get_all("/rest/v1/afspraken")
    client._get = AsyncMock(return_value={"items": [{"links": [{"id": str(i)}]} for i in range(100)], "_has_more": False})
    assert len(await client._get_all("/rest/v1/afspraken")) == 100
    assert client._get.await_count == 1
