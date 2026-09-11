from types import SimpleNamespace
from datetime import datetime, timedelta

from custom_components.somtoday.models import automatic_day_titles
from custom_components.somtoday.export import desired_events
from custom_components.somtoday.calendar import SomtodaySchoolDayCalendar


def appointment(title, **extra):
    return {"titel": title, "beginDatumTijd": "2026-09-14T09:20:00+02:00",
            "eindDatumTijd": "2026-09-14T10:10:00+02:00",
            "afspraakType": {"categorie": "Rooster"}, **extra}


def test_shared_full_title_and_formatting():
    items = [appointment("O&O_GaiaZoo_excursie")] * 2
    assert automatic_day_titles(items) == {"2026-09-14": "GaiaZoo excursie"}
    assert automatic_day_titles([appointment("Sportdag")]) == {"2026-09-14": "Sportdag"}
    assert automatic_day_titles([appointment("O&O_  GaiaZoo__excursie ")]) == {"2026-09-14": "GaiaZoo excursie"}


def test_mixed_empty_and_cancelled_titles():
    first = appointment("O&O_GaiaZoo")
    assert automatic_day_titles([first, appointment("Other_GaiaZoo")]) == {}
    assert automatic_day_titles([first, appointment("")]) == {}
    assert automatic_day_titles([appointment("prefix___")]) == {}
    assert automatic_day_titles([first, appointment("Pauze"), appointment("Math", afspraakStatus="GEANNULEERD")]) == {"2026-09-14": "GaiaZoo"}


def test_export_option_and_fallback_keep_stable_identity():
    start = datetime.fromisoformat("2026-09-14T00:00:00+02:00")
    options = {"day_calendar": "calendar.family", "day_title": "School · Seth"}
    items = [appointment("O&O_GaiaZoo_excursie")]
    normal = desired_events(items, options, "a", start, start + timedelta(days=1))
    options["automatic_day_title"] = True
    automatic = desired_events(items, options, "a", start, start + timedelta(days=1))
    assert normal.keys() == automatic.keys()
    assert next(iter(normal.values()))["summary"] == "School · Seth"
    assert next(iter(automatic.values()))["summary"] == "GaiaZoo excursie"
    mixed = desired_events(items + [appointment("Math")], options, "a", start, start + timedelta(days=1))
    assert next(iter(mixed.values()))["summary"] == "School · Seth"


def test_source_calendar_uses_same_title():
    start = datetime.fromisoformat("2026-09-14T09:20:00+02:00")
    coordinator = SimpleNamespace(data={
        "appointments_by_student": {"a": [appointment("O&O_GaiaZoo_excursie")]},
        "school_days_by_student": {"a": {"2026-09-14": (start, start + timedelta(hours=1))}},
    })
    entry = SimpleNamespace(entry_id="entry", options={"exports": {"a": {"automatic_day_title": True}}})
    calendar = SomtodaySchoolDayCalendar(coordinator, entry, {"links": [{"id": "a"}], "roepnaam": "Seth"})
    event = calendar._events(start, start + timedelta(days=1))[0]
    assert event.summary == "GaiaZoo excursie"
    assert event.start == start
