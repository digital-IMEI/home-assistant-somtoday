from copy import deepcopy
from datetime import date

from custom_components.somtoday.homework import lesson_homework


FIRST = date(2026, 9, 16)
LAST = date(2026, 9, 17)


def lesson():
    return {"beginDatumTijd": "2026-09-16T08:30:00+02:00",
            "eindDatumTijd": "2026-09-16T09:20:00+02:00",
            "omschrijving": "Room 211", "additionalObjects": {"vak": {"naam": "Math"}}}


def assignment(identifier="1", source="appointment"):
    return {"links": [{"id": identifier}], "_somtoday_assignment_kind": source,
            "datumTijd": "2026-09-16T08:30:00+02:00",
            "lesgroep": {"vak": {"naam": "Math"}},
            "studiewijzerItem": {"huiswerkType": "HUISWERK", "onderwerp": "Chapter 2",
                                  "omschrijving": "Exercises 1–8"},
            "additionalObjects": {"swigemaaktVinkjes": {"items": [
                {"leerling": {"links": [{"id": "a"}]}, "gemaakt": False},
                {"leerling": {"links": [{"id": "b"}]}, "gemaakt": True}]}}}


def test_unique_match_preserves_description_and_child_progress():
    original = lesson()
    result = lesson_homework([original], [assignment()], "a", FIRST, LAST)
    assert result[0]["omschrijving"] == "Room 211\n\nHuiswerk\n• Chapter 2 · Exercises 1–8 — Openstaand"
    assert original == lesson()
    assert "Voltooid" in lesson_homework([original], [assignment()], "b", FIRST, LAST)[0]["omschrijving"]
    assert "Openstaand" not in lesson_homework([original], [assignment()], "c", FIRST, LAST)[0]["omschrijving"]


def test_ambiguous_and_day_week_assignments_are_not_attached():
    assert lesson_homework([lesson(), lesson()], [assignment()], "a", FIRST, LAST) == [lesson(), lesson()]
    assert lesson_homework([lesson()], [assignment(source="day"), assignment("2", "week")], "a", FIRST, LAST) == [lesson()]
    wrong = assignment()
    wrong["datumTijd"] = "2026-09-16T09:20:00+02:00"
    assert lesson_homework([lesson()], [wrong], "a", FIRST, LAST) == [lesson()]


def test_multiple_items_empty_results_and_cancelled_lessons():
    items = [assignment(), assignment("2")]
    assert lesson_homework([lesson()], items, "a", FIRST, LAST)[0]["omschrijving"].count("•") == 2
    assert lesson_homework([lesson()], [], "a", FIRST, LAST) == [lesson()]
    cancelled = {**lesson(), "afspraakStatus": "GEANNULEERD"}
    assert lesson_homework([cancelled], items, "a", FIRST, LAST) == [cancelled]
