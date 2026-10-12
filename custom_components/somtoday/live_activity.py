"""Pure timetable-to-Live-Activity projection; no network or Home Assistant I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from .models import is_active_school_appointment, parse_datetime


@dataclass(frozen=True)
class Lesson:
    start: datetime
    end: datetime
    subject: str
    room: str


@dataclass(frozen=True)
class ActivityView:
    phase: str
    message: str | None
    room: str
    next_change: datetime


def activity_view(appointments: list[dict], now: datetime, language="nl", *, include_next_room=False) -> ActivityView:
    """Render today's active lessons and the next exact display boundary.

    Breaks/cancellations do not become a destination. Use the same appointment
    eligibility as the school-day calendar, but retain all actual lesson names.
    Local dates matter: the API may return UTC or a different offset.
    """
    en = language == "en"
    midnight = datetime.combine(now.date() + timedelta(days=1), time.min, now.tzinfo)
    lessons = []
    for item in appointments:
        if not is_active_school_appointment(item):
            continue
        try:
            start = parse_datetime(item["beginDatumTijd"])
            end = parse_datetime(item["eindDatumTijd"])
            if start.tzinfo is None or end.tzinfo is None or end <= start:
                continue
            start, end = start.astimezone(now.tzinfo), end.astimezone(now.tzinfo)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if start.date() != now.date():
            continue
        subject = ((item.get("additionalObjects") or {}).get("vak") or {}).get("naam")
        lessons.append(Lesson(
            start, end, str(subject or item.get("titel") or "Somtoday"),
            str(item.get("locatie") or "").strip(),
        ))
    lessons.sort(key=lambda lesson: (lesson.start, lesson.end, lesson.subject))
    if not lessons:
        return ActivityView("idle", None, "", midnight)

    first = lessons[0].start
    last = max(lesson.end for lesson in lessons)
    lead = first - timedelta(minutes=15)
    dismissal = last + timedelta(minutes=10)
    boundaries = [midnight, lead, dismissal]
    for lesson in lessons:
        boundaries.extend((lesson.start, lesson.end, lesson.end - timedelta(minutes=5)))
    next_change = min(value for value in boundaries if value > now)
    if now < lead or now >= dismissal:
        return ActivityView("idle", None, "", next_change)
    if now >= last:
        return ActivityView("finished", "Done for today" if en else "Klaar voor vandaag", "✓", next_change)

    current = next((lesson for lesson in reversed(lessons) if lesson.start <= now < lesson.end), None)
    following = next((lesson for lesson in lessons if lesson.start > now), None)
    unknown = "Room unknown" if en else "Lokaal onbekend"
    critical = following.room if following and following.room else "—"
    if current:
        current_line = (
            f"{'Now' if en else 'Nu'} {current.subject} · {current.room or unknown} "
            f"{'until' if en else 'tot'} {current.end:%H:%M}"
        )
        if following:
            next_line = f"{'Next' if en else 'Hierna'} {following.subject} · {following.start:%H:%M}"
            leaving = now >= current.end - timedelta(minutes=5)
            if leaving or include_next_room:
                next_line += f" · {following.room or unknown}"
            message = f"{next_line}\n{current_line}" if leaving else f"{current_line}\n{next_line}"
            return ActivityView("leaving" if leaving else "lesson", message, critical, next_change)
        return ActivityView("lesson", f"{current_line}\n{'Last lesson today' if en else 'Laatste les vandaag'}", "—", next_change)

    # Before school and during breaks, the first future lesson is the destination.
    label = ("First lesson" if en else "Eerste les") if now < first else ("Break · next" if en else "Pauze · hierna")
    message = f"{label} {following.subject} · {following.start:%H:%M}\n{'Room' if en else 'Lokaal'} {following.room or unknown}"
    return ActivityView("before_school" if now < first else "break", message, critical, next_change)
