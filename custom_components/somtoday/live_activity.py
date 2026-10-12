"""Pure timetable-to-Live-Activity projection; no network or Home Assistant I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from .models import appointment_category, is_active_school_appointment, parse_datetime


def limit_first_line(message: str, limit: int) -> str:
    """Keep the first body line bounded, preserving current room and end time."""
    def shorten(value, budget):
        return value if len(value) <= budget else value[:max(0, budget - 1)].rstrip() + "…"

    first, separator, remaining = message.partition("\n")
    if len(first) <= limit:
        return message
    parts = first.rsplit(" · ", 2)
    if len(parts) == 3 and first.startswith(("Nu: ", "Now: ")):
        prefix, subject = parts[0].split(": ", 1)
        prefix += ": "
        room = "?" if parts[1] in {"Lokaal onbekend", "Room unknown"} else parts[1]
        suffix = " · " + parts[2]
        if len(prefix) + 1 + 3 + len(room) + len(suffix) > limit:
            # On narrow English cards, keep the time and room before the label.
            suffix = " · " + parts[2].rsplit(" ", 1)[-1]
        room = shorten(room, max(1, limit - len(prefix) - len(suffix) - 4))
        suffix = " · " + room + suffix
        first = prefix + shorten(subject, max(1, limit - len(prefix) - len(suffix))) + suffix
    else:
        first = shorten(first, limit)
    return first + separator + remaining


def subject_display_name(subject: str) -> str:
    """Shorten known full subject names only in the Live Activity text."""
    label = " ".join(subject.split())
    name = label.casefold()
    aliases = {
        "wiskunde": "Wiskunde",
        "nederlands": "Nederlands",
        "engels": "Engels",
        "duits": "Duits",
        "frans": "Frans",
        "latijn": "Latijn",
        "grieks": "Grieks",
        "geschiedenis": "Geschiedenis",
        "aardrijkskunde": "Aardrijkskunde",
        "biologie": "Biologie",
        "scheikunde": "Scheikunde",
        "natuurkunde": "Natuurkunde",
        "nederlandse taal": "Nederlands",
        "nederlandse taal en literatuur": "Nederlands",
        "nederlandse taal en letterkunde": "Nederlands",
        "engelse taal": "Engels",
        "engelse taal en literatuur": "Engels",
        "engelse taal en letterkunde": "Engels",
        "duitse taal": "Duits",
        "duitse taal en literatuur": "Duits",
        "duitse taal en letterkunde": "Duits",
        "franse taal": "Frans",
        "franse taal en literatuur": "Frans",
        "franse taal en letterkunde": "Frans",
        "latijnse taal": "Latijn",
        "latijnse taal en letterkunde": "Latijn",
        "griekse taal": "Grieks",
        "griekse taal en letterkunde": "Grieks",
        "lichamelijke opvoeding": "Gym",
        "lichamelijke oefening": "Gym",
        "bewegingsonderwijs": "Gym",
        "digitale geletterdheid": "Digitaal",
        "natuur- en scheikunde": "NaSk",
        "english language and literature": "English",
        "physical education": "PE",
    }
    return aliases.get(name, label)


def subject_icon(subject: str) -> str:
    """Use readable subject icons, with a book fallback for unknown subjects."""
    name = subject.strip().casefold()
    for words, icon in (
        (("wiskunde", "mathematics", "math"), "calculator-variant"),
        (("nederlands", "dutch"), "book-open-page-variant"),
        (("engels", "english"), "translate"),
        (("duits", "german"), "translate"),
        (("frans", "french"), "translate"),
        (("latijn", "latin"), "pillar"),
        (("grieks", "greek"), "pillar"),
        (("geschiedenis", "history"), "pillar"),
        (("aardrijkskunde", "geography"), "earth"),
        (("biologie", "biology"), "leaf"),
        (("scheikunde", "chemistry"), "flask-outline"),
        (("natuurkunde", "physics"), "atom"),
        (("lichamelijke", "gym", "physical education", "sport"), "run"),
        (("digitale", "informatica", "computing", "computer"), "laptop"),
        (("muziek", "music"), "music-note"),
        (("tekenen", "beeldend", "kunst", "art"), "palette"),
        (("mentor",), "account-group"),
        (("toets", "proefwerk", "exam"), "clipboard-text-outline"),
    ):
        if any(name == word or name.startswith(word) for word in words):
            return f"mdi:{icon}"
    return "mdi:book-open-page-variant"


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
    icon: str = "mdi:school"


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
        if appointment_category(item) not in {"rooster", "toets"}:
            continue
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
        return ActivityView("finished", "Done for today" if en else "Klaar voor vandaag", "—", next_change, "mdi:check-circle-outline")

    current = next((lesson for lesson in reversed(lessons) if lesson.start <= now < lesson.end), None)
    following = next((lesson for lesson in lessons if lesson.start > now), None)
    unknown = "Room unknown" if en else "Lokaal onbekend"
    critical = following.room if following and following.room else "—"
    if current:
        current_line = (
            f"{'Now' if en else 'Nu'}: {subject_display_name(current.subject)} · "
            f"{current.room or unknown} · "
            f"{'until' if en else 'tot'} {current.end:%H:%M}"
        )
        if following:
            next_line = f"{'Next' if en else 'Hierna'}: {subject_display_name(following.subject)}"
            if following.start != current.end:
                next_line += f" · {following.start:%H:%M}"
            leaving = now >= current.end - timedelta(minutes=5)
            if include_next_room or not following.room:
                next_line += f" · {following.room or unknown}"
            message = f"{current_line}\n{next_line}"
            return ActivityView("leaving" if leaving else "lesson", message, critical, next_change, subject_icon(following.subject if leaving else current.subject))
        return ActivityView("lesson", f"{current_line}\n{'Last lesson today' if en else 'Laatste les vandaag'}", "—", next_change, subject_icon(current.subject))

    # Before school and during breaks, the first future lesson is the destination.
    if now < first:
        first_line = f"{'School starts at' if en else 'School begint om'} {following.start:%H:%M}"
        next_line = f"{'First lesson' if en else 'Eerste les'}: {subject_display_name(following.subject)}"
    else:
        first_line = f"{'Break until' if en else 'Pauze tot'} {following.start:%H:%M}"
        next_line = f"{'Next' if en else 'Hierna'}: {subject_display_name(following.subject)} · {following.start:%H:%M}"
    if include_next_room or not following.room:
        next_line += f" · {following.room or unknown}"
    return ActivityView("before_school" if now < first else "break", f"{first_line}\n{next_line}", critical, next_change, "mdi:bag-personal" if now < first else "mdi:coffee-outline")
