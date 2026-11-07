"""Optional local-time polling window with boundary-aware refreshes."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Mapping


def poll_interval(now: datetime, options: Mapping[str, Any]) -> timedelta:
    """Choose the next update interval without skipping morning boundaries."""
    base = timedelta(minutes=max(5, int(options.get("scan_interval", 15))))
    if not options.get("morning_poll_enabled", False):
        return base

    start = max(0, min(23, int(options.get("morning_poll_start_hour", 7))))
    end = max(1, min(24, int(options.get("morning_poll_end_hour", 8))))
    if start == end:
        return base
    fast = timedelta(minutes=max(5, int(options.get("morning_poll_interval", 5))))
    wall = now.hour + (now.minute * 60 + now.second) / 3600
    active = start <= wall < end if start < end else wall >= start or wall < end
    interval = fast if active else base

    # Wake at the next transition even when the base interval is longer.
    upcoming = []
    for offset in (0, 1, 2):
        day = now.date() + timedelta(days=offset)
        for hour in (start, end):
            when = datetime.combine(
                day + timedelta(days=hour // 24), time(hour % 24), tzinfo=now.tzinfo
            )
            if when > now:
                upcoming.append(when - now)
    return min(interval, min(upcoming)) if upcoming else interval
