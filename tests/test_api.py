from datetime import date
import asyncio
from unittest.mock import AsyncMock

import pytest

from custom_components.somtoday.api import SomtodayClient, SomtodayApiError


@pytest.mark.asyncio
async def test_parallel_requests_refresh_rotating_token_only_once():
    client = SomtodayClient(None, {"expires_at": 0})
    async def refresh():
        await asyncio.sleep(0)
        client.token = {"expires_at": 9999999999}
    client.refresh = AsyncMock(side_effect=refresh)
    await asyncio.gather(*(client.ensure_token() for _ in range(6)))
    client.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_optional_endpoint_permission_denied_does_not_request_reauth():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from aiohttp import ClientResponseError
    from custom_components.somtoday.api import SomtodayAuthenticationError
    response = SimpleNamespace(raise_for_status=Mock(side_effect=ClientResponseError(None, (), status=403)))
    client = SomtodayClient(SimpleNamespace(get=AsyncMock(return_value=response)),
                            {"access_token": "test", "expires_at": 9999999999})
    with pytest.raises(SomtodayApiError) as caught:
        await client._get("/optional")
    assert not isinstance(caught.value, SomtodayAuthenticationError)


@pytest.mark.asyncio
async def test_assignment_authentication_failure_is_not_optional():
    from custom_components.somtoday.api import SomtodayAuthenticationError
    client = SomtodayClient(None, {"expires_at": 9999999999})
    client._get_all = AsyncMock(side_effect=[[], SomtodayAuthenticationError("expired"), []])
    with pytest.raises(SomtodayAuthenticationError):
        await client.assessments("student", date(2026, 9, 28))


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


@pytest.mark.asyncio
async def test_source_reports_include_successful_zero_counts():
    client = SomtodayClient(None, {"access_token": "token", "expires_at": 9999999999})
    client._get_all = AsyncMock(return_value=[])
    await client.assessments("student", date(2026, 9, 15))
    assert client.assignment_reports["student"] == [
        {"source": kind, "status": "ok", "count": 0}
        for kind in ("appointment", "day", "week")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", [None, "rotated"])
async def test_refresh_retains_optional_metadata_and_saves_rotation(replacement):
    from unittest.mock import Mock
    client = SomtodayClient(None, {
        "access_token": "old", "refresh_token": "original",
        "somtoday_api_url": "https://school.example", "expires_at": 0,
    })
    refreshed = {"access_token": "new", "expires_at": 9999999999}
    if replacement is not None:
        refreshed["refresh_token"] = replacement
    client._token_request = AsyncMock(return_value=refreshed)
    client.token_updated = Mock()

    await client.refresh()

    assert client.token["refresh_token"] == (replacement or "original")
    assert client.token["somtoday_api_url"] == "https://school.example"
    assert client.token["access_token"] == "new"
    client.token_updated.assert_called_once_with(client.token)
    assert client.token_updated.call_args.args[0] is not client.token


@pytest.mark.asyncio
async def test_early_unauthorized_refreshes_and_retries_once():
    from custom_components.somtoday.api import SomtodayAuthenticationError
    client = SomtodayClient(None, {"access_token": "old", "expires_at": 9999999999})
    client._get_once = AsyncMock(side_effect=[SomtodayAuthenticationError("expired"), {"items": []}])
    async def refresh():
        client.token = {"access_token": "new", "expires_at": 9999999999}
    client.refresh = AsyncMock(side_effect=refresh)

    assert await client._get("/test") == {"items": []}
    client.refresh.assert_awaited_once()
    assert client._get_once.await_count == 2


@pytest.mark.asyncio
async def test_repeated_unauthorized_still_requests_reauth_without_loop():
    from custom_components.somtoday.api import SomtodayAuthenticationError
    client = SomtodayClient(None, {"access_token": "old", "expires_at": 9999999999})
    client._get_once = AsyncMock(side_effect=SomtodayAuthenticationError("rejected"))
    client.refresh = AsyncMock()
    with pytest.raises(SomtodayAuthenticationError):
        await client._get("/test")
    client.refresh.assert_awaited_once()
    assert client._get_once.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_unauthorized_requests_share_one_rotation():
    from custom_components.somtoday.api import SomtodayAuthenticationError
    client = SomtodayClient(None, {"access_token": "old", "expires_at": 9999999999})
    arrivals = 0
    all_arrived = asyncio.Event()
    async def request(*args):
        nonlocal arrivals
        if client.token["access_token"] == "old":
            arrivals += 1
            if arrivals == 6:
                all_arrived.set()
            await all_arrived.wait()
            raise SomtodayAuthenticationError("expired")
        return {"items": []}
    async def refresh():
        await asyncio.sleep(0)
        client.token = {"access_token": "new", "expires_at": 9999999999}
    client._get_once = request
    client.refresh = AsyncMock(side_effect=refresh)
    assert await asyncio.gather(*(client._get("/test") for _ in range(6))) == [{"items": []}] * 6
    client.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_token_payload_is_transient_and_retains_credential():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from custom_components.somtoday.api import SomtodayAuthenticationError
    response = SimpleNamespace(raise_for_status=Mock(), json=AsyncMock(return_value={}))
    original = {"access_token": "old", "refresh_token": "original", "expires_at": 0}
    client = SomtodayClient(SimpleNamespace(post=AsyncMock(return_value=response)), dict(original))
    with pytest.raises(SomtodayApiError) as caught:
        await client.refresh()
    assert not isinstance(caught.value, SomtodayAuthenticationError)
    assert client.token == original
