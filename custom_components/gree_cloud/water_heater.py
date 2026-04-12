"""Support for Gree Cloud Hot Water Heat Pump (HWHP) devices."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.water_heater import (
    STATE_HEAT_PUMP,
    STATE_OFF,
    STATE_PERFORMANCE,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DISPATCH_DEVICE_DISCOVERED,
    HWHP_OPERATION_BOOST,
    HWHP_OPERATION_HEAT_PUMP,
    HWHP_PROP_SET_TEM_DEC,
    HWHP_PROP_SET_TEM_INT,
    HWHP_PROP_WATER_TEMP,
    HWHP_TEMP_ENCODING_DIVISOR,
    HWHP_TEMP_ENCODING_OFFSET,
    HWHP_TEMP_MAX,
    HWHP_TEMP_MIN,
)
from .coordinator import CloudDeviceDataUpdateCoordinator, GreeCloudConfigEntry, is_hwhp_device
from .entity import GreeCloudEntity

_LOGGER = logging.getLogger(__name__)

# Map integration operation mode strings to WaterHeaterEntity state constants
_OPERATION_TO_STATE = {
    HWHP_OPERATION_HEAT_PUMP: STATE_HEAT_PUMP,
    HWHP_OPERATION_BOOST: STATE_PERFORMANCE,
}

HWHP_OPERATION_LIST = [HWHP_OPERATION_HEAT_PUMP, HWHP_OPERATION_BOOST, STATE_OFF]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Gree Cloud HWHP water heater devices from a config entry."""

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Register the device if it is an HWHP."""
        if not is_hwhp_device(coordinator):
            return
        _LOGGER.debug(
            "Registering water heater entity for HWHP device %s",
            coordinator.device.device_info.name,
        )
        async_add_entities([GreeCloudWaterHeaterEntity(coordinator)])

    for coordinator in entry.runtime_data.coordinators:
        init_device(coordinator)

    entry.async_on_unload(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeCloudWaterHeaterEntity(GreeCloudEntity, WaterHeaterEntity):
    """Representation of a Gree Cloud Hot Water Heat Pump."""

    _attr_precision = PRECISION_WHOLE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = HWHP_TEMP_MIN
    _attr_max_temp = HWHP_TEMP_MAX
    _attr_target_temperature_step = 1
    _attr_operation_list = HWHP_OPERATION_LIST
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )
    _attr_name = None

    def __init__(self, coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Initialize the Gree Cloud HWHP entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_info.mac}_water_heater"

    @property
    def current_temperature(self) -> float | None:
        """Return the current water temperature reported by the device."""
        raw = self.coordinator.device.raw_properties.get(HWHP_PROP_WATER_TEMP)
        if raw is None:
            return None
        return (raw - HWHP_TEMP_ENCODING_OFFSET) / HWHP_TEMP_ENCODING_DIVISOR

    @property
    def target_temperature(self) -> float | None:
        """Return the target water temperature."""
        props = self.coordinator.device.raw_properties
        int_part = props.get(HWHP_PROP_SET_TEM_INT)
        if int_part is None:
            return None
        dec_part = props.get(HWHP_PROP_SET_TEM_DEC, 0)
        return int_part + dec_part / 10

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target water temperature."""
        if ATTR_TEMPERATURE not in kwargs:
            raise ValueError(f"Missing parameter {ATTR_TEMPERATURE}")

        temperature = kwargs[ATTR_TEMPERATURE]
        _LOGGER.debug(
            "Setting water temperature to %d for %s",
            temperature,
            self.coordinator.device.device_info.name,
        )

        self.coordinator.device.target_temperature = temperature
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    @property
    def current_operation(self) -> str:
        """Return the current operation mode."""
        if not self.coordinator.device.power:
            return STATE_OFF
        if self.coordinator.device.turbo:
            return STATE_PERFORMANCE
        return STATE_HEAT_PUMP

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set the operation mode."""
        if operation_mode not in HWHP_OPERATION_LIST:
            raise ValueError(f"Invalid operation mode: {operation_mode}")

        _LOGGER.debug(
            "Setting operation mode to %s for %s",
            operation_mode,
            self.coordinator.device.device_info.name,
        )

        if operation_mode == STATE_OFF:
            self.coordinator.device.power = False
            self.coordinator.device.turbo = False
        else:
            self.coordinator.device.power = True
            self.coordinator.device.turbo = (operation_mode == HWHP_OPERATION_BOOST)

        await self.coordinator.push_state_update()
        self.async_write_ha_state()
