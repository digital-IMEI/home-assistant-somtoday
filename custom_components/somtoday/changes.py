"""Schedule changes (moved, room changed, cancelled) from the pupil portal.

``/rest/v1/afspraken`` returns the current timetable without any change
information, and leaves cancelled lessons out entirely. The pupil portal reads
``/rest/v1/afspraakitems/{leerling}/jaar/{jaar}/week/{week}`` instead, which
carries ``wijzigingOmschrijving`` ("De les is verplaatst (komt van wo 12:40u).")
and a status notification 4007 for a cancelled lesson. This module merges that
information into the regular appointment dicts without changing their shape.

Added keys on appointment dicts:
  ``_somtoday_change``     change text as shown in the app ("" when unchanged)
  ``_somtoday_cancelled``  True for a cancelled lesson

A cancelled lesson that is missing from ``/afspraken`` is added as a synthetic
appointment with ``afspraakStatus`` VERVALLEN, so every existing consumer that
only accepts ACTIEF keeps ignoring it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .models import parse_datetime

SOMTODAY_TZ = ZoneInfo("Europe/Amsterdam")
CANCELLED_STATUS = "4007"
LESSON_ITEM_TYPE = "participatie.live.RAfspraakItem"


def iso_weeks(start: date, end: date) -> list[tuple[int, int]]:
    """Return the (ISO year, ISO week) pairs covering start..end inclusive."""
    weeks: list[tuple[int, int]] = []
    day = start - timedelta(days=start.weekday())
    while day <= end:
        iso = day.isocalendar()
        weeks.append((iso.year, iso.week))
        day += timedelta(days=7)
    return weeks


def _vak(item: dict[str, Any]) -> dict[str, Any]:
    vak = (item.get("additionalObjects") or {}).get("vak") or item.get("vak") or {}
    return vak if isinstance(vak, dict) else {}


def _appointment_key(item: dict[str, Any]) -> tuple[str, str] | None:
    try:
        begin = parse_datetime(item["beginDatumTijd"])
    except (KeyError, TypeError, ValueError):
        return None
    if begin.tzinfo is None:
        begin = begin.replace(tzinfo=SOMTODAY_TZ)
    afkorting = str(_vak(item).get("afkorting") or "").strip().casefold()
    if not afkorting:
        return None
    return begin.astimezone(SOMTODAY_TZ).strftime("%Y-%m-%dT%H:%M"), afkorting


def _local(value: str) -> datetime:
    """afspraakitems times have no offset; they are Dutch local time."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SOMTODAY_TZ)
    return parsed


def merge_changes(
    appointments: list[dict[str, Any]], items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return copies of ``appointments`` enriched with change information."""
    names: dict[str, str] = {}
    for source in (*appointments, *items):
        vak = _vak(source)
        afkorting = str(vak.get("afkorting") or "").strip()
        naam = str(vak.get("naam") or "").strip()
        if afkorting and naam and naam.casefold() != afkorting.casefold():
            names.setdefault(afkorting.casefold(), naam)

    changes: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        if item.get("$type") != LESSON_ITEM_TYPE:
            continue  # KWT/registration slots, not lessons
        key = _appointment_key(item)
        if key is None:
            continue
        statuses = {
            str(note.get("status"))
            for note in item.get("statusNotifications") or []
            if isinstance(note, dict)
        }
        changes[key] = {
            "change": str(item.get("wijzigingOmschrijving") or "").strip(),
            "cancelled": CANCELLED_STATUS in statuses,
            "item": item,
        }

    result: list[dict[str, Any]] = []
    matched: set[tuple[str, str]] = set()
    for appointment in appointments:
        key = _appointment_key(appointment)
        info = changes.get(key) if key else None
        if info is None:
            result.append(appointment)
            continue
        matched.add(key)
        merged = {
            **appointment,
            "_somtoday_change": info["change"],
            "_somtoday_cancelled": info["cancelled"],
        }
        if info["cancelled"]:
            merged["afspraakStatus"] = "VERVALLEN"
        result.append(merged)

    for key, info in changes.items():
        if key in matched or not info["cancelled"]:
            continue
        item = info["item"]
        try:
            begin = _local(item["beginDatumTijd"])
            end = _local(item["eindDatumTijd"])
        except (KeyError, TypeError, ValueError):
            continue
        afkorting = str(_vak(item).get("afkorting") or "").strip()
        is_test = str(item.get("afspraakItemType", "")).upper() == "ROOSTERTOETS"
        result.append({
            "links": [{"id": f"afspraakitem-{item.get('uniqueIdentifier', key[0])}"}],
            "afspraakStatus": "VERVALLEN",
            "afspraakType": {
                "categorie": "Toets" if is_test else "Rooster",
                "naam": "Toets" if is_test else "Les",
            },
            "additionalObjects": {
                "vak": {"afkorting": afkorting, "naam": names.get(afkorting.casefold(), afkorting)},
            },
            "beginDatumTijd": begin.isoformat(),
            "eindDatumTijd": end.isoformat(),
            "beginLesuur": item.get("beginLesuur"),
            "eindLesuur": item.get("eindLesuur"),
            "locatie": item.get("locatie"),
            "titel": item.get("titel"),
            "omschrijving": "",
            "_somtoday_change": info["change"],
            "_somtoday_cancelled": True,
        })
    return result
