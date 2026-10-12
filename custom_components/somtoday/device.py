"""Stable logical devices for a Somtoday account and its pupils."""

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .export import item_id


def student_device_info(entry, student) -> DeviceInfo:
    """Group by identity, independent of pupil name or response order."""
    student_id = item_id(student)
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_student_{student_id}")},
        name=str(student.get("roepnaam") or student_id),
        manufacturer="Somtoday",
        model="Student",
    )


def account_device_info(entry) -> DeviceInfo:
    """Group diagnostics which concern the whole account."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_account")},
        name="Somtoday account",
        manufacturer="Somtoday",
        model="Account",
    )
