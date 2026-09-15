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


@pytest.mark.asyncio
async def test_homework_write_body_and_redacted_failure():
    from unittest.mock import Mock
    from types import SimpleNamespace
    response = Mock()
    client = SomtodayClient(SimpleNamespace(put=AsyncMock(return_value=response)),
                            {"access_token": "secret", "expires_at": 9999999999})
    await client.set_homework_done("123", "456", True)
    body = client._session.put.call_args.kwargs["json"]
    assert body["leerling"]["links"][0]["id"] == 123
    assert body["swiToekenningId"] == 456
    assert body["gemaakt"] is True
    assert client._session.put.call_args.args[0].endswith("/rest/v1/swigemaakt/cou")
    client._session.put.side_effect = TimeoutError("private")
    with pytest.raises(SomtodayApiError, match="Homework completion write failed"):
        await client.set_homework_done("123", "456", False)
    with pytest.raises(SomtodayApiError, match="Unsupported homework identifiers"):
        await client.set_homework_done("not-an-id", "456", True)


@pytest.mark.asyncio
async def test_assignment_failures_identify_each_source_without_partial_snapshot():
    from aiohttp import ClientResponseError
    from custom_components.somtoday.api import SomtodayAssignmentsError

    forbidden = SomtodayApiError("private response")
    forbidden.__cause__ = ClientResponseError(None, (), status=403, message="private")
    timeout = SomtodayApiError("private timeout")
    timeout.__cause__ = TimeoutError("secret URL")
    client = SomtodayClient(None, {"access_token": "secret", "expires_at": 9999999999})
    client._get_all = AsyncMock(side_effect=[[{"private": "homework"}], forbidden, timeout])
    with pytest.raises(SomtodayAssignmentsError) as caught:
        await client.assessments("private-student", date(2026, 9, 15))
    assert caught.value.failures == [
        {"source": "day", "category": "http_error", "http_status": 403},
        {"source": "week", "category": "timeout"},
    ]
    assert client._get_all.await_count == 3
    assert "private" not in str(caught.value)


def test_assignment_failure_does_not_leak_exception_messages():
    from custom_components.somtoday.api import assignment_failure
    assert assignment_failure("day", SomtodayApiError("token=secret")) == {
        "source": "day", "category": "invalid_response",
    }


@pytest.mark.asyncio
async def test_all_assignment_sources_empty_is_valid():
    client = SomtodayClient(None, {"access_token": "token", "expires_at": 9999999999})
    client._get_all = AsyncMock(return_value=[])
    assert await client.assessments("student", date(2026, 9, 15)) == []
    assert client._get_all.await_count == 3


@pytest.mark.asyncio
async def test_empty_sources_do_not_discard_other_assignments():
    client = SomtodayClient(None, {"access_token": "token", "expires_at": 9999999999})
    client._get_all = AsyncMock(side_effect=[[], [{"id": "homework"}], []])
    assert await client.assessments("student", date(2026, 9, 15)) == [
        {"id": "homework", "_somtoday_assignment_kind": "day"}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("content_range", ["items */0", "items 0-0/0", "items=0--1/0", ""])
async def test_explicit_empty_http_page_is_valid(content_range):
    from types import SimpleNamespace
    from unittest.mock import Mock
    response = SimpleNamespace(
        raise_for_status=Mock(), json=AsyncMock(return_value={"items": []}),
        headers={"Content-Range": content_range},
    )
    client = SomtodayClient(SimpleNamespace(get=AsyncMock(return_value=response)),
                            {"access_token": "token", "expires_at": 9999999999})
    assert await client._get_all("/rest/v1/assignments") == []
    client._session.get.assert_awaited_once()
