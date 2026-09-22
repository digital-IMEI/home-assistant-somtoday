"""Pure parsing helpers for Somtoday schedule data."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any


def parse_datetime(value: str) -> datetime:
    """Parse an ISO datetime returned by Somtoday."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_active_school_appointment(item: dict[str, Any]) -> bool:
    """Return whether a visible active appointment counts towards the school day."""
    if str(item.get("afspraakStatus", "ACTIEF")).upper() != "ACTIEF":
        return False
    appointment_type = item.get("afspraakType") or {}
    name = str(appointment_type.get("naam", "")).strip().casefold()
    title = str(item.get("titel", "")).strip().casefold()
    subject = str(((item.get("additionalObjects") or {}).get("vak") or {}).get("naam", "")).strip().casefold()
    if any(value in {"pauze", "break"} for value in (name, title, subject)):
        return False
    # Somtoday displays some valid timetable entries (for example study or a
    # test period) with another category/activity than Rooster/Verplicht. The
    # schedule calendar already exposes every active appointment, so applying
    # a second classification filter here can incorrectly shorten a school day.
    return True


def school_day_appointments(appointments, options=None):
    """Apply per-child name exclusions only to school-day calculations."""
    options = options or {}
    excluded = [line.strip().casefold() for line in options.get("day_excluded_names", "").splitlines() if line.strip()]
    contains = options.get("day_exclusion_match", "exact") == "contains"
    result = []
    for item in appointments:
        subject = ((item.get("additionalObjects") or {}).get("vak") or {}).get("naam")
        names = [str(value or "").strip().casefold() for value in (subject, item.get("titel"))]
        if any(term in name if contains else term == name for term in excluded for name in names):
            continue
        result.append(item)
    return result


def school_day_bounds(
    appointments: list[dict[str, Any]],
) -> dict[str, tuple[datetime, datetime]]:
    """Calculate first start and last end per local calendar date."""
    grouped: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for item in appointments:
        if not is_active_school_appointment(item):
            continue
        try:
            start = parse_datetime(item["beginDatumTijd"])
            end = parse_datetime(item["eindDatumTijd"])
        except (KeyError, TypeError, ValueError):
            continue
        grouped[start.date().isoformat()].append((start, end))
    return {
        day: (min(pair[0] for pair in times), max(pair[1] for pair in times))
        for day, times in grouped.items()
    }


def automatic_day_titles(appointments):
    """Use a shared full source title, never infer whether a day is special."""
    grouped = defaultdict(list)
    for item in appointments:
        if not is_active_school_appointment(item):
            continue
        try:
            day = parse_datetime(item["beginDatumTijd"]).date().isoformat()
        except (KeyError, TypeError, ValueError):
            continue
        grouped[day].append(str(item.get("titel") or "").strip())
    result = {}
    for day, titles in grouped.items():
        if not titles or not titles[0] or len(set(titles)) != 1:
            continue
        title = titles[0]
        if "_" in title:
            title = title.split("_", 1)[1]
        title = " ".join(title.replace("_", " ").split())
        if title:
            result[day] = title
    return result
