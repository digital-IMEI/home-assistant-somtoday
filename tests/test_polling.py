from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from custom_components.somtoday.polling import poll_interval

TZ = ZoneInfo("Europe/Amsterdam")


def at(hour, minute=0):
    return datetime(2026, 11, 9, hour, minute, tzinfo=TZ)


def test_disabled_preserves_scan_interval():
    assert poll_interval(at(7, 30), {"scan_interval": 15}) == timedelta(minutes=15)


def test_morning_refreshes_at_boundaries():
    opts = {"scan_interval": 15, "morning_poll_enabled": True, "morning_poll_interval": 5,
            "morning_poll_start_hour": 7, "morning_poll_end_hour": 8}
    assert poll_interval(at(6, 58), opts) == timedelta(minutes=2)
    assert poll_interval(at(7, 0), opts) == timedelta(minutes=5)
    assert poll_interval(at(7, 58), opts) == timedelta(minutes=2)
    assert poll_interval(at(8, 0), opts) == timedelta(minutes=15)


def test_overnight_window():
    opts = {"scan_interval": 30, "morning_poll_enabled": True, "morning_poll_interval": 5,
            "morning_poll_start_hour": 23, "morning_poll_end_hour": 2}
    assert poll_interval(at(22, 55), opts) == timedelta(minutes=5)
    assert poll_interval(at(23, 30), opts) == timedelta(minutes=5)
    assert poll_interval(at(1, 55), opts) == timedelta(minutes=5)
    assert poll_interval(at(2, 0), opts) == timedelta(minutes=30)
