"""Support for Gree Cloud select entities."""

from __future__ import annotations

import logging
from typing import NamedTuple

from greeclimate_davo22.device import Device

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DISPATCH_DEVICE_DISCOVERED,
    POWER_LIMIT_LEVELS,
    PROP_POWER_REDUCE_GEAR,
    PROP_POWER_REDUCE_TYPE,
)
from .coordinator import (
    CloudDeviceDataUpdateCoordinator,
    GreeCloudConfigEntry,
    is_hwhp_device,
)
from .entity import GreeCloudEntity

_LOGGER = logging.getLogger(__name__)


class _RawProp(NamedTuple):
    """Stand-in for a ``Props`` member, for keys the library enum lacks.

    ``Device.set_property`` only reads ``name.value``, so this is enough to
    stage a raw property for the next ``push_state_update()``.
    """

    value: str


_POWER_REDUCE_GEAR = _RawProp(PROP_POWER_REDUCE_GEAR)
_GEAR_TO_OPTION = {gear: option for option, gear in POWER_LIMIT_LEVELS.items()}

POWER_LIMIT_DESCRIPTION = SelectEntityDescription(
    key="Power limit",
    translation_key="power_limit",
    entity_category=EntityCategory.CONFIG,
    options=list(POWER_LIMIT_LEVELS),
)


def _supports_power_limit(device: Device) -> bool:
    """Return True if the unit offers the compressor power limit.

    Units with the feature report a non-zero ``PowReduceType``; the rest answer
    0 or leave the key out.
    """
    return bool(device.raw_properties.get(PROP_POWER_REDUCE_TYPE))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Gree Cloud select entities from a config entry."""

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Register the device."""
        if is_hwhp_device(coordinator):
            return
        if not _supports_power_limit(coordinator.device):
            _LOGGER.debug(
                "%s does not report %s, skipping power limit select",
                coordinator.device.device_info.name,
                PROP_POWER_REDUCE_TYPE,
            )
            return
        async_add_entities([GreeCloudPowerLimitSelect(coordinator)])

    for coordinator in entry.runtime_data.coordinators:
        init_device(coordinator)

    entry.async_on_unload(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeCloudPowerLimitSelect(GreeCloudEntity, SelectEntity):
    """Compressor power limit (Gree+ "power reduce": off / A1 / A2)."""

    entity_description = POWER_LIMIT_DESCRIPTION

    def __init__(self, coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.device.device_info.mac}_{self.entity_description.key}"
        )

    @property
    def current_option(self) -> str | None:
        """Return the current level, or None for a value we do not know."""
        gear = self.coordinator.device.raw_properties.get(PROP_POWER_REDUCE_GEAR)
        return _GEAR_TO_OPTION.get(gear)

    @property
    def extra_state_attributes(self) -> dict[str, int | None]:
        """Expose the raw level so unknown values are still visible."""
        props = self.coordinator.device.raw_properties
        return {
            "raw_gear": props.get(PROP_POWER_REDUCE_GEAR),
            "raw_type": props.get(PROP_POWER_REDUCE_TYPE),
        }

    async def async_select_option(self, option: str) -> None:
        """Set the power limit level."""
        self.coordinator.device.set_property(
            _POWER_REDUCE_GEAR, POWER_LIMIT_LEVELS[option]
        )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()
