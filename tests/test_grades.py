from types import SimpleNamespace

from custom_components.somtoday.grades import grade_params, normalize_grades
from custom_components.somtoday.sensor import SomtodayLatestGradeSensor


def raw(vak, shown, cijfer, datum, weging=2, label=False, voldoende=True):
    item = {
        "$type": "resultaten.RGeldendVoortgangsdossierResultaat",
        "links": [{"id": hash(datum)}],
        "additionalObjects": {"vaknaam": vak, "resultaatkolom": "1"},
        "cijfer": cijfer, "isVoldoende": voldoende, "periode": 1,
        "formattedResultaat": shown, "type": "Toetskolom", "toetscode": "SO",
        "omschrijving": f"SO {vak}", "weging": weging,
        "datumInvoerEerstePoging": datum, "isLabel": label, "isCijfer": True, "herkansing": "Geen",
    }
    if label:
        item["label"] = shown
    return item


ITEMS = [
    raw("Frans", "+", 1.0, "2026-09-29T20:10:27", weging=0, label=True),
    raw("Nederlands", "5,8", 5.8, "2026-10-16T15:21:04"),
    raw("Latijn", "10,0", 10.0, "2026-10-14T11:45:40"),
    raw("wiskunde", "4,2", 4.2, "2026-10-14T16:39:01", voldoende=False),
    raw("Engels", "", None, "2026-10-20T10:00:00"),  # nog geen resultaat
]


def test_params_match_the_pupil_portal():
    params = grade_params()
    assert [v for k, v in params if k == "type"] == [
        "Toetskolom", "DeeltoetsKolom", "Werkstukcijferkolom", "Advieskolom"]
    assert ("additional", "vaknaam") in params
    assert ("sort", "desc-geldendResultaatCijferInvoer") in params


def test_normalized_newest_first_labels_have_no_number():
    grades = normalize_grades(ITEMS)
    assert [g["vak"] for g in grades] == ["Nederlands", "wiskunde", "Latijn", "Frans"]
    frans = grades[-1]
    assert frans["resultaat"] == "+" and frans["cijfer"] is None and frans["weging"] == 0
    assert grades[1]["voldoende"] is False and grades[1]["cijfer"] == 4.2


def test_sensor_shows_latest_and_lists_recent():
    sensor = object.__new__(SomtodayLatestGradeSensor)
    sensor.student = "a"
    sensor.coordinator = SimpleNamespace(data={"grades_by_student": {"a": normalize_grades(ITEMS)}})
    assert sensor.native_value == "5,8"
    attributes = sensor.extra_state_attributes
    assert attributes["vak"] == "Nederlands" and attributes["weging"] == 2
    assert len(attributes["cijfers"]) == 4
    assert "cijfers" in SomtodayLatestGradeSensor._unrecorded_attributes


def test_sensor_without_grades_yet():
    sensor = object.__new__(SomtodayLatestGradeSensor)
    sensor.student = "a"
    sensor.coordinator = SimpleNamespace(data={"grades_by_student": {"a": []}})
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {"cijfers": []}
