from types import SimpleNamespace

import pytest

from custom_components.somtoday.absences import (
    ABSENCE_BUCKETS,
    LESSON_BUCKETS,
    category_counts,
    normalize_absence_registrations,
    normalize_lesson_registrations,
    outstanding_measures,
)
from custom_components.somtoday.sensor import (
    SomtodayAbsenceSensor,
    SomtodayLessonRegistrationSensor,
)
from custom_components.somtoday.diagnostics import async_get_config_entry_diagnostics
from custom_components.somtoday.config_flow import SomtodayOptionsFlow

PUPIL = "pupil-1"
ABSENCE_NAMES = tuple(name for _, name in ABSENCE_BUCKETS)
LESSON_NAMES = tuple(name for _, name in LESSON_BUCKETS)


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


def test_entry_without_a_usable_start_is_dropped_rather_than_counted():
    overview = _overview(
        teLaat=[_registration("Te laat", "", False)],
        materiaalNietInOrde=[_lesson("Duits", "", 3)],
    )
    assert normalize_absence_registrations(overview) == []
    assert normalize_lesson_registrations(overview) == []


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
        ([{"nagekomen": None}, {}], 0),
        ([], 0),
    ],
)
def test_only_an_explicit_false_counts_as_still_to_make_good(items, expected):
    assert outstanding_measures(items) == expected


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
    assert result["absence_report_count"] == 1
    assert result["lesson_registration_count"] == 1
    assert result["outstanding_measure_count"] == 3
    assert result["absence_enabled_count"] == 1
