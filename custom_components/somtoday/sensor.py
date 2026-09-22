"""Sensor platform for Somtoday."""

from __future__ import annotations

from datetime import datetime, time

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .export import item_id
from .coordinator import SomtodayCoordinator
from .absences import (
    absence_counts,
    label_counts,
    measure_counts,
    school_year_start,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SomtodayCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [SomtodaySyncSensor(coordinator, entry), SomtodayHomeworkSyncSensor(coordinator, entry)]
    entities.extend(
        SomtodayNextAssessmentSensor(coordinator, entry, student)
        for student in coordinator.data.get("students", [])
    )
    for student in coordinator.data.get("students", []):
        route = entry.options.get("exports", {}).get(item_id(student), {})
        if isinstance(route, dict) and route.get("absences_enabled"):
            entities.append(SomtodayAbsenceSensor(coordinator, entry, student))
            entities.append(SomtodayMeasureSensor(coordinator, entry, student))
    async_add_entities(entities)


class SomtodaySyncSensor(CoordinatorEntity[SomtodayCoordinator], SensorEntity):
    """Expose preview counts and synchronization failures without private data."""

    _attr_has_entity_name = True
    _attr_name = "Calendar sync"
    _attr_icon = "mdi:calendar-sync"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_calendar_sync"

    @property
    def native_value(self):
        return self.coordinator.data.get("sync_status", {}).get("mode", "disabled")

    @property
    def extra_state_attributes(self):
        return self.coordinator.data.get("sync_status", {})


class SomtodayNextAssessmentSensor(
    CoordinatorEntity[SomtodayCoordinator], SensorEntity
):
    """Expose the next dated assessment and count undated test assignments."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clipboard-text-clock-outline"

    def __init__(self, coordinator, entry, student):
        super().__init__(coordinator)
        self.student = item_id(student)
        name = student.get("roepnaam") or self.student
        self._attr_name = f"{name} · Volgende toets"
        self._attr_unique_id = f"{entry.entry_id}_{self.student}_next_assessment"

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.data.get("assessments_by_student", {}).get(
                self.student
            )
            is not None
        )

    def _dated(self):
        now = dt_util.now()
        return [
            value
            for value in self.coordinator.data.get(
                "assessments_by_student", {}
            ).get(self.student, []) or []
            if value.get("start") is not None
            and value.get("end") is not None
            and (
                value["end"] > now
                if isinstance(value["end"], datetime)
                else value["end"] > now.date()
            )
        ]

    @property
    def native_value(self):
        values = self._dated()
        if not values:
            return None
        start = values[0]["start"]
        if isinstance(start, datetime):
            return start
        return datetime.combine(start, time.min, tzinfo=dt_util.DEFAULT_TIME_ZONE)

    @property
    def extra_state_attributes(self):
        all_values = self.coordinator.data.get("assessments_by_student", {}).get(
            self.student, []
        ) or []
        dated = self._dated()
        attributes = {
            "undated_count": sum(
                value.get("start") is None for value in all_values
            )
        }
        if dated:
            value = dated[0]
            start = value["start"]
            start_day = start.date() if isinstance(start, datetime) else start
            attributes.update(
                subject=value["subject"],
                assessment_type=value["type_label"],
                topic=value["topic"],
                days_until=(start_day - dt_util.now().date()).days,
                all_day=value["all_day"],
                made=value["made"],
            )
        return attributes


class _SomtodayStudentSensor(CoordinatorEntity[SomtodayCoordinator], SensorEntity):
    """Shared plumbing for the opt-in absence overview entities."""

    _attr_has_entity_name = True
    _key = ""

    def __init__(self, coordinator, entry, student):
        super().__init__(coordinator)
        self.entry = entry
        self.student = item_id(student)
        self._name = student.get("roepnaam") or self.student

    def _values(self):
        return self.coordinator.data.get(self._key, {}).get(self.student)

    @property
    def route(self):
        route = self.entry.options.get("exports", {}).get(self.student, {})
        return route if isinstance(route, dict) else {}

    @property
    def available(self):
        # An unreadable endpoint is not an empty overview, so the entity goes
        # unavailable rather than reporting a reassuring zero.
        return super().available and self._values() is not None


class SomtodayAbsenceSensor(_SomtodayStudentSensor):
    """Absence reports for the running school year."""

    _attr_icon = "mdi:account-alert-outline"
    _key = "absences_by_student"

    def __init__(self, coordinator, entry, student):
        super().__init__(coordinator, entry, student)
        self._attr_name = f"{self._name} · Absenties"
        self._attr_unique_id = f"{entry.entry_id}_{self.student}_absences"

    @property
    def native_value(self):
        values = self._values()
        return None if values is None else len(values)

    @property
    def extra_state_attributes(self):
        values = self._values() or []
        # Staff remarks are a separate opt-in: a date and a reason belong on a
        # family dashboard, the wording of an incident usually does not.
        include_remarks = bool(self.route.get("absence_remarks"))
        attributes = {
            **absence_counts(values),
            "reasons": label_counts(values, "reason"),
            "school_year_start": school_year_start(dt_util.now().date()).isoformat(),
            "reports": [
                {
                    "start": value["start"].isoformat(),
                    "end": value["end"].isoformat() if value["end"] else None,
                    "reason": value["reason"],
                    "authorised": value["authorised"],
                    "handled": value["handled"],
                    **({"remark": value["remark"]} if include_remarks else {}),
                }
                for value in values[:25]
            ],
        }
        if values:
            latest = values[0]
            attributes.update(
                latest_start=latest["start"].isoformat(),
                latest_reason=latest["reason"],
                latest_authorised=latest["authorised"],
            )
        return attributes


class SomtodayMeasureSensor(_SomtodayStudentSensor):
    """Measures such as "Huiswerk niet in orde", which absence reports never contain."""

    _attr_icon = "mdi:gavel"
    _key = "measures_by_student"

    def __init__(self, coordinator, entry, student):
        super().__init__(coordinator, entry, student)
        self._attr_name = f"{self._name} · Maatregelen"
        self._attr_unique_id = f"{entry.entry_id}_{self.student}_measures"

    @property
    def native_value(self):
        values = self._values()
        return None if values is None else len(values)

    @property
    def extra_state_attributes(self):
        values = self._values() or []
        attributes = {
            **measure_counts(values),
            "labels": label_counts(values, "label"),
            "school_year_start": school_year_start(dt_util.now().date()).isoformat(),
            "measures": [
                {
                    "date": value["date"].isoformat(),
                    "label": value["label"],
                    "complied": value["complied"],
                    "automatic": value["automatic"],
                }
                for value in values[:25]
            ],
        }
        if values:
            latest = values[0]
            attributes.update(
                latest_date=latest["date"].isoformat(),
                latest_label=latest["label"],
                latest_complied=latest["complied"],
            )
        return attributes


class SomtodayHomeworkSyncSensor(SomtodaySyncSensor):
    """Privacy-safe task synchronization counts."""
    _attr_name = "Homework sync"
    _attr_icon = "mdi:clipboard-check-outline"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_homework_sync"

    @property
    def available(self):
        # Diagnostics must still explain a failed source refresh. This does not
        # make stale source entities available or claim that synchronization ran.
        return self.coordinator.data is not None

    @property
    def native_value(self):
        if not self.coordinator.last_update_success:
            return "error"
        return self.coordinator.data.get("homework_sync_status", {}).get("mode", "disabled")

    @property
    def extra_state_attributes(self):
        if not self.coordinator.last_update_success:
            return {"reason": "source_update_failed"}
        return self.coordinator.data.get("homework_sync_status", {})
