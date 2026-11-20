"""Hot water: Gree Cloud Hot Water Heat Pumps (HWHP) and the tank of a Versati."""

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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DISPATCH_DEVICE_DISCOVERED,
    HWHP_OPERATION_BOOST,
    HWHP_OPERATION_HEAT_PUMP,
    HWHP_PROP_POW_CONSUMP,
    HWHP_PROP_SET_TEM_DEC,
    HWHP_PROP_SET_TEM_INT,
    HWHP_PROP_WATER_PERCENT,
    HWHP_PROP_WATER_TEMP,
    HWHP_PROP_WMOD,
    HWHP_PROP_WSTATE,
    HWHP_TEMP_ENCODING_OFFSET,
    HWHP_TEMP_MAX,
    HWHP_TEMP_MIN,
    HWHP_WMOD_BOOST,
    HWHP_WMOD_HEAT_PUMP,
)
from .coordinator import (
    CloudDeviceDataUpdateCoordinator,
    GreeCloudConfigEntry,
    is_heatpump_device,
    is_hwhp_device,
)
from .entity import GreeCloudEntity
from .heatpump import HOT_WATER_MODES, setpoint, temperature

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
    """Set up Gree Cloud water heaters from a config entry."""
    hot_water_tanks: set[str] = set()

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Register the device if it is an HWHP or a heat pump with a tank."""
        if is_heatpump_device(coordinator):
            if coordinator.device_kind != "heatpump":
                return

            @callback
            def add_hot_water() -> None:
                """Once the unit reports a tank sensor and a hot water target."""
                mac = coordinator.device.device_info.mac
                if mac in hot_water_tanks or not has_hot_water_tank(
                    coordinator.data or {}, coordinator.device.write_policy
                ):
                    return
                hot_water_tanks.add(mac)
                async_add_entities([GreeHeatPumpWaterHeater(coordinator)])

            add_hot_water()
            entry.async_on_unload(coordinator.async_add_listener(add_hot_water))
            return
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


def has_hot_water_tank(props, policy) -> bool:
    """Whether the unit has a tank sensor and a hot water target that may be set."""
    return (
        temperature(props, "dhw_temperature") is not None
        and "WatBoxTemSet" in policy.approved
        and "WatBoxTemSet" in policy.limits
    )


class GreeHeatPumpWaterHeater(GreeCloudEntity, WaterHeaterEntity):
    """The hot water tank of a Versati: its temperature and its target (#75).

    Whether hot water is made at all is part of the unit's mode. On a unit
    with the Rapid function the operation sets both: off takes hot water out
    of the mode, the other two put it in, with or without Rapid. The unit's
    power is never touched from here.
    """

    _attr_translation_key = "versati_dhw"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS  # Home Assistant before 2026.11
    _attr_target_temperature_step = 1
    _attr_supported_features = WaterHeaterEntityFeature.TARGET_TEMPERATURE

    _setpoint_key = "WatBoxTemSet"
    # Hot water joins or leaves the mode: Heat <-> Heat + hot water,
    # Cool <-> Cool + hot water.
    _with_hot_water = {1: 4, 5: 3}
    _without_hot_water = {4: 1, 3: 5}

    def __init__(self, coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.device.device_info.mac}_{self._attr_translation_key}"
        )

    @property
    def _sets_operation(self) -> bool:
        """A unit with the Rapid function whose mode may be set (#75)."""
        approved = self.coordinator.device.write_policy.approved
        return "Mod" in approved and "FastHtWter" in approved

    @property
    def supported_features(self) -> WaterHeaterEntityFeature:
        policy = self.coordinator.device.write_policy
        features = WaterHeaterEntityFeature(0)
        if self._setpoint_key in policy.approved and self._setpoint_key in policy.limits:
            features |= WaterHeaterEntityFeature.TARGET_TEMPERATURE
        if self._sets_operation:
            features |= (
                WaterHeaterEntityFeature.OPERATION_MODE | WaterHeaterEntityFeature.ON_OFF
            )
        return features

    @property
    def operation_list(self) -> list[str] | None:
        if not self._sets_operation:
            return None
        return [STATE_OFF, STATE_HEAT_PUMP, STATE_PERFORMANCE]

    @property
    def _limits(self) -> tuple[float, float]:
        return self.coordinator.device.write_policy.limits.get(self._setpoint_key, (40, 60))

    @property
    def min_temp(self) -> float:
        return self._limits[0]

    @property
    def max_temp(self) -> float:
        return self._limits[1]

    @property
    def native_current_temperature(self) -> float | None:
        return temperature(self.coordinator.data or {}, "dhw_temperature")

    @property
    def native_target_temperature(self) -> float | None:
        return setpoint(self.coordinator.data or {}, self._setpoint_key)

    # Home Assistant before 2026.11 reads the temperatures by these names
    current_temperature = native_current_temperature
    target_temperature = native_target_temperature

    @property
    def current_operation(self) -> str | None:
        props = self.coordinator.data or {}
        if props.get("Pow") == 0:
            return STATE_OFF
        if props.get("Pow") != 1:
            return None
        mode = props.get("Mod")
        if mode in HOT_WATER_MODES:
            if self._sets_operation and props.get("FastHtWter") == 1:
                return STATE_PERFORMANCE
            return STATE_HEAT_PUMP
        # Heating or cooling only: the unit runs, the hot water does not.
        return STATE_OFF if mode in (1, 5) else None

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode not in (self.operation_list or ()):
            raise HomeAssistantError(f"Unsupported operation {operation_mode}")
        props = self.coordinator.data or {}
        mode = props.get("Mod")
        if operation_mode == STATE_OFF:
            if self.current_operation == STATE_OFF:
                return
            await self._async_change_mode(
                self._without_hot_water.get(mode),
                "In Hot water mode the heat pump makes nothing else; "
                "switch the heat pump off instead",
            )
            return
        if props.get("Pow") != 1:
            raise HomeAssistantError("The heat pump is off; switch it on first")
        if mode not in HOT_WATER_MODES:
            await self._async_change_mode(
                self._with_hot_water.get(mode),
                "The unit has no mode that adds hot water to its current one",
            )
        rapid = int(operation_mode == STATE_PERFORMANCE)
        if (self.coordinator.data or {}).get("FastHtWter") != rapid:
            await self.coordinator.async_heatpump_command("FastHtWter", rapid)

    async def _async_change_mode(self, mode: int | None, refusal: str) -> None:
        if mode not in self.coordinator.device.write_policy.modes:
            raise HomeAssistantError(refusal)
        await self.coordinator.async_heatpump_command("Mod", mode)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.current_operation in (STATE_HEAT_PUMP, STATE_PERFORMANCE):
            return
        await self.async_set_operation_mode(STATE_HEAT_PUMP)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_set_operation_mode(STATE_OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE not in kwargs:
            raise HomeAssistantError(f"Missing parameter {ATTR_TEMPERATURE}")
        await self.coordinator.async_heatpump_command(
            self._setpoint_key, kwargs[ATTR_TEMPERATURE]
        )


class GreeCloudWaterHeaterEntity(GreeCloudEntity, WaterHeaterEntity):
    """Representation of a Gree Cloud Hot Water Heat Pump."""

    _attr_precision = PRECISION_WHOLE
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS  # Home Assistant before 2026.11
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
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return HWHP-specific state attributes."""
        props = self.coordinator.device.raw_properties
        attrs: dict[str, Any] = {}

        wstate = props.get(HWHP_PROP_WSTATE)
        if wstate is not None:
            attrs["heating_status"] = "heating" if wstate == 1 else "keep_warm"

        pow_consump = props.get(HWHP_PROP_POW_CONSUMP)
        if pow_consump is not None:
            attrs["power_consumption"] = pow_consump

        # Devices that do not support Watpercent answer 0 for it; skip that
        # instead of reporting -100 %.
        water_percent_raw = props.get(HWHP_PROP_WATER_PERCENT)
        if (
            water_percent_raw is not None
            and water_percent_raw >= HWHP_TEMP_ENCODING_OFFSET
        ):
            attrs["water_level_percent"] = water_percent_raw - HWHP_TEMP_ENCODING_OFFSET

        return attrs

    @property
    def native_current_temperature(self) -> float | None:
        """Return the current water temperature reported by the device."""
        raw = self.coordinator.device.raw_properties.get(HWHP_PROP_WATER_TEMP)
        if raw is None:
            return None
        return raw - HWHP_TEMP_ENCODING_OFFSET

    @property
    def native_target_temperature(self) -> float | None:
        """Return the target water temperature."""
        props = self.coordinator.device.raw_properties
        int_part = props.get(HWHP_PROP_SET_TEM_INT)
        if int_part is None:
            return None
        dec_part = props.get(HWHP_PROP_SET_TEM_DEC, 0)
        return int_part + dec_part / 10

    # Home Assistant before 2026.11 reads the temperatures by these names
    current_temperature = native_current_temperature
    target_temperature = native_target_temperature

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

        # Do NOT use device.target_temperature setter — it validates against
        # AC temperature limits (8–30°C) and will reject HWHP temperatures.
        # Write directly to raw_properties and mark dirty so push_state_update
        # sends SetTemInt/SetTemDec via MQTT.
        device = self.coordinator.device
        device.raw_properties[HWHP_PROP_SET_TEM_INT] = int(temperature)
        device.raw_properties[HWHP_PROP_SET_TEM_DEC] = 0
        for key in (HWHP_PROP_SET_TEM_INT, HWHP_PROP_SET_TEM_DEC):
            if key not in device._dirty:
                device._dirty.append(key)
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    @property
    def current_operation(self) -> str:
        """Return the current operation mode."""
        if not self.coordinator.device.power:
            return STATE_OFF
        wmod = self.coordinator.device.raw_properties.get(HWHP_PROP_WMOD)
        if wmod == HWHP_WMOD_BOOST:
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

        device = self.coordinator.device
        if operation_mode == STATE_OFF:
            device.power = False
        else:
            device.power = True
            wmod = HWHP_WMOD_BOOST if operation_mode == HWHP_OPERATION_BOOST else HWHP_WMOD_HEAT_PUMP
            device.raw_properties[HWHP_PROP_WMOD] = wmod
            if HWHP_PROP_WMOD not in device._dirty:
                device._dirty.append(HWHP_PROP_WMOD)

        await self.coordinator.push_state_update()
        self.async_write_ha_state()
