from datetime import datetime

from custom_components.somtoday.models import school_day_bounds


def test_school_day_ignores_breaks_and_cancelled_items():
    appointments = [
        {
            "beginDatumTijd": "2026-09-10T09:20:00+02:00",
            "eindDatumTijd": "2026-09-10T10:10:00+02:00",
            "afspraakStatus": "ACTIEF",
            "afspraakType": {"naam": "Les", "categorie": "Rooster", "activiteit": "Verplicht"},
        },
        {
            "beginDatumTijd": "2026-09-10T10:10:00+02:00",
            "eindDatumTijd": "2026-09-10T10:25:00+02:00",
            "afspraakStatus": "ACTIEF",
            "titel": "Pauze",
            "afspraakType": {"naam": "Pauze", "categorie": "Rooster"},
        },
        {
            "beginDatumTijd": "2026-09-10T14:10:00+02:00",
            "eindDatumTijd": "2026-09-10T15:00:00+02:00",
            "afspraakStatus": "GEANNULEERD",
            "afspraakType": {"naam": "Les", "categorie": "Rooster", "activiteit": "Verplicht"},
        },
        {
            "beginDatumTijd": "2026-09-10T13:20:00+02:00",
            "eindDatumTijd": "2026-09-10T14:10:00+02:00",
            "afspraakStatus": "ACTIEF",
            "afspraakType": {"naam": "Les", "categorie": "Rooster", "activiteit": "Verplicht"},
        },
    ]

    result = school_day_bounds(appointments)

    assert result["2026-09-10"] == (
        datetime.fromisoformat("2026-09-10T09:20:00+02:00"),
        datetime.fromisoformat("2026-09-10T14:10:00+02:00"),
    )
