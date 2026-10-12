from copy import deepcopy
from types import SimpleNamespace

from custom_components.somtoday.appointment_debug import appointment_debug_rows
from custom_components.somtoday.calendar import SomtodayCalendar


def test_original_type_and_colors_are_visible_without_source_secrets():
    item = {
        "titel": "proefwerk Nederlands ",
        "beginDatumTijd": "2026-10-12T08:30:00+02:00",
        "eindDatumTijd": "2026-10-12T09:20:00+02:00",
        "afspraakStatus": "ACTIEF",
        "kleur": "#123456",
        "afspraakType": {
            "naam": "Proefwerk", "categorie": "Toets", "activiteit": "Optioneel",
            "standaardKleur": "#00ff00", "links": [{"id": "SECRET_ID"}],
            "token": "SECRET_TOKEN",
        },
        "omschrijving": "SECRET_DESCRIPTION",
        "additionalObjects": {"leerlingen": {"items": [{"naam": "SECRET_STUDENT"}]}},
    }
    original = deepcopy(item)
    student = {"links": [{"id": "a"}]}
    coordinator = SimpleNamespace(data={"appointments_by_student": {"a": [item]}})
    entity = SomtodayCalendar(coordinator, SimpleNamespace(entry_id="e"), student)
    attributes = entity.extra_state_attributes
    row = attributes["appointment_debug"][0]
    assert row["title"] == "proefwerk Nederlands "
    assert row["afspraak_type"] == {"naam": "Proefwerk", "categorie": "Toets", "activiteit": "Optioneel"}
    assert row["color_fields"] == {"appointment.kleur": "#123456", "afspraakType.standaardKleur": "#00ff00"}
    assert "SECRET" not in str(attributes)
    assert "links" in row["afspraak_type_available_fields"]
    assert attributes["appointment_debug_total"] == 1
    assert attributes["appointment_debug_truncated"] is False
    assert item == original


def test_missing_type_and_colors_are_not_guessed_and_rows_are_bounded():
    rows = appointment_debug_rows([{"titel": "proefwerk Nederlands"}] * 101)
    assert len(rows) == 100
    assert rows[0]["afspraak_type"] == {}
    assert rows[0]["color_fields"] == {}
    assert rows[0]["afspraak_type_available_fields"] == []
    assert appointment_debug_rows([{"afspraakType": "unexpected"}])[0]["afspraak_type"] == {}


def test_metadata_stays_with_the_selected_child():
    coordinator = SimpleNamespace(data={"appointments_by_student": {
        "a": [{"titel": "Child A"}], "b": [{"titel": "Child B"}]}})
    entity = SomtodayCalendar(coordinator, SimpleNamespace(entry_id="e"), {"links": [{"id": "b"}]})
    assert entity.extra_state_attributes["appointment_debug"][0]["title"] == "Child B"
