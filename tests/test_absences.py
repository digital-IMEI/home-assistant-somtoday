import json
import logging
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import ClientResponseError
from homeassistant.util import dt as dt_util

from custom_components.somtoday.absences import (
    ABSENCE_BUCKETS,
    LESSON_BUCKETS,
    category_counts,
    normalize_absence_registrations,
    normalize_lesson_registrations,
    outstanding_measures,
    registration_snapshot,
)
from custom_components.somtoday.api import SomtodayApiError, SomtodayAuthenticationError
from custom_components.somtoday.coordinator import SomtodayCoordinator
from custom_components.somtoday.sensor import (
    SomtodayAbsenceSensor,
    SomtodayLessonRegistrationSensor,
)
from custom_components.somtoday.diagnostics import async_get_config_entry_diagnostics
from custom_components.somtoday.config_flow import SomtodayOptionsFlow

PUPIL = "pupil-1"
ABSENCE_NAMES = tuple(name for _, name in ABSENCE_BUCKETS)
LESSON_NAMES = tuple(name for _, name in LESSON_BUCKETS)
ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "somtoday"


@pytest.fixture
def school_time_zone():
    """Dutch summer time as a fixed offset, so the result is the same on any runner."""
    previous = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(timezone(timedelta(hours=2)))
    yield
    dt_util.set_default_time_zone(previous)


def _registration(reason, start, authorised, handled=True, identifier=1):
    return {
        "omschrijving": reason,
        "begin": start,
        "eind": start,
        "afgehandeld": handled,
        "geoorloofd": authorised,
        "registratieSoort": "ABSENTIEMELDING",
        "registratieId": identifier,
    }


def _lesson(subject, start, hour, room="c208", identifier="1"):
    return {
        "uniqueIdentifier": identifier,
        "locatie": room,
        "beginDatumTijd": start,
        "eindDatumTijd": start,
        "beginLesuur": hour,
        "titel": f"{room} - grp - TCH",
        "vak": {"naam": subject, "afkorting": subject[:3]},
    }


def _overview(**buckets):
    base = {key: [] for key, _ in ABSENCE_BUCKETS + LESSON_BUCKETS}
    base.update(buckets)
    return base


def test_geoorloofd_is_bookkeeping_and_never_becomes_a_verdict():
    """Observed live: being sent out of a lesson is booked as authorised while
    detention is not. A rule deriving fault from the flag would mislabel both,
    so reason and flag must survive untouched."""
    overview = _overview(
        teLaat=[
            _registration("Is er uit gestuurd", "2026-09-04T10:00:00+02:00", True, identifier=1),
            _registration("Terugkomklas", "2026-09-05T13:00:00+02:00", False, identifier=2),
        ]
    )
    values = normalize_absence_registrations(overview)
    assert {v["reason"]: v["authorised"] for v in values} == {
        "Is er uit gestuurd": True,
        "Terugkomklas": False,
    }


def test_materials_and_homework_come_only_from_the_lesson_buckets():
    """The portal shows these next to the absences, but the absence list
    endpoint never contains them. Reading only the absence side is exactly the
    bug a parent notices: "Materiaal niet in orde" is simply missing."""
    overview = _overview(
        materiaalNietInOrde=[
            _lesson("Duits", "2026-09-18T10:20:00", 3, identifier="m1"),
            _lesson("mathematics", "2026-09-11T09:15:00", 2, room="e05", identifier="m2"),
        ],
        huiswerkNietGemaakt=[
            _lesson("geography", "2026-09-15T10:20:00", 3, room="a10", identifier="h1"),
        ],
    )
    assert normalize_absence_registrations(overview) == []
    lessons = normalize_lesson_registrations(overview)
    assert [value["id"] for value in lessons] == ["m1", "h1", "m2"]
    latest = lessons[0]
    assert latest["category"] == "materiaal_niet_in_orde"
    assert latest["subject"] == "Duits"
    assert latest["lesson_hour"] == 3
    assert category_counts(lessons, LESSON_NAMES) == {
        "huiswerk_niet_gemaakt": 1,
        "materiaal_niet_in_orde": 2,
    }


def test_empty_buckets_are_reported_as_zero_not_left_out():
    """A template asking for lates must get 0, not an attribute that is absent."""
    counts = category_counts(normalize_absence_registrations(_overview()), ABSENCE_NAMES)
    assert set(counts) == set(ABSENCE_NAMES)
    assert all(value == 0 for value in counts.values())


@pytest.mark.parametrize(
    "overview",
    [_overview(), {"teLaat": []}, {"teLaat": None, "materiaalNietInOrde": []}],
    ids=["all-buckets-empty", "missing-buckets", "null-bucket"],
)
def test_a_valid_empty_overview_is_accepted_as_zero(overview):
    assert registration_snapshot(overview) == {"absences": [], "lessons": []}


@pytest.mark.parametrize(
    "overview",
    [{"error": "permission denied"}, {}, [], None, "text"],
    ids=["error-object", "empty-object", "list", "null", "text"],
)
def test_a_response_that_is_not_an_overview_is_refused(overview):
    """Accepting these published available sensors with zero registrations."""
    with pytest.raises(ValueError):
        registration_snapshot(overview)
    with pytest.raises(ValueError):
        normalize_absence_registrations(overview)


@pytest.mark.parametrize(
    "overview",
    [
        {"teLaat": "unexpected"},
        {"teLaat": {}},
        {"teLaat": ["row"]},
        {"materiaalNietInOrde": [1]},
    ],
    ids=["text-bucket", "object-bucket", "text-row", "number-row"],
)
def test_a_bucket_of_the_wrong_type_is_refused(overview):
    with pytest.raises(ValueError):
        registration_snapshot(overview)


@pytest.mark.parametrize(
    "overview",
    [
        _overview(teLaat=[_registration("Te laat", "", False)]),
        _overview(teLaat=[_registration("Te laat", "yesterday", False)]),
        _overview(teLaat=[_registration("Te laat", 1757000000, False)]),
        _overview(teLaat=[{**_registration("Te laat", "2026-09-04T08:30:00+02:00", False),
                           "eind": "later"}]),
        _overview(materiaalNietInOrde=[_lesson("Duits", "", 3)]),
    ],
    ids=["missing-start", "unparseable-start", "numeric-start", "unparseable-end", "lesson-without-start"],
)
def test_a_row_without_a_usable_date_refuses_the_overview_instead_of_lowering_the_count(overview):
    with pytest.raises(ValueError):
        registration_snapshot(overview)


def test_times_with_and_without_offset_are_compared_in_school_time(school_time_zone):
    """Absence buckets carry an offset, lesson buckets naive local time. Mixing
    them used to raise TypeError while sorting; both are now local and aware."""
    overview = _overview(
        teLaat=[
            _registration("Te laat", "2026-09-04T08:30:00", False, identifier=1),
            _registration("Te laat", "2026-09-05T08:30:00+02:00", False, identifier=2),
            _registration("Te laat", "2026-09-05T08:00:00", False, identifier=3),
        ]
    )
    values = registration_snapshot(overview)["absences"]
    assert [value["id"] for value in values] == ["2", "3", "1"]
    assert all(value["start"].utcoffset() == timedelta(hours=2) for value in values)
    assert values[2]["start"].isoformat() == "2026-09-04T08:30:00+02:00"


def test_unknown_flag_stays_unknown_and_is_not_read_as_false():
    entry = _registration("Onbekend", "2026-09-04T10:00:00+02:00", None)
    entry.pop("geoorloofd")
    entry.pop("afgehandeld")
    value = normalize_absence_registrations(_overview(teLaat=[entry]))[0]
    assert value["authorised"] is None
    assert value["handled"] is None


def test_absence_buckets_merge_into_one_timeline_newest_first():
    overview = _overview(
        teLaat=[_registration("Te laat", "2026-09-07T08:30:00+02:00", False, identifier=1)],
        ongeoorloofdAfwezig=[_registration("Spijbelen", "2026-09-19T09:00:00+02:00", False, identifier=2)],
        geoorloofdAfwezig=[_registration("Tandarts", "2026-09-12T11:00:00+02:00", True, identifier=3)],
    )
    values = normalize_absence_registrations(overview)
    assert [value["id"] for value in values] == ["2", "3", "1"]
    assert category_counts(values, ABSENCE_NAMES)["ongeoorloofd_afwezig"] == 1


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([{"nagekomen": False}, {"nagekomen": False}, {"nagekomen": True}], 2),
        ([], 0),
    ],
)
def test_only_an_explicit_false_counts_as_still_to_make_good(items, expected):
    assert outstanding_measures(items) == expected


@pytest.mark.parametrize(
    "items",
    [[{"nagekomen": False}, {"nagekomen": None}], [{}], ["row"], {"items": []}],
    ids=["null-flag", "missing-flag", "text-row", "object"],
)
def test_a_measure_without_a_flag_makes_the_count_unknown_not_lower(items):
    with pytest.raises(ValueError):
        outstanding_measures(items)


def _sensors(absences, measures, *, reasons):
    student = {"links": [{"id": PUPIL}], "roepnaam": "Seth"}
    coordinator = SimpleNamespace(
        last_update_success=True,
        data={"absences_by_student": {PUPIL: absences}, "measures_by_student": {PUPIL: measures}},
    )
    entry = SimpleNamespace(
        entry_id="entry",
        options={"exports": {PUPIL: {"absences_enabled": True, "absence_remarks": reasons}}},
    )
    return (
        SomtodayAbsenceSensor(coordinator, entry, student),
        SomtodayLessonRegistrationSensor(coordinator, entry, student),
    )


def test_staff_wording_is_withheld_unless_separately_opted_in():
    values = normalize_absence_registrations(
        _overview(teLaat=[_registration("PRIVATE_REASON", "2026-09-04T13:05:00+02:00", False)])
    )
    sensor, _ = _sensors(values, None, reasons=False)
    assert sensor.native_value == 1
    assert "PRIVATE_REASON" not in str(sensor.extra_state_attributes)
    assert sensor.extra_state_attributes["te_laat"] == 1

    sensor, _ = _sensors(values, None, reasons=True)
    assert sensor.extra_state_attributes["latest_reason"] == "PRIVATE_REASON"


def test_unreadable_overview_is_unavailable_instead_of_a_reassuring_zero():
    absences, lessons = _sensors(None, None, reasons=False)
    assert absences.available is False
    assert lessons.available is False
    assert absences.native_value is None
    assert lessons.native_value is None

    absences, lessons = _sensors([], {"lessons": [], "outstanding": 0}, reasons=False)
    assert absences.available is True
    assert absences.native_value == 0
    assert lessons.native_value == 0


def test_unreadable_measure_endpoint_does_not_claim_nothing_is_outstanding():
    lessons = normalize_lesson_registrations(
        _overview(huiswerkNietGemaakt=[_lesson("Duits", "2026-09-08T11:05:00", 4)])
    )
    _, sensor = _sensors([], {"lessons": lessons, "outstanding": None}, reasons=False)
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["outstanding_measures"] is None
    assert sensor.extra_state_attributes["subjects"] == {"Duits": 1}


def test_entity_names_are_translated_with_the_child_filled_in():
    absences, lessons = _sensors([], {"lessons": [], "outstanding": 0}, reasons=False)
    assert absences.translation_key == "absences"
    assert lessons.translation_key == "lesson_registrations"
    assert absences.translation_placeholders == {"student": "Seth"}
    for language, expected in (
        ("en", ("{student} · Absences", "{student} · Lesson registrations")),
        ("nl", ("{student} · Absenties", "{student} · Lesregistraties")),
    ):
        names = json.loads(
            (ROOT / "translations" / f"{language}.json").read_text(encoding="utf-8")
        )["entity"]["sensor"]
        assert (names["absences"]["name"], names["lesson_registrations"]["name"]) == expected


def _options_flow(options):
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
    """A stale enabled flag would keep fetching records the user opted out of."""
    flow = _options_flow({"exports": {"a": {"absences_enabled": True, "absence_remarks": True}}})
    settings = await flow.async_step_init({"student_id": "a"})
    assert settings["data_schema"]({})["exports"]["enable_absences"] is True
    form = await flow.async_step_settings(
        {"enable_day": False, "enable_lessons": False, "enable_holidays": False,
         "enable_absences": False, "days_ahead": 14, "scan_interval": 15}
    )
    route = (await flow.async_step_destinations(form["data_schema"]({})))["data"]["exports"]["a"]
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
    result = await flow.async_step_destinations(
        form["data_schema"]({"absences": {"absence_remarks": True}})
    )
    assert result["data"]["exports"]["a"]["absences_enabled"] is True
    assert result["data"]["exports"]["a"]["absence_remarks"] is True
    assert "absences_enabled" not in result["data"]["exports"]["b"]


@pytest.mark.asyncio
async def test_diagnostics_reports_counts_without_any_wording():
    absences = normalize_absence_registrations(
        _overview(teLaat=[_registration("PRIVATE_REASON", "2026-09-04T13:05:00+02:00", False)])
    )
    lessons = normalize_lesson_registrations(
        _overview(materiaalNietInOrde=[_lesson("PRIVATE_SUBJECT", "2026-09-18T10:20:00", 3)])
    )
    coordinator = SimpleNamespace(
        last_update_success=True,
        data={
            "students": [{"roepnaam": "PRIVATE_NAME"}],
            "absences_by_student": {PUPIL: absences},
            "measures_by_student": {PUPIL: {"lessons": lessons, "outstanding": 3}},
        },
        _registration_reports={
            PUPIL: [
                {"source": "overview", "checked_at": "2026-09-28T10:00:00+00:00",
                 "status": "failed", "category": "http_error", "http_status": 403,
                 "detail": "PRIVATE_RESPONSE_BODY"},
                {"source": "measures", "checked_at": "2026-09-28T10:00:01+00:00",
                 "status": "ok"},
            ]
        },
    )
    entry = SimpleNamespace(
        entry_id="entry",
        data={"token": "PRIVATE_TOKEN"},
        options={"exports": {PUPIL: {"absences_enabled": True, "absence_remarks": True}}},
    )
    result = await async_get_config_entry_diagnostics(
        SimpleNamespace(
            data={"somtoday": {"entry": coordinator}},
            states=SimpleNamespace(get=lambda _entity: None),
        ),
        entry,
    )
    assert "PRIVATE" not in str(result)
    assert PUPIL not in str(result)
    assert result["absence_report_count"] == 1
    assert result["lesson_registration_count"] == 1
    assert result["outstanding_measure_count"] == 3
    assert result["absence_enabled_count"] == 1
    assert result["absence_source_results"] == [
        {"source": "overview", "checked_at": "2026-09-28T10:00:00+00:00",
         "status": "failed", "category": "http_error", "http_status": 403},
        {"source": "measures", "checked_at": "2026-09-28T10:00:01+00:00", "status": "ok"},
    ]


def _coordinator(monkeypatch, **client):
    """A coordinator for one opted-in child, built like the upstream startup tests."""
    import custom_components.somtoday.coordinator as module

    coordinator = object.__new__(SomtodayCoordinator)
    coordinator.entry = SimpleNamespace(
        entry_id="test", data={"token": {}},
        options={"exports": {PUPIL: {"absences_enabled": True}}},
    )
    coordinator.hass = SimpleNamespace()
    methods = {
        "students": AsyncMock(return_value=[{"links": [{"id": PUPIL}], "roepnaam": "Seth"}]),
        "appointments": AsyncMock(return_value=[]),
        "holidays": AsyncMock(return_value=[]),
        "assessments": AsyncMock(return_value=[]),
        "registrations": AsyncMock(return_value=_overview()),
        "active_measures": AsyncMock(return_value=[]),
    }
    methods.update(client)
    coordinator.client = SimpleNamespace(token={}, **methods)
    coordinator._holidays = {}
    coordinator._holidays_checked = None
    coordinator.export_ready = False
    monkeypatch.setattr(module.ir, "async_delete_issue", Mock())
    return coordinator


def _statuses(coordinator):
    return {report["source"]: report["status"] for report in coordinator._registration_reports[PUPIL]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overview",
    [
        {"error": "permission denied"},
        {"teLaat": "unexpected"},
        {"teLaat": [{"begin": "2026-09-04T08:30:00+02:00"}, "row"]},
        {"teLaat": [{"omschrijving": "PRIVATE_REASON", "begin": "not a date"}]},
        # Not a ValueError: the id lookup trips over a malformed link.
        {"teLaat": [{"begin": "2026-09-04T08:30:00+02:00", "links": "x"}]},
    ],
    ids=["error-object", "text-bucket", "text-row", "unparseable-date", "malformed-link"],
)
async def test_malformed_overview_leaves_the_roster_and_only_its_own_source_unavailable(
    monkeypatch, caplog, overview
):
    coordinator = _coordinator(monkeypatch, registrations=AsyncMock(return_value=overview))
    result = await coordinator._async_update_data()
    # The shared refresh completed: roster and the other sources are published.
    assert len(result["students"]) == 1
    assert result["assessments_by_student"] == {PUPIL: []}
    assert result["holidays_by_student"][PUPIL] is not None
    # Only the absence entities go unavailable, and the reason is recorded.
    assert result["absences_by_student"] == {PUPIL: None}
    assert result["measures_by_student"] == {PUPIL: None}
    assert _statuses(coordinator) == {"overview": "failed", "measures": "ok"}
    assert coordinator._registration_reports[PUPIL][0]["category"] == "invalid_response"
    assert "invalid_response" in caplog.text
    assert PUPIL not in caplog.text
    assert "PRIVATE" not in caplog.text


@pytest.mark.asyncio
async def test_mixed_offsets_from_the_review_no_longer_abort_the_refresh(monkeypatch):
    overview = {"teLaat": [{"begin": "2026-09-04T08:30:00"}, {"begin": "2026-09-05T08:30:00+02:00"}]}
    coordinator = _coordinator(monkeypatch, registrations=AsyncMock(return_value=overview))
    result = await coordinator._async_update_data()
    assert len(result["absences_by_student"][PUPIL]) == 2
    assert result["measures_by_student"][PUPIL] == {"lessons": [], "outstanding": 0}
    assert _statuses(coordinator) == {"overview": "ok", "measures": "ok"}


@pytest.mark.asyncio
async def test_each_source_reports_its_own_failure_class_and_recovers(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    forbidden = SomtodayApiError("Somtoday API returned HTTP 403")
    forbidden.__cause__ = ClientResponseError(Mock(real_url="https://private"), (), status=403)
    timeout = SomtodayApiError("Invalid response from Somtoday")
    timeout.__cause__ = TimeoutError()
    coordinator = _coordinator(
        monkeypatch,
        registrations=AsyncMock(side_effect=forbidden),
        active_measures=AsyncMock(side_effect=timeout),
    )
    result = await coordinator._async_update_data()
    assert result["absences_by_student"] == {PUPIL: None}
    overview, measures = coordinator._registration_reports[PUPIL]
    assert (overview["source"], overview["category"], overview["http_status"]) == ("overview", "http_error", 403)
    assert (measures["source"], measures["category"]) == ("measures", "timeout")
    assert overview["checked_at"] and measures["checked_at"]
    assert "private" not in caplog.text

    # The overview recovers while the measure list stays unreadable: the
    # entities come back and only the outstanding count is unknown.
    coordinator.client.registrations = AsyncMock(return_value=_overview())
    result = await coordinator._async_update_data()
    assert result["absences_by_student"] == {PUPIL: []}
    assert result["measures_by_student"] == {PUPIL: {"lessons": [], "outstanding": None}}
    assert _statuses(coordinator) == {"overview": "ok", "measures": "failed"}

    coordinator.client.active_measures = AsyncMock(return_value=[{"nagekomen": False}])
    result = await coordinator._async_update_data()
    assert result["measures_by_student"][PUPIL]["outstanding"] == 1
    assert _statuses(coordinator) == {"overview": "ok", "measures": "ok"}
    assert "recovered" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["registrations", "active_measures"])
async def test_expired_sign_in_from_an_absence_source_still_requests_reauthentication(
    monkeypatch, source
):
    from homeassistant.exceptions import ConfigEntryAuthFailed

    coordinator = _coordinator(
        monkeypatch, **{source: AsyncMock(side_effect=SomtodayAuthenticationError("expired"))}
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_nothing_is_requested_for_a_child_that_is_not_opted_in(monkeypatch):
    coordinator = _coordinator(monkeypatch)
    coordinator.entry.options = {"exports": {PUPIL: {"day_calendar": ""}}}
    result = await coordinator._async_update_data()
    coordinator.client.registrations.assert_not_awaited()
    coordinator.client.active_measures.assert_not_awaited()
    assert result["absences_by_student"] == {}
    assert coordinator._registration_reports == {}
