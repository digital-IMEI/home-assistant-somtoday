"""Reconcile only explicitly marked Somtoday events in selected HA calendars."""

import asyncio
from datetime import UTC, datetime, timedelta

from homeassistant.components.calendar.const import DATA_COMPONENT, CalendarEntityFeature
from homeassistant.helpers.storage import Store

from .export import marker, same_event

PENDING_TIMEOUT = timedelta(hours=1)


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

    async def _mark_pending(self, key):
        """Persist a write before sending it to the calendar provider."""
        self.pending[key] = datetime.now(UTC).isoformat()
        await self.store.async_save(self.pending)

    async def _clear_pending(self, key):
        """Clear a write once the resulting event is visible."""
        self.pending.pop(key, None)
        await self.store.async_save(self.pending)

    async def _pending_is_expired(self, key):
        """Migrate old pending records and detect writes that never appeared."""
        value = self.pending[key]
        try:
            created = datetime.fromisoformat(value) if isinstance(value, str) else None
        except ValueError:
            created = None
        if created is None:
            await self._mark_pending(key)
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return datetime.now(UTC) - created > PENDING_TIMEOUT

    async def run(self, desired, targets, start, end, preview):
        async with self.lock:
            if self.pending is None:
                self.pending = await self.store.async_load() or {}
            counts = {
                "create": 0,
                "replace": 0,
                "delete": 0,
                "unchanged": 0,
                "pending": 0,
            }
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
                    exact = next((e for e in existing if same_event(e, value)), None)
                    if not preview and self.pending.get(pending_key):
                        # A delayed or timed-out create may have succeeded remotely.
                        # Resolve it only when the exact event is visible; an older
                        # version with the same marker does not prove success.
                        if exact is not None:
                            await self._clear_pending(pending_key)
                        else:
                            if await self._pending_is_expired(pending_key):
                                raise ValueError(
                                    "Calendar write was accepted but did not become "
                                    "visible within one hour; check the target calendar"
                                )
                            counts["pending"] += 1
                            continue
                    if exact:
                        counts["unchanged"] += 1
                    else:
                        counts["replace" if existing else "create"] += 1
                        if not preview:
                            await self._mark_pending(pending_key)
                            await entity.async_create_event(**value, description=tag)
                            # Verify visibility before deleting the previous version.
                            refreshed = await entity.async_get_events(self.hass, start, end)
                            exact = next((e for e in refreshed
                                          if e.description == tag and same_event(e, value)), None)
                            if exact is None:
                                counts["pending"] += 1
                                continue
                            await self._clear_pending(pending_key)
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
            mode = "preview" if preview else "waiting" if counts["pending"] else "enabled"
            status = {"mode": mode, **counts}
            if mode == "waiting":
                status["reason"] = (
                    "Calendar accepted a write; waiting for the event to become visible"
                )
            return status
