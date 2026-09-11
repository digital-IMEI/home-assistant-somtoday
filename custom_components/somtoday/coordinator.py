"""Data coordinator for Somtoday."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.helpers import issue_registry as ir

from .api import SomtodayApiError, SomtodayClient, SomtodayAuthenticationError
from .const import CONF_TOKEN, DOMAIN, SCHEDULE_DAYS, UPDATE_INTERVAL
from .models import school_day_bounds
from .export import (
    desired_events,
    desired_holiday_events,
    item_id,
    scope_marker,
    select_student,
)
from .sync import CalendarSync
from .holidays import holiday_status


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
        self._holidays = {}
        self._holidays_checked = None
        self.export_ready = False

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            start = dt_util.now().date()
            students = await self.client.students()
            appointments = await self.client.appointments(
                start, start + timedelta(days=self.entry.options.get("days_ahead", 14))
            )
            now = dt_util.now()
            if self._holidays_checked is None or now - self._holidays_checked >= timedelta(hours=6):
                holiday_data = {}
                for pupil in students:
                    student_id = item_id(pupil)
                    try:
                        items = await self.client.holidays(student_id)
                        holiday_status(items, start)  # Validate before retaining a snapshot.
                        holiday_data[student_id] = items
                    except (SomtodayApiError, ValueError, KeyError, TypeError):
                        # Optional endpoint permissions vary by school/account.
                        # Do not block the roster or interpret failure as "no holiday".
                        holiday_data[student_id] = None
                self._holidays = holiday_data
                self._holidays_checked = now
        except SomtodayAuthenticationError as err:
            raise ConfigEntryAuthFailed("Somtoday sign-in expired; sign in again") from err
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
                for field, default in (
                    ("day_title", "School · {student}"),
                    ("lesson_prefix", "{student} · "),
                    ("holiday_title", "{student} · {holiday}"),
                ):
                    route[field] = route.get(field, default).replace("{student}", name)
                for field, kind in (
                    ("day_calendar", "day"),
                    ("lesson_calendar", "lesson"),
                    ("holiday_calendar", "holiday"),
                ):
                    if target := route.get(field):
                        targets.setdefault(target, set()).add(scope_marker(self.entry.entry_id, f"{student}:{kind}"))
                desired.update(desired_events(selected, route, student, window_start, window_end))
                holiday_items = self._holidays.get(student)
                if holiday_items is not None:
                    desired.update(
                        desired_holiday_events(
                            holiday_items,
                            route,
                            student,
                            window_start,
                            window_end,
                        )
                    )
                elif route.get("holiday_calendar"):
                    # Keep previously exported holidays when the optional endpoint
                    # cannot be read; absence of data is not an empty publication.
                    target = route["holiday_calendar"]
                    targets.get(target, set()).discard(
                        scope_marker(self.entry.entry_id, f"{student}:holiday")
                    )
            prepared = True
            if targets and not self.export_ready:
                sync_status = {"mode": "starting", "reason": "Waiting for calendar startup grace period"}
            elif targets:
                sync_status = await self.calendar_sync.run(
                    desired, targets, window_start, window_end,
                    False,
                )
        except ValueError as err:
            sync_status = {"mode": "error", "reason": str(err)}
            # A multi-student account must never show merged school-day bounds.
            if not prepared:
                by_student = {}
                days_by_student = {}
        except HomeAssistantError as err:
            sync_status = {
                "mode": "error",
                "reason": (
                    "Destination calendar rejected the operation; test its "
                    "create-event action in Home Assistant"
                ),
                "error_type": type(err).__name__,
            }
        except Exception:
            # Do not include provider exception text (may contain URLs or personal data).
            sync_status = {"mode": "error", "reason": "Calendar synchronization failed; source roster remains available"}
        issue_id = f"calendar_sync_{self.entry.entry_id}"
        if sync_status["mode"] == "error":
            ir.async_create_issue(
                self.hass, DOMAIN, issue_id, is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="calendar_sync_failed",
                learn_more_url="https://github.com/digital-IMEI/home-assistant-somtoday#calendar-provider-compatibility",
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        return {
            "students": students,
            "appointments": appointments,
            "appointments_by_student": by_student,
            "school_days_by_student": days_by_student,
            "sync_status": sync_status,
            "holidays_by_student": {
                student: None if items is None else holiday_status(items, start)
                for student, items in self._holidays.items()
            },
        }
