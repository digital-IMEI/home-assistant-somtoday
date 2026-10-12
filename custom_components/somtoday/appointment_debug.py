"""Limited source metadata for investigating appointment classification."""

TYPE_FIELDS = ("naam", "categorie", "activiteit")
COLOR_FIELDS = (
    "kleur", "standaardKleur", "achtergrondKleur", "tekstKleur",
    "color", "backgroundColor", "textColor",
)


def appointment_type_metadata(item):
    """Expose classification and colour fields, never source links or IDs."""
    appointment_type = item.get("afspraakType")
    if not isinstance(appointment_type, dict):
        appointment_type = {}
    result = {
        "afspraak_type": {
            field: appointment_type[field]
            for field in TYPE_FIELDS
            if isinstance(appointment_type.get(field), (str, int, bool))
        },
        "color_fields": {},
        "afspraak_type_available_fields": sorted(appointment_type),
    }
    for scope, source in (("appointment", item), ("afspraakType", appointment_type)):
        for field in COLOR_FIELDS:
            value = source.get(field)
            if isinstance(value, (str, int, bool)):
                result["color_fields"][f"{scope}.{field}"] = value
    return result


def appointment_debug_rows(items, limit=100):
    """Include identifying titles and times only in the child's local HA entity."""
    return [
        {
            "title": str(item.get("titel") or ""),
            "start": item.get("beginDatumTijd"),
            "end": item.get("eindDatumTijd"),
            "status": item.get("afspraakStatus"),
            "has_subject": bool(((item.get("additionalObjects") or {}).get("vak") or {}).get("naam")),
            **appointment_type_metadata(item),
        }
        for item in items[:limit]
    ]
