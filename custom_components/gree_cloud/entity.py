"""Base entity for Gree Cloud devices."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo as HADeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CloudDeviceDataUpdateCoordinator


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
