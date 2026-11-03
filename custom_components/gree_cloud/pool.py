"""Gree swimming-pool heat pumps (cloud model 9302).

Protocol mapped from live captures in #48 (GRS-CP11Pd/NbA-K, module V3.2.M):

- ``Pow`` 0/1, ``Wmod`` 0 = heat / 1 = cool / 2 = auto
- setpoint ``SetTemInt`` + ``SetTemDec`` (0 or 5 tenths): 35.5 C -> 35 / 5
- water inlet ``InTemInt``/``InTemDec`` and outlet ``OutTemInt``/``OutTemDec``,
  integer part offset by 100: 120 / 5 -> 20.5 C
- setpoint limits ``HeatTemMin``/``HeatTemMax`` and ``CoolTemMin``/``CoolTemMax``,
  same +100 offset
- every command the Gree+ app sends carries ``FlagPool`` = 1 in front
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_HALVES, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError

from .const import (
    POOL_PROP_AUX_STATUS,
    POOL_PROP_COMPRESSOR_STATUS,
    POOL_PROP_COOL_TEM_MAX,
    POOL_PROP_COOL_TEM_MIN,
    POOL_PROP_DEFROST,
    POOL_PROP_ERROR,
    POOL_PROP_FLAG,
    POOL_PROP_FUNC,
    POOL_PROP_HEAT_TEM_MAX,
    POOL_PROP_HEAT_TEM_MIN,
    POOL_PROP_IN_TEM_DEC,
    POOL_PROP_IN_TEM_INT,
    POOL_PROP_OUT_TEM_DEC,
    POOL_PROP_OUT_TEM_INT,
    POOL_PROP_PUMP_STATUS,
    POOL_PROP_SET_TEM_DEC,
    POOL_PROP_SET_TEM_INT,
    POOL_PROP_WMOD,
    POOL_TEMP_MAX_DEFAULT,
    POOL_TEMP_MIN_DEFAULT,
    POOL_TEMP_OFFSET,
    POOL_WMOD_AUTO,
    POOL_WMOD_COOL,
    POOL_WMOD_HEAT,
)
from .coordinator import CloudDeviceDataUpdateCoordinator
from .entity import GreeCloudEntity

_LOGGER = logging.getLogger(__name__)

_WMOD_TO_HVAC = {
    POOL_WMOD_HEAT: HVACMode.HEAT,
    POOL_WMOD_COOL: HVACMode.COOL,
    POOL_WMOD_AUTO: HVACMode.AUTO,
}
_HVAC_TO_WMOD = {mode: wmod for wmod, mode in _WMOD_TO_HVAC.items()}

_COMMAND_TIMEOUT = 10.0


def _number(value: Any) -> float | None:
    """Return *value* as a number, or None for anything that is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def pool_temperature(props: Mapping[str, Any], int_key: str, dec_key: str | None = None) -> float | None:
    """Decode a +100 offset temperature with an optional tenths key.

    A missing or zero integer part means the unit did not report it (a
    reading of exactly -100 C is not a thing).
    """
    whole = _number(props.get(int_key))
    if whole is None or whole <= 0:
        return None
    tenths = _number(props.get(dec_key)) if dec_key else None
    return round(whole - POOL_TEMP_OFFSET + (tenths or 0) / 10, 1)


class GreeCloudPoolClimateEntity(GreeCloudEntity, ClimateEntity):
    """Swimming-pool heat pump as a climate entity: heat / cool / auto with a water setpoint."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
    _attr_name = None
    _attr_translation_key = "pool"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_precision = PRECISION_HALVES

    def __init__(self, coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.device.device_info.mac

    @property
    def _props(self) -> Mapping[str, Any]:
        return self.coordinator.device.raw_properties

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Off when powered down, else the water mode."""
        if _number(self._props.get("Pow")) == 0:
            return HVACMode.OFF
        wmod = _number(self._props.get(POOL_PROP_WMOD))
        return _WMOD_TO_HVAC.get(int(wmod)) if wmod is not None else None

    @property
    def hvac_action(self) -> HVACAction | None:
        """Derived from the compressor and defrost flags."""
        if _number(self._props.get("Pow")) == 0:
            return HVACAction.OFF
        if _number(self._props.get(POOL_PROP_DEFROST)) == 1:
            return HVACAction.DEFROSTING
        if _number(self._props.get(POOL_PROP_COMPRESSOR_STATUS)) != 1:
            return HVACAction.IDLE
        mode = self.hvac_mode
        if mode == HVACMode.COOL:
            return HVACAction.COOLING
        if mode == HVACMode.HEAT:
            return HVACAction.HEATING
        # Auto: the compressor runs toward the setpoint from whichever side.
        current, target = self.current_temperature, self.target_temperature
        if current is not None and target is not None and current > target:
            return HVACAction.COOLING
        return HVACAction.HEATING

    @property
    def current_temperature(self) -> float | None:
        """Water inlet temperature (the pool side)."""
        return pool_temperature(self._props, POOL_PROP_IN_TEM_INT, POOL_PROP_IN_TEM_DEC)

    @property
    def target_temperature(self) -> float | None:
        """Setpoint from SetTemInt + SetTemDec tenths."""
        whole = _number(self._props.get(POOL_PROP_SET_TEM_INT))
        if whole is None or whole <= 0:
            return None
        tenths = _number(self._props.get(POOL_PROP_SET_TEM_DEC)) or 0
        return round(whole + tenths / 10, 1)

    def _limits(self) -> tuple[float, float]:
        """Setpoint limits for the current mode, as reported by the unit."""
        heat = (
            pool_temperature(self._props, POOL_PROP_HEAT_TEM_MIN),
            pool_temperature(self._props, POOL_PROP_HEAT_TEM_MAX),
        )
        cool = (
            pool_temperature(self._props, POOL_PROP_COOL_TEM_MIN),
            pool_temperature(self._props, POOL_PROP_COOL_TEM_MAX),
        )
        mode = self.hvac_mode
        if mode == HVACMode.COOL:
            candidates = [cool]
        elif mode == HVACMode.HEAT:
            candidates = [heat]
        else:
            candidates = [heat, cool]
        lows = [c[0] for c in candidates if c[0] is not None]
        highs = [c[1] for c in candidates if c[1] is not None]
        return (
            min(lows) if lows else POOL_TEMP_MIN_DEFAULT,
            max(highs) if highs else POOL_TEMP_MAX_DEFAULT,
        )

    @property
    def min_temp(self) -> float:
        """Lowest allowed setpoint."""
        return self._limits()[0]

    @property
    def max_temp(self) -> float:
        """Highest allowed setpoint."""
        return self._limits()[1]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Outlet temperature and the unit's status flags."""
        props = self._props
        return {
            "water_outlet_temperature": pool_temperature(props, POOL_PROP_OUT_TEM_INT, POOL_PROP_OUT_TEM_DEC),
            "pump_running": _number(props.get(POOL_PROP_PUMP_STATUS)) == 1,
            "compressor_running": _number(props.get(POOL_PROP_COMPRESSOR_STATUS)) == 1,
            "defrosting": _number(props.get(POOL_PROP_DEFROST)) == 1,
            "aux_status": props.get(POOL_PROP_AUX_STATUS),
            "pool_function": props.get(POOL_PROP_FUNC),
            "error_code": props.get(POOL_PROP_ERROR),
        }

    async def _send(self, opt: list[str], p: list[Any]) -> None:
        """Send one command with FlagPool in front, as the app does, and wait for the ack."""
        device = self.coordinator.device
        try:
            reply = await device.send_command(
                [POOL_PROP_FLAG, *opt], [1, *p], strict_ack=True, timeout=_COMMAND_TIMEOUT
            )
        except asyncio.TimeoutError as err:
            raise HomeAssistantError(
                f"{device.device_info.name} did not acknowledge the command"
            ) from err
        except Exception as err:  # transport errors (MQTT disconnected, ...)
            raise HomeAssistantError(
                f"Could not send the command to {device.device_info.name}: {err}"
            ) from err
        if isinstance(reply, dict) and reply.get("r") not in (None, 200):
            raise HomeAssistantError(
                f"{device.device_info.name} rejected the command (r={reply.get('r')})"
            )
        # Reflect the accepted values right away; the next poll confirms them.
        for key, value in zip(opt, p):
            device.raw_properties[key] = value
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the water setpoint in 0.5 C steps."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        low, high = self._limits()
        temperature = max(low, min(float(temperature), high))
        whole = int(temperature)
        tenths = 5 if temperature - whole >= 0.5 else 0
        await self._send([POOL_PROP_SET_TEM_INT, POOL_PROP_SET_TEM_DEC], [whole, tenths])

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Power off, or power on and select heat / cool / auto."""
        if hvac_mode == HVACMode.OFF:
            await self._send(["Pow"], [0])
            return
        wmod = _HVAC_TO_WMOD.get(hvac_mode)
        if wmod is None:
            raise HomeAssistantError(f"Unsupported mode for a pool heat pump: {hvac_mode}")
        if _number(self._props.get(POOL_PROP_WMOD)) != wmod:
            await self._send([POOL_PROP_WMOD], [wmod])
        if _number(self._props.get("Pow")) != 1:
            await self._send(["Pow"], [1])

    async def async_turn_on(self) -> None:
        """Power on in the unit's current water mode."""
        await self._send(["Pow"], [1])

    async def async_turn_off(self) -> None:
        """Power off."""
        await self._send(["Pow"], [0])
