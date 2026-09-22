from datetime import date, datetime
from types import SimpleNamespace

import pytest

from custom_components.somtoday.absences import (
    absence_counts,
    label_counts,
    measure_counts,
    normalize_absences,
    normalize_measures,
    school_year_start,
)
from custom_components.somtoday.sensor import (
    SomtodayAbsenceSensor,
    SomtodayMeasureSensor,
)
from custom_components.somtoday.diagnostics import async_get_config_entry_diagnostics
from custom_components.somtoday.config_flow import SomtodayOptionsFlow

SINCE = date(2026, 8, 1)
PUPIL = "pupil-1"


def _report(identifier, start, reason, authorised, remark="", handled=True, owner=PUPIL):
    return {
        "links": [{"id": identifier}],
        "leerling": {"links": [{"id": owner}]},
        "beginDatumTijd": start,
        "eindDatumTijd": start,
        "afgehandeld": handled,
        "opmerkingen": remark,
        "absentieReden": {"omschrijving": reason, "geoorloofd": authorised},
    }


def _measure(identifier, day, label, complied=True, owner=PUPIL):
    return {
        "links": [{"id": identifier}],
        "leerling": {"links": [{"id": owner}]},
        "maatregelDatum": f"{day}T23:59:59.000+02:00",
        "nagekomen": complied,
        "automatischToegekend": True,
        "maatregel": {"omschrijving": label},
    }


def test_geoorloofd_is_bookkeeping_and_never_becomes_a_verdict():
    """Observed live: being sent out of a lesson is booked as authorised while
    detention is not. Any rule deriving fault from the flag would mislabel both,
    so reason and flag must survive untouched."""
    items = [
        _report("a", "2026-09-04T10:00:00+02:00", "Is er uit gestuurd", True),
        _report("b", "2026-09-05T13:00:00+02:00", "Terugkomklas", False),
    ]
    values = normalize_absences(items, PUPIL, SINCE)
    by_reason = {value["reason"]: value["authorised"] for value in values}
    assert by_reason == {"Is er uit gestuurd": True, "Terugkomklas": False}
    counts = absence_counts(values)
    assert counts["authorised"] == 1
    assert counts["unauthorised"] == 1
    assert label_counts(values, "reason") == {
        "Is er uit gestuurd": 1,
        "Terugkomklas": 1,
    }


def test_guardian_account_reports_are_split_per_child():
    items = [
        _report("a", "2026-09-04T10:00:00+02:00", "Tandarts", True),
        _report("b", "2026-09-05T10:00:00+02:00", "Tandarts", True, owner="pupil-2"),
    ]
    assert [value["id"] for value in normalize_absences(items, PUPIL, SINCE)] == ["a"]
    assert [value["id"] for value in normalize_absences(items, "pupil-2", SINCE)] == ["b"]


def test_report_without_a_usable_start_is_dropped_rather_than_counted():
    broken = _report("a", "", "Tandarts", True)
    assert normalize_absences([broken, {}, "not-a-dict"], PUPIL, SINCE) == []


def test_reports_before_the_school_year_are_excluded_and_order_is_newest_first():
    items = [
        _report("old", "2026-05-12T11:20:00+02:00", "Tandarts", True),
        _report("a", "2026-09-04T13:05:00+02:00", "Terugkomklas", False),
        _report("b", "2026-09-07T08:30:00+02:00", "Te laat in de les", False),
    ]
    values = normalize_absences(items, PUPIL, SINCE)
    assert [value["id"] for value in values] == ["b", "a"]


def test_unknown_flag_stays_unknown_and_counts_as_neither():
    item = _report("a", "2026-09-04T10:00:00+02:00", "Onbekend", None)
    item["absentieReden"].pop("geoorloofd")
    item.pop("afgehandeld")
    values = normalize_absences([item], PUPIL, SINCE)
    assert values[0]["authorised"] is None
    assert values[0]["handled"] is None
    counts = absence_counts(values)
    assert counts["authorised"] == 0
    assert counts["unauthorised"] == 0
    assert counts["open"] == 0


def test_measures_are_a_separate_source_and_survive_without_any_report():
    """The portal shows measures next to absence reports, but the reports
    endpoint never contains them. An overview built on reports alone therefore
    looks broken to a parent who sees both."""
    items = [
        _measure("m1", "2026-09-15", "Huiswerk niet in orde", complied=False),
        _measure("m2", "2026-09-10", "Materiaal niet in orde", complied=True),
        _measure("m3", "2026-05-01", "Huiswerk niet in orde"),
        _measure("m4", "2026-09-11", "Huiswerk niet in orde", owner="pupil-2"),
    ]
    values = normalize_measures(items, PUPIL, SINCE)
    assert [value["id"] for value in values] == ["m1", "m2"]
    assert measure_counts(values) == {"total": 2, "outstanding": 1}
    assert label_counts(values, "label") == {
        "Huiswerk niet in orde": 1,
        "Materiaal niet in orde": 1,
    }
    assert normalize_absences([], PUPIL, SINCE) == []


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 9, 22), date(2026, 8, 1)),
        (date(2026, 8, 1), date(2026, 8, 1)),
        (date(2026, 7, 31), date(2025, 8, 1)),
        (date(2027, 1, 5), date(2026, 8, 1)),
    ],
)
def test_school_year_starts_in_august(today, expected):
    assert school_year_start(today) == expected


def _sensor_pair(values, measures, *, remarks, monkeypatch):
    student = {"links": [{"id": PUPIL}], "roepnaam": "Seth"}
    coordinator = SimpleNamespace(
        last_update_success=True,
        data={"absences_by_student": {PUPIL: values}, "measures_by_student": {PUPIL: measures}},
    )
    entry = SimpleNamespace(
        entry_id="entry",
        options={"exports": {PUPIL: {"absences_enabled": True, "absence_remarks": remarks}}},
    )
    monkeypatch.setattr(
        "custom_components.somtoday.sensor.dt_util.now",
        lambda: datetime.fromisoformat("2026-09-22T10:00:00+02:00"),
    )
    return (
        SomtodayAbsenceSensor(coordinator, entry, student),
        SomtodayMeasureSensor(coordinator, entry, student),
    )


def test_staff_remarks_are_withheld_unless_separately_opted_in(monkeypatch):
    values = normalize_absences(
        [_report("a", "2026-09-04T13:05:00+02:00", "Terugkomklas", False, "PRIVATE_REMARK")],
        PUPIL,
        SINCE,
    )
    sensor, _ = _sensor_pair(values, [], remarks=False, monkeypatch=monkeypatch)
    assert sensor.native_value == 1
    assert "PRIVATE_REMARK" not in str(sensor.extra_state_attributes)
    assert sensor.extra_state_attributes["latest_reason"] == "Terugkomklas"

    sensor, _ = _sensor_pair(values, [], remarks=True, monkeypatch=monkeypatch)
    assert sensor.extra_state_attributes["reports"][0]["remark"] == "PRIVATE_REMARK"


def test_unreadable_overview_is_unavailable_instead_of_a_reassuring_zero(monkeypatch):
    absences, measures = _sensor_pair(None, None, remarks=False, monkeypatch=monkeypatch)
    assert absences.available is False
    assert measures.available is False
    assert absences.native_value is None
    assert measures.native_value is None

    absences, measures = _sensor_pair([], [], remarks=False, monkeypatch=monkeypatch)
    assert absences.available is True
    assert absences.native_value == 0


def test_measure_sensor_reports_outstanding_separately(monkeypatch):
    measures = normalize_measures(
        [
            _measure("m1", "2026-09-15", "Huiswerk niet in orde", complied=False),
            _measure("m2", "2026-09-10", "Huiswerk niet in orde", complied=True),
        ],
        PUPIL,
        SINCE,
    )
    _, sensor = _sensor_pair([], measures, remarks=False, monkeypatch=monkeypatch)
    attributes = sensor.extra_state_attributes
    assert sensor.native_value == 2
    assert attributes["outstanding"] == 1
    assert attributes["latest_label"] == "Huiswerk niet in orde"
    assert attributes["latest_complied"] is False


def _options_flow(options):
    """Mirror the helper in test_options: two children, no writable calendars."""
    entry = SimpleNamespace(entry_id="entry", options=options)
    students = [
        {"links": [{"id": student_id}], "roepnaam": name}
        for student_id, name in (("a", "Seth"), ("b", "Other child"))
    ]
    flow = SomtodayOptionsFlow()
    flow.hass = SimpleNamespace(
        data={"somtoday": {"entry": SimpleNamespace(data={"students": students})}},
        config_entries=SimpleNamespace(async_get_known_entry=lambda _: entry),
        states=SimpleNamespace(async_all=lambda _: []),
    )
    flow.handler = "entry"
    return flow


@pytest.mark.asyncio
async def test_switching_the_overview_off_removes_the_flag_instead_of_keeping_it():
    """A stale enabled flag would keep fetching records the user just opted out
    of, so the keys are dropped rather than written as false."""
    flow = _options_flow({"exports": {"a": {"absences_enabled": True, "absence_remarks": True}}})
    settings = await flow.async_step_init({"student_id": "a"})
    assert settings["data_schema"]({})["exports"]["enable_absences"] is True
    form = await flow.async_step_settings(
        {"enable_day": False, "enable_lessons": False, "enable_holidays": False,
         "enable_absences": False, "days_ahead": 14, "scan_interval": 15}
    )
    result = await flow.async_step_destinations(form["data_schema"]({}))
    route = result["data"]["exports"]["a"]
    assert "absences_enabled" not in route
    assert "absence_remarks" not in route


@pytest.mark.asyncio
async def test_enabling_the_overview_stores_both_opt_ins_for_that_child_only():
    flow = _options_flow({"exports": {"b": {"day_calendar": ""}}})
    await flow.async_step_init({"student_id": "a"})
    form = await flow.async_step_settings(
        {"enable_day": False, "enable_lessons": False, "enable_holidays": False,
         "enable_absences": True, "days_ahead": 14, "scan_interval": 15}
    )
    submitted = form["data_schema"]({"absences": {"absence_remarks": True}})
    result = await flow.async_step_destinations(submitted)
    assert result["data"]["exports"]["a"]["absences_enabled"] is True
    assert result["data"]["exports"]["a"]["absence_remarks"] is True
    assert "absences_enabled" not in result["data"]["exports"]["b"]


@pytest.mark.asyncio
async def test_diagnostics_reports_absence_counts_without_any_wording():
    values = normalize_absences(
        [_report("a", "2026-09-04T13:05:00+02:00", "PRIVATE_REASON", False, "PRIVATE_REMARK")],
        PUPIL,
        SINCE,
    )
    measures = normalize_measures(
        [_measure("m1", "2026-09-15", "PRIVATE_LABEL", complied=False)], PUPIL, SINCE
    )
    coordinator = SimpleNamespace(
        last_update_success=True,
        data={
            "students": [{"roepnaam": "PRIVATE_NAME"}],
            "absences_by_student": {PUPIL: values},
            "measures_by_student": {PUPIL: measures},
        },
    )
    entry = SimpleNamespace(
        entry_id="entry",
        data={"token": "PRIVATE_TOKEN"},
        options={"exports": {PUPIL: {"absences_enabled": True, "absence_remarks": True}}},
    )
    result = await async_get_config_entry_diagnostics(
        SimpleNamespace(data={"somtoday": {"entry": coordinator}}, states=SimpleNamespace(get=lambda _entity: None)),
        entry,
    )
    assert "PRIVATE" not in str(result)
    assert result["absence_report_count"] == 1
    assert result["measure_count"] == 1
    assert result["absence_enabled_count"] == 1
    assert result["absence_remarks_enabled_count"] == 1
