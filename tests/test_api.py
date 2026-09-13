from datetime import date
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


@pytest.mark.asyncio
async def test_assessments_fetches_and_labels_all_assignment_scopes():
    client = SomtodayClient(None, {"access_token": "token", "expires_at": 9999999999})
    client._get_all = AsyncMock(
        side_effect=[
            [{"links": [{"id": "appointment"}]}],
            [{"links": [{"id": "day"}]}],
            [{"links": [{"id": "week"}]}],
        ]
    )

    values = await client.assessments("student", date(2026, 9, 13))

    assert [value["_somtoday_assignment_kind"] for value in values] == [
        "appointment",
        "day",
        "week",
    ]
    assert {call.args[0] for call in client._get_all.await_args_list} == {
        "/rest/v1/studiewijzeritemafspraaktoekenningen",
        "/rest/v1/studiewijzeritemdagtoekenningen",
        "/rest/v1/studiewijzeritemweektoekenningen",
    }
