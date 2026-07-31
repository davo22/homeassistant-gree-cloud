"""Support for Gree Cloud vane position selects."""

from __future__ import annotations

import logging

from greeclimate.device import HorizontalSwing, VerticalSwing

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DISPATCH_DEVICE_DISCOVERED
from .coordinator import (
    CloudDeviceDataUpdateCoordinator,
    GreeCloudConfigEntry,
    is_hwhp_device,
)
from .entity import GreeCloudEntity

_LOGGER = logging.getLogger(__name__)

VERTICAL_POSITIONS = {
    "Oben": VerticalSwing.FixedUpper,
    "Oben-Mitte": VerticalSwing.FixedUpperMiddle,
    "Mitte": VerticalSwing.FixedMiddle,
    "Unten-Mitte": VerticalSwing.FixedLowerMiddle,
    "Unten": VerticalSwing.FixedLower,
}

HORIZONTAL_POSITIONS = {
    "Links": HorizontalSwing.Left,
    "Links-Mitte": HorizontalSwing.LeftCenter,
    "Mitte": HorizontalSwing.Center,
    "Rechts-Mitte": HorizontalSwing.RightCenter,
    "Rechts": HorizontalSwing.Right,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Gree Cloud vane selects from a config entry."""

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Register vane selects for a device."""
        if is_hwhp_device(coordinator):
            return
        async_add_entities(
            [
                GreeCloudVaneSelect(coordinator, "vertical", VERTICAL_POSITIONS),
                GreeCloudVaneSelect(coordinator, "horizontal", HORIZONTAL_POSITIONS),
            ]
        )

    for coordinator in entry.runtime_data.coordinators:
        init_device(coordinator)

    entry.async_on_unload(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeCloudVaneSelect(GreeCloudEntity, SelectEntity):
    """A fixed vane position (vertical or horizontal) for a Gree Cloud device."""

    def __init__(
        self,
        coordinator: CloudDeviceDataUpdateCoordinator,
        axis: str,
        positions: dict[str, VerticalSwing | HorizontalSwing],
    ) -> None:
        """Initialize the vane select."""
        super().__init__(coordinator)
        self._axis = axis
        self._positions = positions
        self._reverse = {int(v): k for k, v in positions.items()}
        self._attr_options = list(positions)
        self._attr_unique_id = f"{coordinator.device.device_info.mac}_swing_{axis}"
        self._attr_name = (
            "Lamelle vertikal" if axis == "vertical" else "Lamelle horizontal"
        )

    @property
    def current_option(self) -> str | None:
        """Return the selected fixed position, or None if the vane is swinging."""
        if self._axis == "vertical":
            value = self.coordinator.device.vertical_swing
        else:
            value = self.coordinator.device.horizontal_swing
        return self._reverse.get(int(value))

    async def async_select_option(self, option: str) -> None:
        """Set a fixed vane position."""
        value = self._positions[option]
        _LOGGER.debug(
            "Setting %s vane to %s for device %s",
            self._axis,
            option,
            self.coordinator.device.device_info.name,
        )
        if self._axis == "vertical":
            self.coordinator.device.vertical_swing = value
        else:
            self.coordinator.device.horizontal_swing = value
        await self.coordinator.push_state_update()
        self.async_write_ha_state()
