"""Homework sync regression tests without live accounts."""
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("state,source,reason", [
    (None, [], "task_list_missing"),
    (SimpleNamespace(state="unavailable", attributes={}), [], "task_list_unavailable"),
    (SimpleNamespace(state="0", attributes={"supported_features": 0}), [], "task_list_unsupported"),
    (SimpleNamespace(state="0", attributes={"supported_features": 127}), None, "homework_source_unavailable"),
])
async def test_distinct_blocked_sync_reasons(state, source, reason):
    sync = make_sync()
    sync.hass.states.get = lambda _: state
    result = await sync.run([{"links": [{"id": "1"}]}], {"1": source}, date(2026, 9, 14), date(2026, 9, 20))
    assert result["reasons"] == {reason: 1}
    sync.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_failure_is_redacted():
    from custom_components.somtoday.homework import HomeworkOperationError
    sync = make_sync()
    sync.hass.services = SimpleNamespace(async_call=AsyncMock(side_effect=RuntimeError("secret token and pupil")))
    with pytest.raises(HomeworkOperationError, match="task_list_read_failed") as error:
        await HomeworkSync.call(sync, "get_items", "todo.school")
    assert "secret" not in str(error.value)


def test_homework_diagnostic_explains_failed_source_without_stale_success():
    from custom_components.somtoday.sensor import SomtodayHomeworkSyncSensor
    sensor = object.__new__(SomtodayHomeworkSyncSensor)
    sensor.coordinator = SimpleNamespace(last_update_success=False, data={"homework_sync_status": {"mode": "enabled", "created": 10}})
    assert sensor.available
    assert sensor.native_value == "error"
    assert sensor.extra_state_attributes == {"reason": "source_update_failed"}
    sensor.coordinator.last_update_success = True
    assert sensor.native_value == "enabled"

from custom_components.somtoday.homework import (
    HomeworkSync, compatible, completion, marker_for, normalize_homework, task_fields,
)


def assignment(student="1", made=False, source="day"):
    return {
        "links": [{"id": "11"}], "_somtoday_assignment_kind": source,
        "datumTijd": "2026-09-15T09:20:00+02:00",
        "studiewijzerItem": {"huiswerkType": "HUISWERK", "onderwerp": "Chapter 2", "omschrijving": "Exercises"},
        "additionalObjects": {"swigemaaktVinkjes": {"items": [
            {"leerling": {"links": [{"id": student}]}, "gemaakt": made}
        ]}},
    }


def make_sync():
    obj = object.__new__(HomeworkSync)
    obj.entry = SimpleNamespace(entry_id="entry", options={"exports": {"1": {
        "homework_list": "todo.school", "homework_bidirectional": True
    }}})
    state = SimpleNamespace(state="0", attributes={"supported_features": 127})
    obj.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: state))
    obj.client = SimpleNamespace(set_homework_done=AsyncMock())
    obj.store = SimpleNamespace(async_save=AsyncMock(), async_load=AsyncMock(return_value={}))
    obj.records, obj.lock = {}, asyncio.Lock()
    obj.call = AsyncMock()
    return obj


def test_normalization_and_sibling_isolation():
    a = assignment()
    assert completion(a, "1") is False
    assert completion(a, "2") is None
    a["additionalObjects"]["huiswerkgemaakt"] = True
    assert completion(a, "2") is None
    first, last = date(2026, 9, 14), date(2026, 9, 20)
    values = normalize_homework([a, a], "1", first, last)
    assert len(values) == 1 and values[0]["due"] == date(2026, 9, 15)
    a["_somtoday_assignment_kind"] = "week"
    assert normalize_homework([a], "1", first, last)[0]["due"] is None
    a["studiewijzerItem"]["huiswerkType"] = "TOETS"
    assert normalize_homework([a], "1", first, last) == []
    assert marker_for("e", "1", "11") != marker_for("e", "2", "11")


def test_capabilities_and_no_fabricated_dates():
    assert not compatible(SimpleNamespace(state="unavailable", attributes={"supported_features": 127}))
    assert not compatible(SimpleNamespace(state="0", attributes={"supported_features": 5}))
    value = normalize_homework([assignment()], "1", date(2026, 9, 14), date(2026, 9, 20))[0]
    title, fields = task_fields(value, "Child", "{student} · {topic}", "marker", 101)
    assert title == "Child · Chapter 2"
    assert fields.get("due_datetime") is None
    assert "2026-09-15" in fields["description"]


@pytest.mark.asyncio
async def test_uncertain_creation_not_retried_and_read_failure_not_empty():
    sync = make_sync()
    sync.call.side_effect = [{"todo.school": {"items": []}}, TimeoutError(),
                             {"todo.school": {"items": []}}]
    pupils = [{"links": [{"id": "1"}], "roepnaam": "Child"}]
    args = (pupils, {"1": [assignment()]}, date(2026, 9, 14), date(2026, 9, 20))
    assert (await sync.run(*args))["mode"] == "error"
    assert (await sync.run(*args))["mode"] == "waiting"
    assert sum(call.args[0] == "add_item" for call in sync.call.await_args_list) == 1
    sync.call.side_effect = None
    sync.call.return_value = {}
    assert (await sync.run(*args))["mode"] == "error"


@pytest.mark.asyncio
async def test_bidirectional_readback_and_conflicts():
    sync = make_sync()
    pupils = [{"links": [{"id": "1"}], "roepnaam": "Child"}]
    a = assignment()
    marker = marker_for("entry", "1", "11")
    value = normalize_homework([a], "1", date(2026, 9, 14), date(2026, 9, 20))[0]
    title, fields = task_fields(value, "Child", "{student} · {subject} · {topic}", marker, 127)
    item = {"uid": "uid", "summary": title, "description": fields["description"],
            "due": fields["due_date"], "status": "needs_action"}
    sync.call.return_value = {"todo.school": {"items": [item]}}
    args = (pupils, {"1": [a]}, date(2026, 9, 14), date(2026, 9, 20))
    assert (await sync.run(*args))["unchanged"] == 1
    item["status"] = "completed"
    assert (await sync.run(*args))["source_updated"] == 1
    sync.client.set_homework_done.assert_awaited_once_with("1", "11", True)
    assert (await sync.run(*args))["waiting"] == 1
    a["additionalObjects"]["swigemaaktVinkjes"]["items"][0]["gemaakt"] = True
    assert (await sync.run(*args))["unchanged"] == 1
    assert sync.client.set_homework_done.await_count == 1


@pytest.mark.asyncio
async def test_missing_source_and_unrelated_items_untouched():
    sync = make_sync()
    pupils = [{"links": [{"id": "1"}]}]
    args = (pupils, {"1": None}, date(2026, 9, 14), date(2026, 9, 20))
    assert (await sync.run(*args))["waiting"] == 1
    sync.call.assert_not_awaited()
    sync.call.return_value = {"todo.school": {"items": [{"uid": "personal", "summary": "Personal"}]}}
    args = (pupils, {"1": []}, date(2026, 9, 14), date(2026, 9, 20))
    await sync.run(*args)
    assert sync.call.await_count == 1


@pytest.mark.asyncio
async def test_duplicate_marker_blocks_modification():
    sync = make_sync()
    marker = marker_for("entry", "1", "11")
    sync.call.return_value = {"todo.school": {"items": [
        {"uid": uid, "description": marker} for uid in ("a", "b")
    ]}}
    result = await sync.run([{"links": [{"id": "1"}]}], {"1": [assignment()]},
                            date(2026, 9, 14), date(2026, 9, 20))
    assert result["errors"] == 1
    assert sync.call.await_count == 1


def test_equivalent_due_timestamps():
    from custom_components.somtoday.homework import same_due
    assert same_due("2026-09-15T07:20:00Z", "2026-09-15T09:20:00+02:00")
    assert not same_due("2026-09-15", "2026-09-15T00:00:00+02:00")


@pytest.mark.asyncio
async def test_pending_intent_survives_restart():
    sync = make_sync()
    sync.call.side_effect = [{"todo.school": {"items": []}}, TimeoutError()]
    pupils = [{"links": [{"id": "1"}]}]
    args = (pupils, {"1": [assignment()]}, date(2026, 9, 14), date(2026, 9, 20))
    await sync.run(*args)
    restarted = make_sync()
    restarted.records = None
    restarted.store.async_load.return_value = deepcopy(sync.records)
    restarted.call.return_value = {"todo.school": {"items": []}}
    assert (await restarted.run(*args))["waiting"] == 1
    assert restarted.call.await_count == 1


@pytest.mark.asyncio
async def test_source_completion_changes_update_existing_task():
    sync = make_sync()
    marker = marker_for("entry", "1", "11")
    item = {"uid": "owned", "summary": "Old name", "description": marker,
            "status": "needs_action"}
    sync.call.return_value = {"todo.school": {"items": [item]}}
    result = await sync.run([{"links": [{"id": "1"}], "roepnaam": "Child"}],
                            {"1": [assignment(made=True)]}, date(2026, 9, 14), date(2026, 9, 20))
    assert result["updated"] == 1
    assert sync.call.call_args.args == ("update_item", "todo.school")
    assert sync.call.call_args.kwargs["item"] == "owned"
    assert sync.call.call_args.kwargs["status"] == "completed"
    sync.client.set_homework_done.assert_not_awaited()
