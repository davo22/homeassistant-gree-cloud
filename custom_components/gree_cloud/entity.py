"""Base entity for Gree Cloud devices."""

from __future__ import annotations

from typing import NamedTuple

from homeassistant.helpers.device_registry import DeviceInfo as HADeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CloudDeviceDataUpdateCoordinator


class RawProp(NamedTuple):
    """Stand-in for a ``Props`` member, for keys the library enum lacks.

    ``Device.set_property`` only reads ``name.value``, so this is enough to
    stage a raw property for the next ``push_state_update()``.
    """

    value: str


class GreeCloudEntity(CoordinatorEntity[CloudDeviceDataUpdateCoordinator]):
    """Base class for Gree Cloud entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_device_info = HADeviceInfo(
            identifiers={(DOMAIN, coordinator.device.device_info.mac)},
            name=coordinator.device.device_info.name,
            manufacturer="Gree",
            model=coordinator.device.hid or "Unknown Model",
        )
