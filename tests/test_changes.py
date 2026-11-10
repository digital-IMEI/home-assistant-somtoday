from datetime import date, datetime
from types import SimpleNamespace

from custom_components.somtoday.calendar import SomtodayCalendar
from custom_components.somtoday.changes import iso_weeks, merge_changes
from custom_components.somtoday.export import desired_events
from custom_components.somtoday.models import school_day_bounds


def appointment(begin, end, naam, afkorting, lesuur, locatie="a1"):
    return {
        "links": [{"id": f"afspraak-{begin}"}],
        "afspraakStatus": "ACTIEF",
        "afspraakType": {"categorie": "Rooster", "naam": "Les"},
        "additionalObjects": {"vak": {"naam": naam, "afkorting": afkorting}},
        "beginDatumTijd": f"{begin}:00.000+01:00",
        "eindDatumTijd": f"{end}:00.000+01:00",
        "beginLesuur": lesuur,
        "eindLesuur": lesuur,
        "locatie": locatie,
        "omschrijving": f"{locatie} - 1Bxx - Bob",
    }


def item(begin, end, afkorting, naam, lesuur, change="", statuses=("2002",)):
    return {
        "$type": "participatie.live.RAfspraakItem",
        "uniqueIdentifier": f"u-{begin}",
        "afspraakItemType": "ROOSTER",
        "beginDatumTijd": f"{begin}:00",
        "eindDatumTijd": f"{end}:00",
        "beginLesuur": lesuur,
        "eindLesuur": lesuur,
        "locatie": "d4",
        "titel": afkorting,
        "vak": {"naam": naam, "afkorting": afkorting},
        "statusNotifications": [{"status": status} for status in statuses],
        "wijzigingOmschrijving": change,
    }


APPOINTMENTS = [
    appointment("2026-11-23T09:10", "2026-11-23T09:50", "wiskunde", "wi", 2),
    appointment("2026-11-23T10:50", "2026-11-23T11:30", "Engels", "en", 4),
]
ITEMS = [
    item("2026-11-23T09:10", "2026-11-23T09:50", "wi", "wiskunde", 2),
    # Cancelled: absent from /afspraken, only an abbreviation as subject name.
    item("2026-11-23T09:50", "2026-11-23T10:30", "la", "la", 3, "Les vervalt", ("4001", "4007")),
    item("2026-11-23T10:50", "2026-11-23T11:30", "en", "Engels", 4,
         "De les is verplaatst (komt van wo 12:40u)."),
    # Elsewhere this week: provides the full name for "la".
    item("2026-11-24T08:30", "2026-11-24T09:10", "la", "Latijn", 1),
    {"$type": "participatie.live.RKWTAfspraakItem", "beginDatumTijd": "2026-11-26T18:20:00",
     "eindDatumTijd": "2026-11-26T18:40:00", "statusNotifications": []},
]


def test_iso_weeks_cover_the_window():
    assert iso_weeks(date(2026, 11, 10), date(2026, 11, 24)) == [(2026, 46), (2026, 47), (2026, 48)]
    assert iso_weeks(date(2026, 12, 30), date(2027, 1, 4)) == [(2026, 53), (2027, 1)]


def test_changes_are_merged_and_cancelled_lessons_added():
    merged = sorted(merge_changes(APPOINTMENTS, ITEMS), key=lambda a: a["beginDatumTijd"])
    assert [a["additionalObjects"]["vak"]["naam"] for a in merged] == ["wiskunde", "Latijn", "Engels"]
    wiskunde, latijn, engels = merged
    assert wiskunde["_somtoday_change"] == "" and not wiskunde["_somtoday_cancelled"]
    assert engels["_somtoday_change"].startswith("De les is verplaatst")
    assert engels["afspraakStatus"] == "ACTIEF"
    assert latijn["_somtoday_cancelled"] and latijn["afspraakStatus"] == "VERVALLEN"
    assert datetime.fromisoformat(latijn["beginDatumTijd"]).utcoffset().total_seconds() == 3600
    assert latijn["beginLesuur"] == 3


def test_cancelled_lessons_stay_out_of_exports_and_school_days():
    merged = merge_changes(APPOINTMENTS, ITEMS)
    start = datetime.fromisoformat("2026-11-23T00:00:00+01:00")
    end = datetime.fromisoformat("2026-11-24T00:00:00+01:00")
    exported = desired_events(merged, {"lesson_calendar": "calendar.x"}, "a", start, end)
    assert len(exported) == 2
    assert len(school_day_bounds(merged)) == 1


def test_calendar_shows_status_change_and_lesson_hour():
    merged = merge_changes(APPOINTMENTS, ITEMS)
    calendar = object.__new__(SomtodayCalendar)
    calendar.student = "a"
    calendar.coordinator = SimpleNamespace(data={"appointments_by_student": {"a": merged}})
    events = calendar._events(
        datetime.fromisoformat("2026-11-23T00:00:00+01:00"),
        datetime.fromisoformat("2026-11-24T00:00:00+01:00"),
    )
    by_summary = {event.summary: event for event in events}
    assert by_summary["Latijn (valt uit)"].description.splitlines()[:3] == [
        "Status: uitval", "Wijziging: Les vervalt", "Lesuur: 3"]
    assert by_summary["Engels"].description.splitlines()[0] == "Status: gewijzigd"
    assert by_summary["wiskunde"].description == "Lesuur: 2\na1 - 1Bxx - Bob"


def test_without_week_items_nothing_changes():
    assert merge_changes(APPOINTMENTS, []) == APPOINTMENTS
