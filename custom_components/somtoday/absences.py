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

Nothing here publishes a partial snapshot. A response that is not an overview,
a bucket of the wrong type or a row without a usable date raises ValueError, so
the caller reports the source as unavailable instead of a lower count. A valid
overview whose buckets are empty is accepted and counts zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

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
    """Parse the first date present, in local time; an unusable one raises.

    The absence buckets carry an offset while the lesson buckets carry naive
    local times. Both are converted to Home Assistant's time zone so they can
    be compared and sorted, and a naive value is read as local school time.
    """
    for key in keys:
        value = source.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise ValueError("Registration date is not text")
        return dt_util.as_local(parse_datetime(value))
    return None


def _text(source: dict[str, Any], *keys: str) -> str:
    """Report the school's own wording; never translate or classify it."""
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _bucket(overview: Any, key: str) -> list[dict[str, Any]]:
    """Return one bucket, refusing anything that is not an overview.

    A missing or null bucket is empty. Any other non-list value, and any row
    that is not an object, makes the whole overview unusable.
    """
    if not isinstance(overview, dict) or not any(
        source_key in overview for source_key, _ in ABSENCE_BUCKETS + LESSON_BUCKETS
    ):
        raise ValueError("Not a registration overview")
    value = overview.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Unexpected registration bucket")
    return value


def _start(item: dict[str, Any], *keys: str) -> datetime:
    start = _moment(item, *keys)
    if start is None:
        # Without a start the entry cannot be placed on a timeline. Dropping it
        # would lower every count derived from it, so the overview is refused.
        raise ValueError("Registration without a usable start")
    return start


def normalize_absence_registrations(overview: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the absence buckets into one timeline, newest first."""
    values: list[dict[str, Any]] = []
    for source_key, name in ABSENCE_BUCKETS:
        for item in _bucket(overview, source_key):
            start = _start(item, "begin", "beginDatumTijd")
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
            start = _start(item, "beginDatumTijd", "begin")
            subject = item.get("vak")
            subject = subject if isinstance(subject, dict) else {}
            hour = item.get("beginLesuur")
            values.append(
                {
                    "category": name,
                    "start": start,
                    "subject": _text(subject, "naam", "afkorting") or "Onbekend vak",
                    "lesson_hour": hour if type(hour) is int else None,
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


def registration_snapshot(overview: Any) -> dict[str, list[dict[str, Any]]]:
    """Validate and normalize the whole overview before any of it is published."""
    return {
        "absences": normalize_absence_registrations(overview),
        "lessons": normalize_lesson_registrations(overview),
    }


def outstanding_measures(items: list[dict[str, Any]]) -> int:
    """Measures not yet complied with (`nagekomen: false`).

    A measure without a boolean flag makes the count unknown rather than lower,
    so it raises and the caller reports the count as unavailable.
    """
    if not isinstance(items, list) or not all(
        isinstance(item, dict) and isinstance(item.get("nagekomen"), bool)
        for item in items
    ):
        raise ValueError("Unexpected measure list")
    return sum(1 for item in items if item["nagekomen"] is False)
