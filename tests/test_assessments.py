from datetime import date, datetime, timedelta

from custom_components.somtoday.assessments import (
    assessment_description,
    assessment_summary,
    normalize_assessments,
)


START = datetime.fromisoformat("2026-09-15T09:20:00+02:00")


def assignment(identifier, kind, assessment_type="TOETS", due=None):
    value = {
        "links": [{"id": identifier}],
        "_somtoday_assignment_kind": kind,
        "studiewijzerItem": {
            "huiswerkType": assessment_type,
            "onderwerp": "Hoofdstuk 3",
            "omschrijving": "Leer paragraaf 3.1 en 3.2",
        },
        "lesgroep": {"vak": {"naam": "Wiskunde"}},
        "additionalObjects": {
            "swigemaaktVinkjes": {"items": [{"gemaakt": False}]}
        },
    }
    if due is not None:
        value["datumTijd"] = due
    return value


def test_explicit_tests_are_dated_without_inventing_times():
    lesson = {
        "beginDatumTijd": START.isoformat(),
        "eindDatumTijd": (START + timedelta(minutes=50)).isoformat(),
        "additionalObjects": {"vak": {"naam": "Wiskunde"}},
    }
    values = normalize_assessments(
        [
            assignment("timed", "appointment", due=START.isoformat()),
            assignment("day", "day", due="2026-09-16T00:00:00+02:00"),
            assignment("week", "week"),
            assignment("homework", "day", "HUISWERK", "2026-09-17"),
        ],
        [lesson],
        date(2026, 9, 14),
        date(2026, 9, 30),
    )

    assert [value["id"] for value in values] == ["timed", "day", "week"]
    assert values[0]["start"] == START
    assert values[0]["end"] == START + timedelta(minutes=50)
    assert values[0]["all_day"] is False
    assert values[1]["start"] == date(2026, 9, 16)
    assert values[1]["end"] == date(2026, 9, 17)
    assert values[1]["all_day"] is True
    assert values[2]["start"] is None
    assert values[2]["date_known"] is False
    assert assessment_summary(values[0]) == "Wiskunde · Toets · Hoofdstuk 3"
    assert assessment_description(values[0]).endswith("Afgerond: nee")


def test_appointment_without_exact_lesson_match_becomes_all_day():
    values = normalize_assessments(
        [assignment("test", "appointment", due=START.isoformat())],
        [],
        date(2026, 9, 14),
        date(2026, 9, 30),
    )

    assert values[0]["start"] == START.date()
    assert values[0]["end"] == START.date() + timedelta(days=1)
    assert values[0]["all_day"] is True


def test_consecutive_study_guide_test_periods_form_one_assessment():
    first_start = START.replace(hour=10, minute=25)
    second_start = START.replace(hour=11, minute=15)
    final_end = START.replace(hour=12, minute=5)
    lessons = [
        {
            "beginDatumTijd": begin.isoformat(),
            "eindDatumTijd": finish.isoformat(),
            "additionalObjects": {"vak": {"naam": "Wiskunde"}},
        }
        for begin, finish in (
            (first_start, second_start),
            (second_start, final_end),
        )
    ]
    assignments = [
        assignment("one", "appointment", due=first_start.isoformat()),
        assignment("two", "appointment", due=second_start.isoformat()),
    ]

    values = normalize_assessments(
        assignments, lessons, date(2026, 9, 14), date(2026, 9, 30)
    )

    assert len(values) == 1
    assert values[0]["id"] == "one"
    assert values[0]["start"] == first_start
    assert values[0]["end"] == final_end
    assert values[0]["all_day"] is False


def test_different_topics_or_nonconsecutive_test_periods_stay_separate():
    second_start = START + timedelta(minutes=50)
    third_start = START + timedelta(hours=2)
    assignments = [
        assignment("first", "appointment", due=START.isoformat()),
        assignment("different-topic", "appointment", due=second_start.isoformat()),
        assignment("later", "appointment", due=third_start.isoformat()),
    ]
    assignments[1]["studiewijzerItem"]["onderwerp"] = "Hoofdstuk 4"
    lessons = [
        {
            "beginDatumTijd": begin.isoformat(),
            "eindDatumTijd": (begin + timedelta(minutes=50)).isoformat(),
            "additionalObjects": {"vak": {"naam": "Wiskunde"}},
        }
        for begin in (START, second_start, third_start)
    ]

    values = normalize_assessments(
        assignments, lessons, date(2026, 9, 14), date(2026, 9, 30)
    )

    assert [value["id"] for value in values] == [
        "first", "different-topic", "later"
    ]
