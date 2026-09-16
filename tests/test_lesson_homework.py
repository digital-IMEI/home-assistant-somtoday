from copy import deepcopy
from datetime import date

import pytest

from custom_components.somtoday.homework import homework_text, lesson_homework, normalize_homework


FIRST = date(2026, 9, 16)
LAST = date(2026, 9, 17)


@pytest.mark.parametrize(("raw", "expected"), [
    ("<p>Huiswerk:</p><p></p><p>1.6B opgave 81, 82</p><p>Extra uitdaging: 86</p>",
     "Huiswerk:\n1.6B opgave 81, 82\nExtra uitdaging: 86"),
    ("<p>&nbsp;L: pagina 36</p><p>\u00a0M: 20 / 21</p>", "L: pagina 36\nM: 20 / 21"),
    ("<ul><li>A &amp; B</li><li>C<br>D</li></ul>", "• A & B\n• C\nD"),
    ("2 < 3 en 5 > 4", "2 < 3 en 5 > 4"),
    ("<p>Lees <b>hoofdstuk 2</b></p><script>secret</script><style>hidden</style>", "Lees hoofdstuk 2"),
    (None, ""),
])
def test_homework_plain_text(raw, expected):
    assert homework_text(raw) == expected


def test_html_is_normalized_for_lessons_and_tasks():
    value = assignment()
    value["studiewijzerItem"].update(onderwerp="<b>woordenboek</b>",
                                   omschrijving="<p>maken opdrachten 6,7 + 8 blz. 21</p>")
    normalized = normalize_homework([value], "a", FIRST, LAST)[0]
    assert normalized["topic"] == "woordenboek"
    assert normalized["description"] == "maken opdrachten 6,7 + 8 blz. 21"
    enriched = lesson_homework([lesson()], [value], "a", FIRST, LAST)[0]
    assert "woordenboek · maken opdrachten 6,7 + 8 blz. 21" in enriched["omschrijving"]
    assert "<p>" not in enriched["omschrijving"]


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
