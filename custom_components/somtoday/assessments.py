"""Normalize Somtoday study-guide assessment assignments."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .export import item_id
from .models import parse_datetime

ASSESSMENT_TYPES = {"TOETS", "GROTE_TOETS"}
ASSESSMENT_TYPE_LABELS = {
    "TOETS": "Toets",
    "GROTE_TOETS": "Grote toets",
}


def _subject(item: dict[str, Any]) -> str:
    group = item.get("lesgroep") or (item.get("additionalObjects") or {}).get(
        "lesgroep"
    ) or {}
    subject = (group.get("vak") or {}).get("naam")
    return str(subject or "Onbekend vak")


def _made(item: dict[str, Any]) -> bool | None:
    additional = item.get("additionalObjects") or {}
    direct = additional.get("huiswerkgemaakt")
    if isinstance(direct, bool):
        return direct
    wrapper = additional.get("swigemaaktVinkjes") or {}
    values = wrapper.get("items") if isinstance(wrapper, dict) else None
    if isinstance(values, list):
        made = [value.get("gemaakt") for value in values if isinstance(value, dict)]
        if any(isinstance(value, bool) for value in made):
            return any(value is True for value in made)
    return None


def _matching_lesson(
    appointments: list[dict[str, Any]], due: datetime, subject: str
) -> tuple[datetime, datetime] | None:
    """Use lesson bounds only for an exact time and subject match."""
    normalized_subject = subject.strip().casefold()
    for appointment in appointments:
        try:
            begin = parse_datetime(appointment["beginDatumTijd"])
            end = parse_datetime(appointment["eindDatumTijd"])
        except (KeyError, TypeError, ValueError):
            continue
        appointment_subject = str(
            (((appointment.get("additionalObjects") or {}).get("vak") or {}).get("naam"))
            or ""
        ).strip().casefold()
        if begin == due and appointment_subject == normalized_subject and end > begin:
            return begin, end
    return None


def normalize_assessments(
    assignments: list[dict[str, Any]],
    appointments: list[dict[str, Any]],
    first_day: date,
    last_day: date,
) -> list[dict[str, Any]]:
    """Return dated and undated tests without inferring missing dates."""
    result = []
    seen = set()
    for assignment in assignments:
        identifier = item_id(assignment)
        if not identifier or identifier in seen:
            continue
        study_item = assignment.get("studiewijzerItem") or {}
        kind = str(study_item.get("huiswerkType") or "").upper()
        if kind not in ASSESSMENT_TYPES:
            continue
        seen.add(identifier)
        source = str(assignment.get("_somtoday_assignment_kind") or "")
        raw_due = assignment.get("datumTijd")
        due = None
        if source != "week" and raw_due:
            try:
                due = parse_datetime(str(raw_due))
            except ValueError:
                due = None
        subject = _subject(assignment)
        topic = str(study_item.get("onderwerp") or "").strip()
        description = str(study_item.get("omschrijving") or "").strip()
        value = {
            "id": identifier,
            "type": kind,
            "type_label": ASSESSMENT_TYPE_LABELS[kind],
            "subject": subject,
            "topic": topic,
            "description": description,
            "made": _made(assignment),
            "source": source,
            "start": None,
            "end": None,
            "date_known": due is not None,
            "all_day": True,
        }
        if due is None:
            result.append(value)
            continue
        day = due.date()
        if day < first_day or day >= last_day:
            continue
        lesson = _matching_lesson(appointments, due, subject)
        if source == "appointment" and lesson is not None:
            value.update(start=lesson[0], end=lesson[1], all_day=False)
        else:
            value.update(start=day, end=day + timedelta(days=1))
        result.append(value)
    return sorted(
        result,
        key=lambda value: (
            value["start"] is None,
            value["start"].isoformat() if value["start"] is not None else "",
            value["subject"].casefold(),
        ),
    )


def assessment_summary(value: dict[str, Any]) -> str:
    """Build a concise human-readable assessment title."""
    parts = [value["subject"], value["type_label"]]
    if value.get("topic"):
        parts.append(value["topic"])
    return " · ".join(parts)


def assessment_description(value: dict[str, Any]) -> str:
    """Build a useful calendar description without internal identifiers."""
    parts = []
    if value.get("description"):
        parts.append(value["description"])
    if value.get("made") is not None:
        parts.append("Afgerond: " + ("ja" if value["made"] else "nee"))
    return "\n\n".join(parts)
