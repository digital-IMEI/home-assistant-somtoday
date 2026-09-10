"""Published school holidays; never infer a holiday from an empty timetable."""

from datetime import date


def holiday_status(items, today: date):
    """Somtoday holiday end dates are inclusive (Monday through Friday, for example)."""
    ranges = []
    for item in items:
        start = date.fromisoformat(str(item["beginDatum"])[:10])
        end = date.fromisoformat(str(item["eindDatum"])[:10])
        if end < start:
            raise ValueError("Invalid holiday date range")
        ranges.append((start, end))
    return any(start <= today <= end for start, end in ranges)
