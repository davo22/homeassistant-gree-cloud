"""Support for Gree Cloud climate devices."""

from __future__ import annotations

import logging
from typing import Any

from greeclimate.device import (
    TEMP_MAX,
    TEMP_MAX_F,
    TEMP_MIN,
    TEMP_MIN_F,
    FanSpeed,
    HorizontalSwing,
    Mode,
    Props,
    TemperatureUnits,
    VerticalSwing,
)

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_ECO,
    PRESET_NONE,
    PRESET_SLEEP,
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_VERTICAL,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_HALVES,
    PRECISION_WHOLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DEHUMIDIFY_MODE_ON,
    DISPATCH_DEVICE_DISCOVERED,
    FAN_MEDIUM_HIGH,
    FAN_MEDIUM_LOW,
    HUMIDITY_MAX_COOL,
    HUMIDITY_MAX_DRY,
    HUMIDITY_MIN_COOL,
    HUMIDITY_MIN_DRY,
    HUMIDITY_STEP,
    PROP_DEHUMIDIFY_MODE,
    TARGET_TEMPERATURE_STEP,
    TARGET_TEMPERATURE_STEP_HALF,
)
from .coordinator import CloudDeviceDataUpdateCoordinator, GreeCloudConfigEntry, is_hwhp_device
from .entity import GreeCloudEntity

_LOGGER = logging.getLogger(__name__)

HVAC_MODES = {
    Mode.Auto: HVACMode.AUTO,
    Mode.Cool: HVACMode.COOL,
    Mode.Dry: HVACMode.DRY,
    Mode.Fan: HVACMode.FAN_ONLY,
    Mode.Heat: HVACMode.HEAT,
}
HVAC_MODES_REVERSE = {v: k for k, v in HVAC_MODES.items()}

PRESET_MODES = [
    PRESET_ECO,  # Power saving mode
    PRESET_AWAY,  # Steady heat, or 8C mode on gree units
    PRESET_BOOST,  # Turbo mode
    PRESET_NONE,  # Default operating mode
    PRESET_SLEEP,  # Sleep mode
]

FAN_MODES = {
    FanSpeed.Auto: FAN_AUTO,
    FanSpeed.Low: FAN_LOW,
    FanSpeed.MediumLow: FAN_MEDIUM_LOW,
    FanSpeed.Medium: FAN_MEDIUM,
    FanSpeed.MediumHigh: FAN_MEDIUM_HIGH,
    FanSpeed.High: FAN_HIGH,
}
FAN_MODES_REVERSE = {v: k for k, v in FAN_MODES.items()}

SWING_MODES = [SWING_OFF, SWING_VERTICAL, SWING_HORIZONTAL, SWING_BOTH]

# Target humidity is only meaningful while actively cooling or drying.
HUMIDITY_MODES = (Mode.Cool, Mode.Dry)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Gree Cloud HVAC device from a config entry."""

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Register the device."""
        if is_hwhp_device(coordinator):
            _LOGGER.debug(
                "Skipping climate entity for HWHP device %s",
                coordinator.device.device_info.name,
            )
            return
        async_add_entities([GreeCloudClimateEntity(coordinator)])

    for coordinator in entry.runtime_data.coordinators:
        init_device(coordinator)

    entry.async_on_unload(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeCloudClimateEntity(GreeCloudEntity, ClimateEntity):
    """Representation of a Gree Cloud HVAC device."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_hvac_modes = [*HVAC_MODES_REVERSE, HVACMode.OFF]
    _attr_preset_modes = PRESET_MODES
    _attr_fan_modes = [*FAN_MODES_REVERSE]
    _attr_swing_modes = SWING_MODES
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = TEMP_MIN
    _attr_max_temp = TEMP_MAX

    def __init__(self, coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Initialize the Gree Cloud device."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.device.device_info.mac

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the supported features, adding humidity control in Cool/Dry mode."""
        features = self._attr_supported_features
        if self.coordinator.device.mode in HUMIDITY_MODES:
            features |= ClimateEntityFeature.TARGET_HUMIDITY
        return features

    @property
    def min_humidity(self) -> int:
        """Return the minimum target humidity for the current mode."""
        if self.coordinator.device.mode == Mode.Dry:
            return HUMIDITY_MIN_DRY
        return HUMIDITY_MIN_COOL

    @property
    def max_humidity(self) -> int:
        """Return the maximum target humidity for the current mode."""
        if self.coordinator.device.mode == Mode.Dry:
            return HUMIDITY_MAX_DRY
        return HUMIDITY_MAX_COOL

    @property
    def target_humidity_step(self) -> int:
        """Return the target humidity step; the unit only accepts multiples of 5."""
        return HUMIDITY_STEP

    @property
    def target_humidity(self) -> int | None:
        """Return the target humidity, only meaningful in Cool/Dry mode."""
        if self.coordinator.device.mode not in HUMIDITY_MODES:
            return None
        return self.coordinator.device.target_humidity

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        mode = self.coordinator.device.mode
        if mode not in HUMIDITY_MODES:
            raise ValueError(f"Target humidity can only be set in Cool or Dry mode, not {mode}")

        min_humidity, max_humidity = (
            (HUMIDITY_MIN_DRY, HUMIDITY_MAX_DRY)
            if mode == Mode.Dry
            else (HUMIDITY_MIN_COOL, HUMIDITY_MAX_COOL)
        )
        # target_humidity_step keeps the UI slider on multiples of 5, but a
        # direct service call can still pass an arbitrary value.
        humidity = round(humidity / HUMIDITY_STEP) * HUMIDITY_STEP
        humidity = max(min_humidity, min(humidity, max_humidity))

        _LOGGER.debug(
            "Setting target humidity to %s for %s",
            humidity,
            self._attr_name,
        )

        device = self.coordinator.device
        device.target_humidity = humidity  # Dwet
        # Setting a target implies dehumidify should be on. Dmod has no
        # setter in greeclimate, so it's written directly through
        # raw_properties, the same pattern used for HWHP properties; this
        # takes over from whatever Dmod held before (including Smart
        # Drying), and both go out together in the push below.
        device.raw_properties[PROP_DEHUMIDIFY_MODE] = DEHUMIDIFY_MODE_ON
        if PROP_DEHUMIDIFY_MODE not in device._dirty:
            device._dirty.append(PROP_DEHUMIDIFY_MODE)
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    @property
    def _supports_half_degree(self) -> bool:
        """Return whether this unit supports 0.5C setpoints."""
        return self.coordinator.device.get_property(Props.TEMP_HALF_ENABLED) == 1

    @property
    def precision(self) -> float:
        """Return the display precision, matching the device's actual step."""
        return PRECISION_HALVES if self._supports_half_degree else PRECISION_WHOLE

    @property
    def target_temperature_step(self) -> float:
        """Return the target temperature step, only offering 0.5C where supported."""
        return TARGET_TEMPERATURE_STEP_HALF if self._supports_half_degree else TARGET_TEMPERATURE_STEP

    @property
    def current_temperature(self) -> float:
        """Return the reported current temperature for the device."""
        return self.coordinator.device.current_temperature

    @property
    def target_temperature(self) -> float:
        """Return the target temperature for the device."""
        return self.coordinator.device.target_temperature

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if ATTR_TEMPERATURE not in kwargs:
            raise ValueError(f"Missing parameter {ATTR_TEMPERATURE}")

        if hvac_mode := kwargs.get(ATTR_HVAC_MODE):
            await self.async_set_hvac_mode(hvac_mode)

        temperature = kwargs[ATTR_TEMPERATURE]
        _LOGGER.debug(
            "Setting temperature to %s for %s",
            temperature,
            self._attr_name,
        )

        self.coordinator.device.target_temperature = temperature
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current HVAC mode for the device."""
        if not self.coordinator.device.power:
            return HVACMode.OFF

        return HVAC_MODES.get(self.coordinator.device.mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode not in self.hvac_modes:
            raise ValueError(f"Invalid hvac_mode: {hvac_mode}")

        _LOGGER.debug(
            "Setting HVAC mode to %s for device %s",
            hvac_mode,
            self._attr_name,
        )

        if hvac_mode == HVACMode.OFF:
            self.coordinator.device.power = False
            await self.coordinator.push_state_update()
            self.async_write_ha_state()
            return

        if not self.coordinator.device.power:
            self.coordinator.device.power = True

        self.coordinator.device.mode = HVAC_MODES_REVERSE.get(hvac_mode)
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on the device."""
        _LOGGER.debug("Turning on HVAC for device %s", self._attr_name)

        self.coordinator.device.power = True
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn off the device."""
        _LOGGER.debug("Turning off HVAC for device %s", self._attr_name)

        self.coordinator.device.power = False
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    @property
    def preset_mode(self) -> str:
        """Return the current preset mode for the device."""
        if self.coordinator.device.steady_heat:
            return PRESET_AWAY
        if self.coordinator.device.power_save:
            return PRESET_ECO
        if self.coordinator.device.sleep:
            return PRESET_SLEEP
        if self.coordinator.device.turbo:
            return PRESET_BOOST
        return PRESET_NONE

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if preset_mode not in PRESET_MODES:
            raise ValueError(f"Invalid preset mode: {preset_mode}")

        _LOGGER.debug(
            "Setting preset mode to %s for device %s",
            preset_mode,
            self._attr_name,
        )

        self.coordinator.device.steady_heat = False
        self.coordinator.device.power_save = False
        self.coordinator.device.turbo = False
        self.coordinator.device.sleep = False

        if preset_mode == PRESET_AWAY:
            self.coordinator.device.steady_heat = True
        elif preset_mode == PRESET_ECO:
            self.coordinator.device.power_save = True
        elif preset_mode == PRESET_BOOST:
            self.coordinator.device.turbo = True
        elif preset_mode == PRESET_SLEEP:
            self.coordinator.device.sleep = True

        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode for the device."""
        speed = self.coordinator.device.fan_speed
        return FAN_MODES.get(speed)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        if fan_mode not in FAN_MODES_REVERSE:
            raise ValueError(f"Invalid fan mode: {fan_mode}")

        self.coordinator.device.fan_speed = FAN_MODES_REVERSE.get(fan_mode)
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    @property
    def swing_mode(self) -> str:
        """Return the current swing mode for the device."""
        h_swing = self.coordinator.device.horizontal_swing == HorizontalSwing.FullSwing
        v_swing = self.coordinator.device.vertical_swing == VerticalSwing.FullSwing

        if h_swing and v_swing:
            return SWING_BOTH
        if h_swing:
            return SWING_HORIZONTAL
        if v_swing:
            return SWING_VERTICAL
        return SWING_OFF

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set new target swing operation."""
        if swing_mode not in SWING_MODES:
            raise ValueError(f"Invalid swing mode: {swing_mode}")

        _LOGGER.debug(
            "Setting swing mode to %s for device %s",
            swing_mode,
            self._attr_name,
        )

        self.coordinator.device.horizontal_swing = HorizontalSwing.Center
        self.coordinator.device.vertical_swing = VerticalSwing.FixedMiddle
        if swing_mode in (SWING_BOTH, SWING_HORIZONTAL):
            self.coordinator.device.horizontal_swing = HorizontalSwing.FullSwing
        if swing_mode in (SWING_BOTH, SWING_VERTICAL):
            self.coordinator.device.vertical_swing = VerticalSwing.FullSwing

        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        """Update the state of the entity."""
        units = self.coordinator.device.temperature_units
        if (
            units == TemperatureUnits.C
            and self._attr_temperature_unit != UnitOfTemperature.CELSIUS
        ):
            _LOGGER.debug("Setting temperature unit to Celsius")
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS
            self._attr_min_temp = TEMP_MIN
            self._attr_max_temp = TEMP_MAX
        elif (
            units == TemperatureUnits.F
            and self._attr_temperature_unit != UnitOfTemperature.FAHRENHEIT
        ):
            _LOGGER.debug("Setting temperature unit to Fahrenheit")
            self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
            self._attr_min_temp = TEMP_MIN_F
            self._attr_max_temp = TEMP_MAX_F

        super()._handle_coordinator_update()
