"""Pure calendar export planning; no credentials or provider-specific API calls."""

from datetime import date, timedelta

from hashlib import sha256

from .const import (
    HOLIDAY_MODE_DAILY,
    HOLIDAY_MODE_FULL_WEEKS,
    HOLIDAY_MODE_SCHOOL_DAYS,
    HOLIDAY_MODES,
)
from .models import automatic_day_titles, is_active_school_appointment, parse_datetime, school_day_bounds, school_day_appointments


def item_id(item):
    return str((item.get("links") or [{}])[0].get("id", ""))


def select_student(appointments, students, selected):
    """Fail closed if a multi-student account lacks appointment ownership."""
    ids = {item_id(s) for s in students}
    if not selected and len(ids) == 1:
        selected = next(iter(ids))
    if not selected or selected not in ids:
        raise ValueError("Select a student in Somtoday options")
    if len(ids) == 1:
        return selected, appointments
    result = []
    for item in appointments:
        pupils = (item.get("additionalObjects") or {}).get("leerlingen")
        if isinstance(pupils, dict):
            pupils = pupils.get("items")
        if not isinstance(pupils, list) or not pupils:
            raise ValueError("Cannot determine appointment ownership; synchronization paused")
        if selected in {item_id(p) for p in pupils}:
            result.append(item)
    return selected, result


def desired_events(appointments, options, student, start, end):
    """Build stable keys; source changes alter content rather than identity."""
    result = {}
    active = []
    for item in appointments:
        if not is_active_school_appointment(item):
            continue
        begin = parse_datetime(item["beginDatumTijd"])
        finish = parse_datetime(item["eindDatumTijd"])
        if begin.tzinfo is None or finish.tzinfo is None or finish <= begin:
            raise ValueError("Invalid appointment time; synchronization paused")
        if start <= begin < end:
            active.append(item)
    if target := options.get("day_calendar"):
        day_items = school_day_appointments(active, options)
        titles = automatic_day_titles(day_items) if options.get("automatic_day_title", False) else {}
        for day, (begin, finish) in school_day_bounds(day_items).items():
            result[(target, f"{student}:day:{day}")] = {
                "dtstart": begin, "dtend": finish,
                "summary": titles.get(day, options.get("day_title", "School")),
                "location": "",
            }
    if target := options.get("lesson_calendar"):
        for item in active:
            identifier = item_id(item)
            if not identifier:
                raise ValueError("Appointment has no stable ID; synchronization paused")
            subject = ((item.get("additionalObjects") or {}).get("vak") or {}).get("naam")
            result[(target, f"{student}:lesson:{identifier}")] = {
                "dtstart": parse_datetime(item["beginDatumTijd"]),
                "dtend": parse_datetime(item["eindDatumTijd"]),
                "summary": options.get("lesson_prefix", "") + str(subject or item.get("titel") or "Lesson"),
                "location": str(item.get("locatie") or ""),
                "description": str(item.get("omschrijving") or "") if options.get("lesson_homework") else "",
            }
    return result


def desired_holiday_events(holidays, options, student, start, end):
    """Build all-day events using the selected holiday layout."""
    target = options.get("holiday_calendar")
    if not target:
        return {}
    mode = options.get("holiday_mode", HOLIDAY_MODE_SCHOOL_DAYS)
    if mode not in HOLIDAY_MODES:
        raise ValueError("Invalid holiday event layout; synchronization paused")
    result = {}
    first_day = start.date()
    last_day = end.date()
    for item in holidays:
        identifier = item_id(item)
        if not identifier:
            raise ValueError("Holiday has no stable ID; synchronization paused")
        try:
            begin = date.fromisoformat(str(item["beginDatum"])[:10])
            inclusive_end = date.fromisoformat(str(item["eindDatum"])[:10])
        except (KeyError, TypeError, ValueError) as err:
            raise ValueError("Invalid holiday range; synchronization paused") from err
        if inclusive_end < begin:
            raise ValueError("Invalid holiday range; synchronization paused")
        if inclusive_end < first_day or begin >= last_day:
            continue
        name = str(item.get("naam") or item.get("titel") or "Holiday")
        summary = options.get("holiday_title", "{student} · {holiday}").replace(
            "{holiday}", name
        )
        if mode == HOLIDAY_MODE_DAILY:
            current = begin
            while current <= inclusive_end:
                result[(target, f"{student}:holiday:{identifier}:{current}")] = {
                    "dtstart": current,
                    "dtend": current + timedelta(days=1),
                    "summary": summary,
                    "location": "",
                }
                current += timedelta(days=1)
            continue

        event_begin = begin
        event_end = inclusive_end
        if mode == HOLIDAY_MODE_FULL_WEEKS:
            # Expand to the Saturday before and Sunday after the published range.
            event_begin -= timedelta(days=(event_begin.weekday() - 5) % 7)
            event_end += timedelta(days=(6 - event_end.weekday()) % 7)
        result[(target, f"{student}:holiday:{identifier}")] = {
            "dtstart": event_begin,
            # HA calendar actions use an exclusive end date for all-day events.
            "dtend": event_end + timedelta(days=1),
            "summary": summary,
            "location": "",
        }
    return result


def desired_assessment_events(assessments, options, student):
    """Build export events only for assessments with a known date."""
    target = options.get("assessment_calendar")
    if not target:
        return {}
    result = {}
    template = options.get(
        "assessment_title", "{student} · {subject} · {type}"
    )
    for value in assessments:
        if value.get("start") is None or value.get("end") is None:
            continue
        summary = template
        for field in ("subject", "type_label", "topic"):
            placeholder = "type" if field == "type_label" else field
            summary = summary.replace("{" + placeholder + "}", str(value.get(field) or ""))
        # Avoid an empty separator when an optional placeholder (such as topic)
        # has no value in Somtoday.
        summary = " · ".join(
            part.strip() for part in summary.split("·") if part.strip()
        )
        summary = summary.strip().strip("·:- ") or "Toets"
        result[(target, f"{student}:assessment:{value['id']}")] = {
            "dtstart": value["start"],
            "dtend": value["end"],
            "summary": summary,
            "location": "",
        }
    return result


def marker(entry_id, key):
    return scope_marker(entry_id, ":".join(key.split(":")[:2])) + sha256(key.encode()).hexdigest() + "]"


def scope_marker(entry_id, scope):
    return f"[somtoday:{entry_id}:{sha256(scope.encode()).hexdigest()}:"


def same_event(event, desired):
    return (event.start == desired["dtstart"] and event.end == desired["dtend"]
            and event.summary == desired["summary"]
            and (event.location or "") == desired["location"]
            and (event.description or "").partition("\n\n")[2] == desired.get("description", ""))
