"""Absence overview: reports and measures, as the pupil portal shows them.

The "Afwezigheid" page is fed by more than one source, so a single endpoint
cannot reproduce it:

* ``/rest/v1/absentiemeldingen`` holds absence reports (reason, period, remark).
* ``/rest/v1/maatregeltoekenningen`` holds measures such as "Huiswerk niet in
  orde" or being removed from a lesson. These never appear in the absence
  reports, which is why a reports-only implementation looks incomplete to a
  parent who sees both in the portal.
* ``/rest/v1/waarnemingen`` holds per-lesson presence. It is deliberately not
  used here: on the verified account it returned 1043 rows while the
  ``Content-Range`` total claimed 200, so a paginated read cannot be proven
  complete, and its non-present rows duplicated the absence reports anyway.

``geoorloofd`` is bookkeeping, never a verdict. The flag belongs to the
configured reason, and schools pick their own. On the verified school "Is er uit
gestuurd" (sent out of the lesson) is stored as ``geoorloofd: true`` while
"Terugkomklas" (detention) is ``false``. The flag therefore answers whether the
school books the absence as authorised and says nothing about fault. Reason and
flag are exposed side by side and never combined into a judgement.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .export import item_id
from .models import parse_datetime


def school_year_start(today: date) -> date:
    """Dutch school years begin in August; before August the previous one still runs."""
    return date(today.year if today.month >= 8 else today.year - 1, 8, 1)


def _flag(value: Any) -> bool | None:
    """An absent flag is unknown, which is not the same as false."""
    return value if isinstance(value, bool) else None


def _moment(item: dict[str, Any], key: str) -> datetime | None:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_datetime(value)
    except (TypeError, ValueError):
        return None


def _owned_by(item: dict[str, Any], student_id: str) -> bool:
    """A guardian account lists every child in one response."""
    owner = item.get("leerling")
    if not isinstance(owner, dict):
        return True
    owner_id = item_id(owner)
    return not owner_id or owner_id == student_id


def _text(source: dict[str, Any], *keys: str) -> str:
    """Report the school's own wording; never translate or classify it."""
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_absences(
    items: list[dict[str, Any]], student_id: str, since: date
) -> list[dict[str, Any]]:
    """Return this pupil's absence reports, newest first."""
    values: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not _owned_by(item, student_id):
            continue
        start = _moment(item, "beginDatumTijd")
        if start is None or start.date() < since:
            # A report without a usable start cannot be placed on a timeline and
            # would silently distort every count derived from it.
            continue
        reason = item.get("absentieReden")
        reason = reason if isinstance(reason, dict) else {}
        values.append(
            {
                "id": item_id(item),
                "start": start,
                "end": _moment(item, "eindDatumTijd"),
                "reason": _text(reason, "omschrijving", "afkorting") or "Onbekend",
                "authorised": _flag(reason.get("geoorloofd")),
                "handled": _flag(item.get("afgehandeld")),
                "remark": _text(item, "opmerkingen"),
            }
        )
    values.sort(key=lambda value: value["start"], reverse=True)
    return values


def normalize_measures(
    items: list[dict[str, Any]], student_id: str, since: date
) -> list[dict[str, Any]]:
    """Return this pupil's measures, newest first.

    ``nagekomen`` states whether the measure has been complied with. An
    outstanding measure is the part a parent can still act on, so it is kept as
    a plain flag rather than folded into the absence counts.
    """
    values: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not _owned_by(item, student_id):
            continue
        moment = _moment(item, "maatregelDatum")
        if moment is None or moment.date() < since:
            continue
        measure = item.get("maatregel")
        measure = measure if isinstance(measure, dict) else {}
        values.append(
            {
                "id": item_id(item),
                "date": moment.date(),
                "label": _text(measure, "omschrijving", "naam") or "Onbekend",
                "complied": _flag(item.get("nagekomen")),
                "automatic": _flag(item.get("automatischToegekend")),
            }
        )
    values.sort(key=lambda value: value["date"], reverse=True)
    return values


def absence_counts(values: list[dict[str, Any]]) -> dict[str, int]:
    """Count only what the source states; an unknown flag counts as neither."""
    return {
        "total": len(values),
        "authorised": sum(value["authorised"] is True for value in values),
        "unauthorised": sum(value["authorised"] is False for value in values),
        "open": sum(value["handled"] is False for value in values),
    }


def measure_counts(values: list[dict[str, Any]]) -> dict[str, int]:
    """Outstanding measures are the actionable number, so they are counted apart."""
    return {
        "total": len(values),
        "outstanding": sum(value["complied"] is False for value in values),
    }


def label_counts(values: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Break down by the school's own wording instead of guessing categories.

    A school calling lateness "Te laat in de les" and another calling it "Te
    laat" would both be mangled by pattern matching, so labels are passed
    through unchanged and the consumer decides what matters.
    """
    counts: dict[str, int] = {}
    for value in values:
        counts[value[key]] = counts.get(value[key], 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))
