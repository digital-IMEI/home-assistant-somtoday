"""Published holiday indicator for each child."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .export import item_id


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SomtodayHolidaySensor(coordinator, entry, student)
        for student in coordinator.data.get("students", [])
    ])


class SomtodayHolidaySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:beach"

    def __init__(self, coordinator, entry, student):
        super().__init__(coordinator)
        self.student = item_id(student)
        self._attr_unique_id = f"{entry.entry_id}_{self.student}_holiday"
        self._attr_name = f"{student.get('roepnaam') or self.student} · Published holiday"

    @property
    def is_on(self):
        return self.coordinator.data.get("holidays_by_student", {}).get(self.student)

    @property
    def available(self):
        return super().available and self.is_on is not None
