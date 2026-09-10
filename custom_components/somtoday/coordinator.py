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


class SomtodayCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch and normalize Somtoday data."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: SomtodayClient
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            start = dt_util.now().date()
            students = await self.client.students()
            appointments = await self.client.appointments(
                start, start + timedelta(days=SCHEDULE_DAYS)
            )
        except SomtodayApiError as err:
            raise UpdateFailed(str(err)) from err

        if self.client.token != self.entry.data.get(CONF_TOKEN):
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, CONF_TOKEN: self.client.token},
            )
        return {
            "students": students,
            "appointments": appointments,
            "school_days": school_day_bounds(appointments),
        }
