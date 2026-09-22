"""Absence overview, read the way the pupil portal reads it.

`/rest/v1/leerlingen/{id}/registratieOverzicht?periode=SCHOOLJAAR` is the single
call the portal makes for its "Afwezigheid" page. It answers with one object
already grouped into the buckets shown there, scoped to the running school year.

Two shapes appear inside it:

* Absence buckets (`afwezigWaarnemingen`, `ongeoorloofdAfwezig`,
  `geoorloofdAfwezig`, `teLaat`, `verwijderd`) hold registrations with a period,
  a reason, `geoorloofd` and `afgehandeld`.
* Lesson buckets (`huiswerkNietGemaakt`, `materiaalNietInOrde`) hold the lesson
  the registration was made in, with subject, lesson hour and room.

The lesson buckets are the reason this endpoint is used instead of the list
endpoints. `/rest/v1/absentiemeldingen` carries only the absence side, and
`/rest/v1/waarnemingen` held nothing but Aanwezig and Afwezig across 1045 rows
on the verified account, so "Materiaal niet in orde" is not reachable there at
all. A parent looking at the portal sees it, and an overview without it looks
broken.

`geoorloofd` is bookkeeping, never a verdict. It belongs to the configured
reason and schools configure their own. On the verified school "Is er uit
gestuurd" is stored as `geoorloofd: true` while "Terugkomklas" is `false`, so
the flag says how the school books the absence and nothing about fault. Reason
and flag are exposed side by side and never combined into a judgement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .export import item_id
from .models import parse_datetime

ABSENCE_BUCKETS: tuple[tuple[str, str], ...] = (
    ("ongeoorloofdAfwezig", "ongeoorloofd_afwezig"),
    ("geoorloofdAfwezig", "geoorloofd_afwezig"),
    ("teLaat", "te_laat"),
    ("verwijderd", "verwijderd"),
    ("afwezigWaarnemingen", "afwezig_waarnemingen"),
)

LESSON_BUCKETS: tuple[tuple[str, str], ...] = (
    ("huiswerkNietGemaakt", "huiswerk_niet_gemaakt"),
    ("materiaalNietInOrde", "materiaal_niet_in_orde"),
)


def _flag(value: Any) -> bool | None:
    """An absent flag is unknown, which is not the same as false."""
    return value if isinstance(value, bool) else None


def _moment(source: dict[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            try:
                return parse_datetime(value)
            except (TypeError, ValueError):
                return None
    return None


def _text(source: dict[str, Any], *keys: str) -> str:
    """Report the school's own wording; never translate or classify it."""
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _bucket(overview: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = overview.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def normalize_absence_registrations(overview: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the absence buckets into one timeline, newest first."""
    values: list[dict[str, Any]] = []
    for source_key, name in ABSENCE_BUCKETS:
        for item in _bucket(overview, source_key):
            start = _moment(item, "begin", "beginDatumTijd")
            if start is None:
                # Without a start the entry cannot be placed on a timeline and
                # would silently distort every count derived from it.
                continue
            values.append(
                {
                    "category": name,
                    "start": start,
                    "end": _moment(item, "eind", "eindDatumTijd"),
                    "reason": _text(item, "omschrijving") or "Onbekend",
                    "authorised": _flag(item.get("geoorloofd")),
                    "handled": _flag(item.get("afgehandeld")),
                    "id": str(item.get("registratieId") or item_id(item) or ""),
                }
            )
    values.sort(key=lambda value: value["start"], reverse=True)
    return values


def normalize_lesson_registrations(overview: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the lesson buckets, newest first, keeping subject and lesson hour.

    These entries describe the lesson a registration was made in, not an
    absence, so the subject and the lesson hour are the useful part: "Duits,
    Friday, third hour" is what the portal shows and what a parent recognises.
    """
    values: list[dict[str, Any]] = []
    for source_key, name in LESSON_BUCKETS:
        for item in _bucket(overview, source_key):
            start = _moment(item, "beginDatumTijd", "begin")
            if start is None:
                continue
            subject = item.get("vak")
            subject = subject if isinstance(subject, dict) else {}
            values.append(
                {
                    "category": name,
                    "start": start,
                    "subject": _text(subject, "naam", "afkorting") or "Onbekend vak",
                    "lesson_hour": item.get("beginLesuur"),
                    "location": _text(item, "locatie"),
                    "id": str(item.get("uniqueIdentifier") or item_id(item) or ""),
                }
            )
    values.sort(key=lambda value: value["start"], reverse=True)
    return values


def category_counts(values: list[dict[str, Any]], names: tuple[str, ...]) -> dict[str, int]:
    """Count per portal bucket, including the buckets that are empty.

    An empty bucket is reported as zero on purpose: "no lates this year" is a
    useful answer, and leaving the key out would make a template fall back to
    an attribute that does not exist.
    """
    counts = {name: 0 for name in names}
    for value in values:
        if value["category"] in counts:
            counts[value["category"]] += 1
    return counts


def outstanding_measures(items: list[dict[str, Any]]) -> int:
    """Measures not yet complied with; an unknown flag is not counted as open."""
    return sum(
        1
        for item in items
        if isinstance(item, dict) and item.get("nagekomen") is False
    )
