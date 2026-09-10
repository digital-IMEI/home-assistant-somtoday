"""Reconcile only explicitly marked Somtoday events in selected HA calendars."""

import asyncio
from datetime import timedelta

from homeassistant.components.calendar.const import DATA_COMPONENT, CalendarEntityFeature
from homeassistant.helpers.storage import Store

from .export import marker, same_event


def target_entity(hass, entity_id):
    component = hass.data.get(DATA_COMPONENT)
    entity = component.get_entity(entity_id) if component else None
    required = CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
    if entity is None or not entity.available or (entity.supported_features & required) != required:
        raise ValueError("Target calendar unavailable or not writable")
    return entity


class CalendarSync:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.lock = asyncio.Lock()
        self.store = Store(hass, 1, f"somtoday_sync_{entry.entry_id}")
        self.pending = None

    async def run(self, desired, targets, start, end, preview):
        async with self.lock:
            if self.pending is None:
                self.pending = await self.store.async_load() or {}
            counts = {"create": 0, "replace": 0, "delete": 0, "unchanged": 0}
            for target in sorted(targets):
                entity = target_entity(self.hass, target)
                events = await entity.async_get_events(self.hass, start, end)
                owned = {}
                for event in events:
                    description = event.description or ""
                    if any(description.startswith(prefix) for prefix in targets[target]) and description.endswith("]"):
                        if not event.uid or event.recurrence_id or event.rrule:
                            raise ValueError("Unsupported recurring or unidentified managed event")
                        owned.setdefault(description, []).append(event)
                expected = {marker(self.entry.entry_id, key): value
                            for (calendar, key), value in desired.items() if calendar == target}
                for tag, value in expected.items():
                    existing = owned.pop(tag, [])
                    pending_key = target + "|" + tag
                    if self.pending.get(pending_key):
                        # A timed-out create may have succeeded remotely. Never blindly retry it.
                        if not existing:
                            raise ValueError("Uncertain previous calendar write; waiting for target to return the event")
                        del self.pending[pending_key]
                        await self.store.async_save(self.pending)
                    exact = next((e for e in existing if same_event(e, value)), None)
                    if exact:
                        counts["unchanged"] += 1
                    else:
                        counts["replace" if existing else "create"] += 1
                        if not preview:
                            self.pending[pending_key] = True
                            await self.store.async_save(self.pending)
                            await entity.async_create_event(**value, description=tag)
                            # Verify visibility before deleting the previous version.
                            refreshed = await entity.async_get_events(self.hass, start, end)
                            exact = next((e for e in refreshed
                                          if e.description == tag and same_event(e, value)), None)
                            if exact is None:
                                raise ValueError("Calendar write not yet visible; cleanup postponed")
                            del self.pending[pending_key]
                            await self.store.async_save(self.pending)
                    for old in existing:
                        if exact is not None and old.uid == exact.uid:
                            continue
                        if not preview:
                            await entity.async_delete_event(old.uid)
                for obsolete in owned.values():
                    for old in obsolete:
                        # Preserve past events and events outside the configured window.
                        if old.start_datetime_local < start or old.start_datetime_local >= end:
                            continue
                        counts["delete"] += 1
                        if not preview:
                            await entity.async_delete_event(old.uid)
                if not preview:
                    entity.async_write_ha_state()
            return {"mode": "preview" if preview else "enabled", **counts}
