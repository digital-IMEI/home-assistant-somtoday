"""Data coordinator for Somtoday."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SomtodayApiError, SomtodayClient
from .const import CONF_TOKEN, DOMAIN, SCHEDULE_DAYS, UPDATE_INTERVAL
from .models import school_day_bounds
from .export import desired_events, select_student, item_id, scope_marker
from .sync import CalendarSync


class SomtodayCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch and normalize Somtoday data."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: SomtodayClient
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(minutes=entry.options.get("scan_interval", 15)),
        )
        self.entry = entry
        self.client = client
        self.calendar_sync = CalendarSync(hass, entry)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            start = dt_util.now().date()
            students = await self.client.students()
            appointments = await self.client.appointments(
                start, start + timedelta(days=self.entry.options.get("days_ahead", 14))
            )
        except SomtodayApiError as err:
            raise UpdateFailed(str(err)) from err
        finally:
            # Refresh tokens rotate even when the subsequent roster request fails.
            if self.client.token != self.entry.data.get(CONF_TOKEN):
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={**self.entry.data, CONF_TOKEN: self.client.token},
                )
        sync_status = {"mode": "disabled"}
        by_student = {}
        days_by_student = {}
        prepared = False
        try:
            desired = {}
            targets = {}
            window_start = dt_util.start_of_local_day()
            window_end = window_start + timedelta(days=self.entry.options.get("days_ahead", 14))
            for pupil in students:
                student = item_id(pupil)
                _, selected = select_student(appointments, students, student)
                by_student[student] = selected
                days_by_student[student] = school_day_bounds(selected)
                route = dict(self.entry.options.get("exports", {}).get(student, {}))
                name = str(pupil.get("roepnaam") or student)
                for field, default in (("day_title", "School · {student}"), ("lesson_prefix", "{student} · ")):
                    route[field] = route.get(field, default).replace("{student}", name)
                for field, kind in (("day_calendar", "day"), ("lesson_calendar", "lesson")):
                    if target := route.get(field):
                        targets.setdefault(target, set()).add(scope_marker(self.entry.entry_id, f"{student}:{kind}"))
                desired.update(desired_events(selected, route, student, window_start, window_end))
            prepared = True
            if targets:
                sync_status = await self.calendar_sync.run(
                    desired, targets, window_start, window_end,
                    self.entry.options.get("preview", True),
                )
        except ValueError as err:
            sync_status = {"mode": "error", "reason": str(err)}
            # A multi-student account must never show merged school-day bounds.
            if not prepared:
                by_student = {}
                days_by_student = {}
        except Exception:
            # Do not include provider exception text (may contain URLs or personal data).
            sync_status = {"mode": "error", "reason": "Calendar synchronization failed; source roster remains available"}
        return {
            "students": students,
            "appointments": appointments,
            "appointments_by_student": by_student,
            "school_days_by_student": days_by_student,
            "sync_status": sync_status,
        }
