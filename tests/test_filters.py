from datetime import datetime, date
from unittest.mock import AsyncMock

import pytest

from custom_components.somtoday.models import school_day_appointments, school_day_bounds
from custom_components.somtoday.export import desired_events
from custom_components.somtoday.homework import selected_homework
from test_homework import make_sync, assignment
from test_options import make_flow


def appointments():
    return [{"links": [{"id": str(i)}], "titel": title,
             "additionalObjects": {"vak": {"naam": subject}},
             "beginDatumTijd": f"2026-09-22T{start}:00+02:00",
             "eindDatumTijd": f"2026-09-22T{end}:00+02:00"}
            for i, (title, subject, start, end) in enumerate([
                ("optional", "Flexlessen", "08:10", "08:11"),
                ("Math", "Wiskunde", "09:00", "10:00")])]


def test_day_filter_leaves_individual_lessons_and_source_intact():
    items = appointments()
    options = {"day_excluded_names": "  FLEXLESSEN \n\n", "day_calendar": "calendar.day", "lesson_calendar": "calendar.lessons"}
    start = datetime.fromisoformat("2026-09-22T00:00:00+02:00")
    end = datetime.fromisoformat("2026-09-23T00:00:00+02:00")
    events = desired_events(items, options, "a", start, end)
    assert len(events) == 3
    assert events[("calendar.day", "a:day:2026-09-22")]["dtstart"].hour == 9
    assert len(items) == 2
    assert school_day_bounds(school_day_appointments(items, options))["2026-09-22"][0].hour == 9
    assert school_day_appointments(items, {}) == items
    assert school_day_appointments(items, {"day_excluded_names": "Flex"}) == items
    assert len(school_day_appointments(items, {"day_excluded_names": "flex", "day_exclusion_match": "contains"})) == 1
    options["day_excluded_names"] = "optional\nMath"
    assert len(desired_events(items, options, "a", start, end)) == 2


@pytest.mark.parametrize("kind", ["appointment", "day", "week"])
@pytest.mark.asyncio
async def test_homework_type_selection_blocks_sync_and_writeback(kind):
    sync = make_sync()
    source = [assignment(source=kind)]
    sync.entry.options["exports"]["1"][f"homework_include_{kind}"] = False
    sync.call.return_value = {"todo.school": {"items": []}}
    sync.sync_item = AsyncMock()
    result = await sync.run([{"links": [{"id": "1"}]}], {"1": source}, date(2026, 9, 14), date(2026, 9, 20))
    assert result["homework_found"] == 0
    sync.sync_item.assert_not_awaited()
    sync.client.set_homework_done.assert_not_awaited()
    assert selected_homework(source, {}) == source
    sync.entry.options["exports"]["1"][f"homework_include_{kind}"] = True
    await sync.run([{"links": [{"id": "1"}]}], {"1": source}, date(2026, 9, 14), date(2026, 9, 20))
    sync.sync_item.assert_awaited_once()


@pytest.mark.asyncio
async def test_filter_options_save_clear_and_preserve_other_child():
    other = {"day_excluded_names": "Other", "homework_include_week": False}
    flow, _ = make_flow({"exports": {"a": {"day_excluded_names": "Old"}, "b": other}})
    form = await flow.async_step_init({"student_id": "a"})
    dest = await flow.async_step_settings(form["data_schema"]({}))
    result = await flow.async_step_destinations(dest["data_schema"]({"school_days": {
        "day_excluded_names": "Flexlessen", "day_exclusion_match": "contains"}}))
    assert result["data"]["exports"]["a"]["day_excluded_names"] == "Flexlessen"
    assert result["data"]["exports"]["b"] == other
    reopened, _ = make_flow(result["data"])
    form = await reopened.async_step_init({"student_id": "a"})
    dest = await reopened.async_step_settings(form["data_schema"]({}))
    saved = await reopened.async_step_destinations(dest["data_schema"]({}))
    assert saved["data"]["exports"]["a"]["day_excluded_names"] == ""
