"""Pure calendar export planning; no credentials or provider-specific API calls."""

from hashlib import sha256

from .models import is_active_school_appointment, parse_datetime, school_day_bounds


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
        for day, (begin, finish) in school_day_bounds(active).items():
            result[(target, f"{student}:day:{day}")] = {
                "dtstart": begin, "dtend": finish,
                "summary": options.get("day_title", "School"),
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
            }
    return result


def marker(entry_id, key):
    return scope_marker(entry_id, ":".join(key.split(":")[:2])) + sha256(key.encode()).hexdigest() + "]"


def scope_marker(entry_id, scope):
    return f"[somtoday:{entry_id}:{sha256(scope.encode()).hexdigest()}:"


def same_event(event, desired):
    return (event.start == desired["dtstart"] and event.end == desired["dtend"]
            and event.summary == desired["summary"]
            and (event.location or "") == desired["location"])
