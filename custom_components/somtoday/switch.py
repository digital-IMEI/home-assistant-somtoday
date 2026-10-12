"""Opt-in per-child Live Activities using the Companion app's native layout."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import timedelta

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .device import student_device_info
from .const import DOMAIN
from .export import item_id
from .live_activity import activity_view, limit_first_line

_LOGGER = logging.getLogger(__name__)
ACTIVITY_LAYOUT = "next_room_v1"


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SomtodayLiveActivitySwitch(coordinator, entry, student)
        for student in coordinator.data.get("students", [])
        if entry.options.get("exports", {}).get(item_id(student), {}).get("live_activity_targets")
    ])


class SomtodayLiveActivitySwitch(SwitchEntity, RestoreEntity):
    """Arm the daily timetable on selected phones; off immediately clears it.

    Clock transitions use cached appointments, independently of API polling.
    A per-target fingerprint avoids redundant pushes; failed targets retry
    independently without notifying successful targets again.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:cellphone-text"
    _attr_is_on = False

    def __init__(self, coordinator, entry, student):
        self.coordinator = coordinator
        self.student = item_id(student)
        self._attr_device_info = student_device_info(entry, student)
        self.name_in_title = str(student.get("roepnaam") or self.student)
        self._attr_name = "Live Activity"
        self._attr_unique_id = f"{entry.entry_id}_{self.student}_live_activity"
        route = entry.options.get("exports", {}).get(self.student, {})
        self.targets = tuple(dict.fromkeys(route.get("live_activity_targets", [])))
        self.language = route.get("live_activity_language", "nl")
        self.first_line_limit = int(route.get("live_activity_first_line_limit", 28))
        # Stable, private, valid Companion tag, including account and pupil.
        self.tag = "somtoday-" + hashlib.sha256(self._attr_unique_id.encode()).hexdigest()[:32]
        self._lock = asyncio.Lock()
        self._cancel_timer = None
        self._last_sent = {}
        self._started_at = {}
        self._stopping = False
        self._phase = "off"
        self._failed_targets = 0
        self._restart_targets = set()

    @property
    def extra_state_attributes(self):
        return {"phase": self._phase, "failed_targets": self._failed_targets,
                "layout": ACTIVITY_LAYOUT if not self._restart_targets else "pending"}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if previous := await self.async_get_last_state():
            self._attr_is_on = previous.state == "on"
            if self._attr_is_on and getattr(previous, "attributes", {}).get("layout") != ACTIVITY_LAYOUT:
                # The Companion title is fixed at creation. End the previous
                # layout once so updates cannot keep its ambiguous old title.
                self._restart_targets = set(self.targets)
        self.async_on_remove(self.coordinator.async_add_listener(self._source_updated))
        self.async_on_remove(self._cancel_scheduled)
        # Defer I/O until state registration and mobile-app service startup.
        self._schedule(1)

    @callback
    def _source_updated(self):
        if not self._stopping:
            self.hass.async_create_task(self._async_refresh())

    @callback
    def _cancel_scheduled(self):
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

    @callback
    def _schedule(self, seconds):
        self._cancel_scheduled()
        if not self._stopping:
            self._cancel_timer = async_call_later(self.hass, max(1, seconds), self._timer_fired)

    async def _timer_fired(self, _now):
        self._cancel_timer = None
        await self._async_refresh()

    async def async_turn_on(self, **kwargs):
        async with self._lock:
            self._attr_is_on = True
        await self._async_refresh()

    async def async_turn_off(self, **kwargs):
        async with self._lock:
            self._attr_is_on = False
        await self._async_refresh()

    async def async_will_remove_from_hass(self):
        self._stopping = True
        self._cancel_scheduled()
        async with self._lock:
            for target in self.targets:
                await self._send(target, None)
        await super().async_will_remove_from_hass()

    def _platform(self, target):
        """Resolve the exact notify service's registration, not its display name."""
        # Read loaded registration metadata without importing mobile_app, which
        # also imports optional cloud, camera and stream integrations.
        mobile_app = self.hass.data.get("mobile_app", {})
        notifier = mobile_app.get("notify")
        webhook = getattr(notifier, "registered_targets", {}).get(target.partition(".")[2])
        registration = mobile_app.get("config_entries", {}).get(webhook)
        os_name = str(registration.data.get("os_name", "")).casefold() if registration else ""
        return "android" if os_name == "android" else "ios" if os_name in ("ios", "ipados") else "unknown"

    def _payload(self, message, room, platform="ios", icon="mdi:school"):
        payload = {
            "title": f"{self.name_in_title} · {'Next room' if self.language == 'en' else 'Volgend lokaal'}",
            "message": limit_first_line(message, self.first_line_limit),
            "data": {
                "tag": self.tag,
                "live_update": True,
                "critical_text": room,
                "notification_icon": icon,
                "notification_icon_color": "#03A9F4",
                "background_color": "transparent",
                "url": "somtoday://",
                "silent": True,
                "alert_once": True,
                # ActivityKit alerts are controlled by silent, independently
                # of the ordinary notification sound. Passive also quiets any
                # standard-notification fallback on iOS.
                "push": {"sound": None, "interruption-level": "passive"},
            },
        }
        if platform == "android":
            data = payload["data"]
            for key in ("push", "background_color"):
                data.pop(key)
            data.update({
                "channel": "Somtoday timetable",
                # LOW remains eligible for promoted Live Updates while silent.
                "importance": "low",
                "vibrationPattern": "0",
                "persistent": True,
                "sticky": True,
                "priority": "high",
                "ttl": 0,
                "color": "#03A9F4",
                "clickAction": "app://nl.topicus.somtoday.leerling",
            })
        return payload

    async def _send(self, target, payload):
        if target in self._last_sent and self._last_sent[target] == payload:
            return True
        # Only configured Companion services can receive timetable content.
        if not target.startswith("notify.mobile_app_"):
            return False
        service = target.partition(".")[2]
        data = payload if payload is not None else {"message": "clear_notification", "data": {"tag": self.tag}}
        if payload is None and self._platform(target) == "android":
            data["data"].update(priority="high", ttl=0)
        try:
            await self.hass.services.async_call("notify", service, data, blocking=True)
        except HomeAssistantError:
            _LOGGER.warning("Somtoday Live Activity delivery failed; retry scheduled")
            return False
        self._last_sent[target] = payload
        if payload is None:
            self._started_at.pop(target, None)
        else:
            self._started_at.setdefault(target, dt_util.now())
        return True

    async def _async_refresh(self):
        async with self._lock:
            if self._stopping:
                return
            now = dt_util.now()
            payload = None
            next_change = None
            if not self._attr_is_on:
                self._phase = "off"
            elif not self.coordinator.last_update_success:
                view = activity_view(self.coordinator.data.get("appointments_by_student", {}).get(self.student, []), now, self.language)
                self._phase = "unavailable" if view.message is not None else "idle"
                # Do not display a stale room, or start a new unavailable card.
                message = "Timetable unavailable" if self.language == "en" else "Rooster niet beschikbaar"
                if view.message is not None:
                    payload = self._payload(message, "—", icon="mdi:cloud-alert")
                # Still stop after school, even if the source has gone offline.
                next_change = min(view.next_change, now + timedelta(minutes=1))
            else:
                view = activity_view(self.coordinator.data.get("appointments_by_student", {}).get(self.student, []), now, self.language)
                self._phase = view.phase
                next_change = view.next_change
                if view.message is not None:
                    payload = self._payload(view.message, view.room, icon=view.icon)

            failures = 0
            for target in self.targets:
                platform = self._platform(target)
                if target in self._restart_targets:
                    if not await self._send(target, None):
                        failures += 1
                        continue
                    self._restart_targets.discard(target)
                target_payload = payload
                if platform == "android" and payload is not None:
                    if self.coordinator.last_update_success:
                        android_view = activity_view(
                            self.coordinator.data.get("appointments_by_student", {}).get(self.student, []),
                            now, self.language, include_next_room=True,
                        )
                        target_payload = self._payload(android_view.message, android_view.room, "android", android_view.icon)
                    else:
                        target_payload = self._payload(payload["message"], "—", "android", "mdi:cloud-alert")
                if self._phase == "unavailable" and not self._last_sent.get(target):
                    target_payload = None
                # iOS expires a card after 8 h. Renew once near that boundary
                # for unusually long school days, not on every lesson change.
                started = self._started_at.get(target)
                if platform != "android" and started and target_payload is not None:
                    renewal = started + timedelta(hours=7, minutes=55)
                    if now >= renewal:
                        if not await self._send(target, None):
                            failures += 1
                            continue
                        if self._phase == "unavailable":
                            target_payload = None
                    elif next_change is not None:
                        next_change = min(next_change, renewal)
                if not await self._send(target, target_payload):
                    failures += 1
                if platform != "android" and target_payload is not None and (started := self._started_at.get(target)):
                    renewal = started + timedelta(hours=7, minutes=55)
                    if renewal > now and next_change is not None:
                        next_change = min(next_change, renewal)
            self._failed_targets = failures
            self.async_write_ha_state()
            self._cancel_scheduled()
            if failures:
                retry = now + timedelta(minutes=1)
                next_change = min(next_change, retry) if next_change else retry
            if next_change is not None:
                self._schedule((next_change - now).total_seconds())
