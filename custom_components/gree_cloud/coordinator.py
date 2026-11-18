"""Helper and wrapper classes for Gree Cloud module."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from greeclimate_davo22.cloud_api import GreeCloudApi
from greeclimate_davo22.cloud_device import CloudDevice
from greeclimate_davo22.cloud_gateway import GreeCloudGateway
from greeclimate_davo22.device import Props
from greeclimate_davo22.deviceinfo import DeviceInfo
from greeclimate_davo22.mqtt_client import GreeMqttClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

# Imported lazily at call time to avoid circular import (coordinator <- __init__).
_RECONNECT_FUNC_NAME = "async_reconnect_mqtt"
_RECONNECT_MODULE = __name__.rsplit(".", 1)[0]  # custom_components.gree_cloud

from .const import (
    DISPATCH_DEVICE_DISCOVERED,
    DOMAIN,
    HWHP_PROP_POW_CONSUMP,
    HWHP_PROP_SET_TEM_DEC,
    HWHP_PROP_SET_TEM_INT,
    HWHP_PROP_WATER_PERCENT,
    HWHP_PROP_WATER_TEMP,
    HWHP_ERROR_PROPS,
    HWHP_PROP_BACKUP_HEATER,
    HWHP_PROP_BOTTOM_TEMP,
    HWHP_PROP_COIL_TEMP,
    HWHP_PROP_DEFROST,
    HWHP_PROP_DISCHARGE_TEMP,
    HWHP_PROP_DISINFECT_ON,
    HWHP_PROP_DISINFECT_RUNNING,
    HWHP_PROP_FAN_HIGH,
    HWHP_PROP_FAN_LOW,
    HWHP_PROP_HOLIDAY,
    HWHP_PROP_OUT_EXCHANGER_TEMP,
    HWHP_PROP_OUTDOOR_TEMP,
    HWHP_PROP_PUMP,
    HWHP_PROP_WSTATE,
    MAX_ERRORS,
    POOL_MODEL_ID,
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
    PROP_COMPRESSOR_FREQ,
    PROP_COMPRESSOR_TEMP,
    PROP_ENERGY_TOTAL,
    PROP_OUTDOOR_TEMP,
    PROP_POWER_REDUCE_GEAR,
    PROP_POWER_REDUCE_TYPE,
    PROP_ROOM_TEMP,
    UPDATE_INTERVAL,
)

from .heatpump import (TEMPERATURE_PAIRS, WritePolicy, classify, decode_values, model_profile, prepare_command, status_columns, verify_command_reply, user_control_policy)

_LOGGER = logging.getLogger(__name__)

# Extra raw properties requested from the device in addition to the standard Props enum.
_STANDARD_PROPS: list[str] = [x.value for x in Props]

# Hot Water Heat Pump (HWHP) keys. A unit is a HWHP when it reports ``WatTmp``;
# only then is it asked for the rest of these.
_HWHP_BASE_PROPS = [
    HWHP_PROP_WATER_TEMP,
    HWHP_PROP_SET_TEM_INT,
    HWHP_PROP_SET_TEM_DEC,
    HWHP_PROP_WSTATE,
    HWHP_PROP_POW_CONSUMP,
    HWHP_PROP_WATER_PERCENT,
]
_HWHP_DETAIL_PROPS = [
    HWHP_PROP_BOTTOM_TEMP,
    HWHP_PROP_OUTDOOR_TEMP,
    HWHP_PROP_DISCHARGE_TEMP,
    HWHP_PROP_OUT_EXCHANGER_TEMP,
    HWHP_PROP_COIL_TEMP,
    HWHP_PROP_BACKUP_HEATER,
    HWHP_PROP_FAN_HIGH,
    HWHP_PROP_FAN_LOW,
    HWHP_PROP_DEFROST,
    HWHP_PROP_PUMP,
    HWHP_PROP_DISINFECT_ON,
    HWHP_PROP_DISINFECT_RUNNING,
    HWHP_PROP_HOLIDAY,
    *HWHP_ERROR_PROPS,
]

# Extra properties reported by AC units, surfaced by the sensor platform. The
# cloud serves these even though the local UDP protocol does not, so they are
# only available on this integration.
_SENSOR_EXTRA_PROPS = [
    PROP_ENERGY_TOTAL,
    PROP_COMPRESSOR_FREQ,
    PROP_POWER_REDUCE_GEAR,
    PROP_POWER_REDUCE_TYPE,
    PROP_OUTDOOR_TEMP,
    PROP_COMPRESSOR_TEMP,
]

# Most columns a single status request may carry. Some Wi-Fi modules silently
# drop a longer request: 1.8.0-beta.1 asked every AC for 57 columns and a
# V3.4.M module that had answered the 39 columns of 1.7.x on every poll stopped
# answering altogether. 40 is the longest request 1.7.x ever sent (a unit
# behind a module, first poll). Anything beyond it goes into further requests,
# so think twice before adding a column to what every AC is asked for.
MAX_STATUS_COLUMNS = 40


def _column_chunks(columns: list[str]) -> list[list[str]]:
    """Split *columns* into requests of at most MAX_STATUS_COLUMNS, evenly."""
    count = -(-len(columns) // MAX_STATUS_COLUMNS)
    if count <= 1:
        return [list(columns)]
    size = -(-len(columns) // count)
    return [list(columns[i:i + size]) for i in range(0, len(columns), size)]


# Everything a pool heat pump (model 9302) is asked for. These units answer
# with their whole property set anyway, but the AC columns are meaningless
# for them, so the request is kept to what the entities read (#48).
_POOL_PROPS = [
    Props.POWER.value,
    POOL_PROP_WMOD,
    POOL_PROP_SET_TEM_INT,
    POOL_PROP_SET_TEM_DEC,
    POOL_PROP_IN_TEM_INT,
    POOL_PROP_IN_TEM_DEC,
    POOL_PROP_OUT_TEM_INT,
    POOL_PROP_OUT_TEM_DEC,
    POOL_PROP_HEAT_TEM_MIN,
    POOL_PROP_HEAT_TEM_MAX,
    POOL_PROP_COOL_TEM_MIN,
    POOL_PROP_COOL_TEM_MAX,
    POOL_PROP_FLAG,
    POOL_PROP_FUNC,
    POOL_PROP_PUMP_STATUS,
    POOL_PROP_COMPRESSOR_STATUS,
    POOL_PROP_DEFROST,
    POOL_PROP_AUX_STATUS,
    POOL_PROP_ERROR,
    HWHP_PROP_WSTATE,
]


# A state without any of these is no state: an acknowledgement, a firmware id.
_USABLE_STATE_KEYS = ("Pow", "Mod", "HeWatOutTemSet", "SetTem", "WatTmp")


class HWHPAwareCloudDevice(CloudDevice):
    """CloudDevice subclass that also requests HWHP-specific properties.

    The Gree WHIO Hot Water Heat Pump reports current water temperature under
    the ``WatTem`` property key which is not part of the standard ``Props``
    enum.  This subclass extends the status request with that key so it is
    stored in ``raw_properties`` and can be read by the water_heater entity.

    The same mechanism requests ``ElcAll`` (cumulative energy) for AC units,
    read by the sensor platform.

    Transport (MQTT or the legacy TLS gateway) and the timeout handling live in
    the library; a status poll that gets no answer raises
    ``asyncio.TimeoutError`` so the coordinator can count it (#41).
    """

    def __init__(self, *args: Any, model_id: str | None = None, **kwargs: Any) -> None:
        """Remember the cloud model id (``mid``); it selects the device profile."""
        super().__init__(*args, **kwargs)
        self.model_id = model_id
        self._cooling_observed = False
        self.write_policy = WritePolicy()
        # A heat pump may report its state by itself instead of answering
        # status requests (#75): how often it did, whether a request was ever
        # answered, and who wants to hear about it.
        self.push_count = 0
        self.status_answered = False
        self.push_listener = None
        self._in_mqtt_callback = False

    @property
    def lives_on_pushes(self) -> bool:
        """True for a unit that reports by itself and never answered a request."""
        return self.push_count > 0 and not self.status_answered

    def _handle_mqtt_message(self, topic, message) -> None:
        """Tell what the unit sends by itself from what a request returned.

        The library hands a waiting request whatever arrives first. When a
        second message comes in before the request picks that up, the first
        one is replaced; a heat pump's state must not get lost that way.
        """
        held = self._response_data if self._response_event else None
        self._in_mqtt_callback = True
        try:
            super()._handle_mqtt_message(topic, message)
            if (
                self.is_heat_pump
                and isinstance(held, dict)
                and self._response_data is not held
                and (state := self._decode_dat(held))
            ):
                self.handle_state_update(**state)
        finally:
            self._in_mqtt_callback = False

    def _state_pushed(self) -> None:
        """Take in a state the heat pump sent without being asked (#75).

        A Versati series 1 leaves status requests unanswered and sends its
        whole state by itself. That state decides what the unit is, the same
        way an answer to a request does, and goes straight to the entities.
        """
        self.push_count += 1
        if getattr(self, "device_kind", None) not in ("heatpump", "ac"):
            self.device_kind = classify(self.raw_properties, mid=self.model_id)
        self._refresh_write_policy()
        if self.push_listener is not None:
            self.push_listener()

    @property
    def is_heat_pump(self) -> bool:
        """True for registered air-to-water heat-pump models."""
        return model_profile(self.model_id) is not None


    @property
    def is_pool_heat_pump(self) -> bool:
        """True for swimming-pool heat pumps (model 9302)."""
        return self.model_id == POOL_MODEL_ID

    def _refresh_write_policy(self):
        """Profile selection never sends commands and preserves the cooling evidence."""
        self._cooling_observed |= self.raw_properties.get("Mod") in (3, 5)
        self.write_policy = user_control_policy(
            self.raw_properties, mid=self.model_id, cooling=self._cooling_observed
        ) if getattr(self, "device_kind", "unknown") == "heatpump" else WritePolicy()

    def handle_state_update(self, **kwargs):
        """Never combine Hi/Lo halves from different MQTT messages."""
        if model_profile(self.model_id) is None:
            super().handle_state_update(**kwargs)
            return
        for high, low in TEMPERATURE_PAIRS.values():
            if (high in kwargs) != (low in kwargs):
                self.raw_properties.pop(high, None)
                self.raw_properties.pop(low, None)
                kwargs.pop(high, None)
                kwargs.pop(low, None)
        pushed = self._in_mqtt_callback and any(
            key in kwargs for key in _USABLE_STATE_KEYS
        )
        super().handle_state_update(**kwargs)
        if pushed:
            self._state_pushed()

    async def async_heatpump_command(self, key: str, value: Any) -> dict:
        """One approved write, strict ACK, then readback. Never retry writes."""
        if getattr(self, "device_kind", "unknown") != "heatpump":
            raise HomeAssistantError("Not a supported air-to-water device")
        async with self.request_lock:
            self._refresh_write_policy()
            try:
                command = prepare_command(self.raw_properties, self.write_policy, key, value)
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            pushes = self.push_count

            def pushed() -> bool:
                """The unit reported the new value by itself since the command."""
                return (
                    self.push_count != pushes
                    and self.raw_properties.get(key) == command["p"][0]
                )
            # Only allowlisted user commands can reach the transport.
            try:
                reply = await self.send_command(
                    command["opt"], command["p"], strict_ack=True
                )
                verify_command_reply(reply, key, command["p"][0])
            except (ValueError, asyncio.TimeoutError) as err:
                raise HomeAssistantError("Command not confirmed; it may have executed. No retry.") from err
            # Cloud state can lag behind the ACK, or a late bare ACK can wake
            # the status request. Retry reads only, never the accepted write.
            columns = status_columns(self.raw_properties)
            # A unit that reports by itself (#75) confirms the value that way:
            # its report may end the wait for the acknowledgement, arrive on
            # its own, or end the wait of the readback.
            state = decode_values(reply) if reply.get("t") == "dat" else {}
            data = state if state.get(key) == command["p"][0] else None
            for attempt in range(3):
                if data is not None or pushed():
                    break
                if attempt:
                    await asyncio.sleep(1)
                try:
                    answer = await self.request_status(list(columns))
                except asyncio.TimeoutError:
                    continue
                if isinstance(answer, dict) and answer.get(key) == command["p"][0]:
                    data = answer
            if data is None and not pushed():
                raise HomeAssistantError(
                    "Command acknowledged, but the applied value could not be confirmed. "
                    "It may have executed; the write was not retried."
                )
            if data:
                for column in columns:
                    self.raw_properties.pop(column, None)
                self.handle_state_update(**data)
            return copy.deepcopy(self.raw_properties)

    def _status_columns(self) -> list[str]:
        """Everything this unit is asked for, by the kind of device it is.

        The list is kept as short as the entities allow, because modules drop
        requests that are too long (see MAX_STATUS_COLUMNS). A unit that
        reports ``WatTmp`` is a hot water heat pump and gets the standard and
        the HWHP keys. Anything else, including a unit that has not answered
        yet, is treated as an AC: standard keys, the AC sensors, and ``WatTmp``
        alone, which is how a HWHP gives itself away.
        """
        if self.is_heat_pump:
            return list(status_columns(self.raw_properties))
        if self.is_pool_heat_pump:
            return list(_POOL_PROPS)
        water = self.raw_properties.get(HWHP_PROP_WATER_TEMP)
        if isinstance(water, (int, float)) and water > 0:
            columns = _HWHP_BASE_PROPS + _STANDARD_PROPS + _HWHP_DETAIL_PROPS
        else:
            columns = _STANDARD_PROPS + [HWHP_PROP_WATER_TEMP] + _SENSOR_EXTRA_PROPS
        if self.is_sub_device:
            columns = [*columns, PROP_ROOM_TEMP]
        return columns

    async def _update_in_chunks(self) -> None:
        """Poll an AC, HWHP or pool unit without ever sending a long request.

        An AC is covered by a single request. A HWHP has more columns than fit
        into one: the first request decides whether the poll succeeded and the
        rest is asked for afterwards, unless the unit sent it along already. A
        follow-up that goes unanswered does not fail the poll.

        The list is drawn up again after the first answer, because that answer
        may be the one that shows the unit to be a HWHP, and the platforms
        create entities for the properties present after the first refresh.
        """
        def columns() -> list[str]:
            wanted = self._status_columns()
            return wanted if self.hid else [*wanted, "hid"]

        first = _column_chunks(columns())[0]
        try:
            data = dict(await self.request_status(first) or {})
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Timeout waiting for state update from %s", self.device_info.name
            )
            raise
        if data:
            self.handle_state_update(**data)
        rest = [c for c in columns() if c not in first and c not in data]
        if not rest:
            return
        for chunk in _column_chunks(rest):
            try:
                more = await self.request_status(chunk)
            except asyncio.TimeoutError:
                _LOGGER.debug(
                    "%s did not answer the follow-up request for %s",
                    self.device_info.name, chunk,
                )
                break
            if more:
                self.handle_state_update(**more)

    async def update_state(self) -> None:
        """Read only; reject empty acknowledgements instead of reporting success."""
        if model_profile(self.model_id) is None:
            self.device_kind = "ac"
            await self._update_in_chunks()
            return
        async with self.request_lock:
            requested = self._status_columns()
            data = await self.request_status(requested)
            if isinstance(data, dict) and classify(data, mid=self.model_id) == "unknown":
                if not getattr(self, "_unknown_profile_warned", False):
                    _LOGGER.warning(
                        "Model %s has fewer than two usable hydraulic setpoints; "
                        "the heat-pump profile cannot be recognized from this poll. "
                        "Received columns: %s",
                        self.model_id, ", ".join(sorted(data)) or "(none)",
                    )
                    self._unknown_profile_warned = True
            else:
                self._unknown_profile_warned = False
            if not isinstance(data, dict) or not data or not any(
                key in data for key in _USABLE_STATE_KEYS
            ):
                raise ValueError("Cloud returned no usable device state")
            # An answer holds what was asked for. Anything else that ended the
            # wait is a state the unit sent by itself (#75).
            if set(data) <= {*requested, "hid"}:
                self.status_answered = True
            else:
                self.push_count += 1
            # A missing field in the latest poll is unknown, not a stale reading.
            if getattr(self, "device_kind", "unknown") != "ac":
                for key in self._status_columns():
                    self.raw_properties.pop(key, None)
            self.handle_state_update(**data)
            detected = classify(self.raw_properties, mid=self.model_id)
            if getattr(self, "device_kind", None) not in ("heatpump", "ac"):
                self.device_kind = detected
            self._refresh_write_policy()

    @property
    def request_lock(self) -> asyncio.Lock:
        """Serialize requests: the library has a single response event per device."""
        if not hasattr(self, "_request_lock"):
            self._request_lock = asyncio.Lock()
        return self._request_lock

    async def push_state_update(self):
        """Never send AC commands to a registered air-to-water heat pump."""
        if model_profile(self.model_id) is not None:
            raise HomeAssistantError("This model requires the air-to-water command path")
        return await super().push_state_update()


def is_heatpump_device(coordinator: "CloudDeviceDataUpdateCoordinator") -> bool:
    """Return True for a registered air-to-water model, including unknown profiles."""
    return bool(getattr(coordinator.device, "is_heat_pump", False))


def is_pool_device(coordinator: "CloudDeviceDataUpdateCoordinator") -> bool:
    """Return True if the device is a swimming-pool heat pump (model 9302)."""
    return bool(getattr(coordinator.device, "is_pool_heat_pump", False))


def is_hwhp_device(coordinator: "CloudDeviceDataUpdateCoordinator") -> bool:
    """Return True if the device appears to be a Hot Water Heat Pump.

    Detection requires a positive WatTmp raw value (actual = raw - 100).
    Standard AC units return 0 for unknown properties; a real HWHP reports
    actual water temperature (40–80 °C → raw 140–180), so raw > 0 is the
    discriminator.
    """
    if is_heatpump_device(coordinator):
        return False
    raw = coordinator.device.raw_properties.get(HWHP_PROP_WATER_TEMP)
    return raw is not None and raw > 0


def _is_mqtt_disconnected(error: Exception) -> bool:
    """Return True if *error* indicates the MQTT client is not connected."""
    msg = str(error).lower()
    return any(m in msg for m in ("code:4", "not currently connected", "not connected"))


async def _try_reconnect(hass: HomeAssistant, entry: "GreeCloudConfigEntry") -> bool:
    """Lazy-import and call async_reconnect_mqtt to avoid circular imports."""
    import importlib
    mod = importlib.import_module(_RECONNECT_MODULE)
    return await mod.async_reconnect_mqtt(hass, entry)


type GreeCloudConfigEntry = ConfigEntry[GreeCloudRuntimeData]


@dataclass
class GreeCloudRuntimeData:
    """Runtime data for Gree Climate Cloud integration."""

    cloud_api: GreeCloudApi
    mqtt_client: GreeMqttClient
    coordinators: list[CloudDeviceDataUpdateCoordinator]
    gateway: GreeCloudGateway | None = None
    mqtt_reconnect_lock: asyncio.Lock = None

    def __post_init__(self) -> None:
        """Initialise fields that need a running event loop."""
        if self.mqtt_reconnect_lock is None:
            self.mqtt_reconnect_lock = asyncio.Lock()


class CloudDeviceDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages polling for state changes from cloud devices."""

    config_entry: GreeCloudConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GreeCloudConfigEntry,
        device: CloudDevice,
    ) -> None:
        """Initialize the cloud data update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-{device.device_info.name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
            always_update=False,
        )
        self.device = device
        self._error_count: int = 0
        self._unsub_late_announce = None
        if getattr(device, "is_heat_pump", False):
            device.push_listener = self._state_pushed

    @callback
    def _state_pushed(self) -> None:
        """Publish the state a heat pump sent by itself (#75)."""
        self._error_count = 0
        self.async_set_updated_data(copy.deepcopy(self.device.raw_properties))

    @callback
    def async_announce(self) -> None:
        """Tell the platforms about the device so they create its entities.

        A heat pump gets its entities once its state shows what it is. One
        that could not be recognised yet (no answer to the first poll) is
        polled on and announced again when it is, instead of staying without
        entities until the next restart (#75).
        """
        async_dispatcher_send(self.hass, DISPATCH_DEVICE_DISCOVERED, self)
        if (
            is_heatpump_device(self)
            and self.device_kind != "heatpump"
            and self._unsub_late_announce is None
        ):
            self._unsub_late_announce = self.async_add_listener(
                self._announce_when_recognised
            )
            self.config_entry.async_on_unload(self._cancel_late_announce)

    @callback
    def _cancel_late_announce(self) -> None:
        if self._unsub_late_announce is not None:
            self._unsub_late_announce()
            self._unsub_late_announce = None

    @callback
    def _announce_when_recognised(self) -> None:
        if self.device_kind != "heatpump":
            return
        _LOGGER.info(
            "%s recognised as an air-to-water heat pump; creating its entities",
            self.name,
        )
        async_dispatcher_send(self.hass, DISPATCH_DEVICE_DISCOVERED, self)
        self._cancel_late_announce()

    def _pushed_state(self, reason: Any) -> dict[str, Any] | None:
        """The last state of a unit that reports by itself, or None for any other.

        Such a unit leaves status requests unanswered (#75), so an unanswered
        poll says nothing about it being reachable.
        """
        if not getattr(self.device, "lives_on_pushes", False):
            return None
        _LOGGER.debug(
            "%s left the status request unanswered (%s); keeping the state it "
            "reported by itself",
            self.name,
            reason or "timeout",
        )
        return copy.deepcopy(self.device.raw_properties)

    async def async_heatpump_command(self, key: str, value: Any) -> None:
        """Native entity command path, no optimistic state and no automatic retry."""
        data = await self.device.async_heatpump_command(key, value)
        self.async_set_updated_data(data)

    @property
    def device_kind(self) -> str:
        """The device profile determined from actual cloud data."""
        return getattr(
            self.device,
            "device_kind",
            "unknown" if model_profile(getattr(self.device, "model_id", None)) else "ac",
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update the state of the device from cloud."""
        _LOGGER.debug(
            "Updating cloud device state: %s, error count: %d",
            self.name,
            self._error_count,
        )
        try:
            await self.device.update_state()
            self._error_count = 0
            _LOGGER.debug(
                "Raw properties for %s: %s", self.name, self.device.raw_properties
            )
            return copy.deepcopy(self.device.raw_properties)

        except asyncio.TimeoutError as error:
            if (pushed := self._pushed_state(error)) is not None:
                return pushed
            self._error_count += 1
            if self._error_count >= MAX_ERRORS:
                # Once per outage; a unit that stays away is polled on.
                _LOGGER.log(
                    logging.WARNING if self._error_count == MAX_ERRORS else logging.DEBUG,
                    "Cloud device %s is unavailable after %d timeouts",
                    self.name,
                    self._error_count,
                )
                raise UpdateFailed(
                    f"Cloud device {self.name} is unavailable, timeout"
                ) from error
            if not self.device.has_valid_state and not is_heatpump_device(self):
                # Never heard from since the start: there is no last state to
                # keep, only the library's defaults, which would show as "off".
                # (A heat pump has no entities before its first state.)
                raise UpdateFailed(
                    f"Cloud device {self.name} has not answered yet"
                ) from error
            # Return last known state if within error threshold
            return copy.deepcopy(self.device.raw_properties)

        except Exception as error:
            # Somebody else's reply ended the wait (the app is open).
            if isinstance(error, ValueError) and (
                pushed := self._pushed_state(error)
            ) is not None:
                return pushed
            if _is_mqtt_disconnected(error):
                _LOGGER.warning(
                    "MQTT disconnected while updating %s — triggering reconnect",
                    self.name,
                )
                reconnected = await _try_reconnect(self.hass, self.config_entry)
                if reconnected:
                    try:
                        await self.device.update_state()
                        self._error_count = 0
                        return copy.deepcopy(self.device.raw_properties)
                    except Exception as retry_error:
                        _LOGGER.warning(
                            "State update failed after reconnect for %s: %s",
                            self.name,
                            retry_error,
                        )

            self._error_count += 1
            _LOGGER.exception("Error updating cloud device %s: %s", self.name, error)
            if self._error_count >= MAX_ERRORS:
                raise UpdateFailed(
                    f"Cloud device {self.name} failed to update"
                ) from error
            return copy.deepcopy(self.device.raw_properties)

    async def push_state_update(self):
        """Send state updates to the cloud device."""
        try:
            return await self.device.push_state_update()
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Timeout sending state update to cloud device: %s", self.name
            )
        except Exception as error:
            if _is_mqtt_disconnected(error):
                _LOGGER.warning(
                    "MQTT disconnected while pushing state to %s — triggering reconnect",
                    self.name,
                )
                # Reconnecting reads every unit again, which would replace
                # what is about to be sent by what the unit still holds.
                pending = {
                    name: self.device.raw_properties.get(name)
                    for name in self.device._dirty
                }
                reconnected = await _try_reconnect(self.hass, self.config_entry)
                if reconnected:
                    self.device.raw_properties.update(pending)
                    try:
                        return await self.device.push_state_update()
                    except Exception as retry_error:
                        _LOGGER.warning(
                            "Push state failed after reconnect for %s: %s",
                            self.name,
                            retry_error,
                        )
                        return
            _LOGGER.exception(
                "Error sending state update to cloud device %s: %s", self.name, error
            )


class CloudDiscoveryService:
    """Cloud discovery service for Gree devices."""

    def __init__(
        self, hass: HomeAssistant, entry: GreeCloudConfigEntry, api: GreeCloudApi
    ) -> None:
        """Initialize cloud discovery service."""
        self.hass = hass
        self.entry = entry
        self.api = api

    async def discover_devices(
        self, mqtt_client: GreeMqttClient, gateway: GreeCloudGateway | None = None
    ) -> list[CloudDeviceDataUpdateCoordinator]:
        """Discover all cloud devices.

        Each device picks its transport from the protocol version in its cloud
        record: MQTT for ``ver`` >= 3.2, the legacy TLS gateway otherwise
        (only when *gateway* is given).
        """
        # Shared with the platforms: a coordinator is appended as soon as its
        # device exists, and the DISPATCH_DEVICE_DISCOVERED signal tells the
        # platforms (already set up) to create the entities.
        coordinators = self.entry.runtime_data.coordinators

        try:
            # Get all devices from cloud
            _LOGGER.debug("Fetching devices from Gree Cloud")
            cloud_devices = await self.api.get_all_devices()

            _LOGGER.info("Found %d cloud devices", len(cloud_devices))

            # Create coordinator for each device
            for cloud_dev_info in cloud_devices:
                try:
                    # Create DeviceInfo for CloudDevice
                    device_info = DeviceInfo(
                        ip="0.0.0.0",  # Not used for cloud devices
                        port=0,  # Not used for cloud devices
                        mac=cloud_dev_info.mac,
                        name=cloud_dev_info.name,
                        model=cloud_dev_info.model,
                        version=cloud_dev_info.version,
                    )

                    # Create cloud device instance
                    device = HWHPAwareCloudDevice(
                        mqtt_client=mqtt_client,
                        device_info=device_info,
                        device_key=cloud_dev_info.key,
                        cipher_version=1,  # Default to v1, can be made configurable
                        gateway=gateway,
                        # Module MAC from the cloud record (pmac); indoor units
                        # of multi-head systems are reached through it (#6, #33).
                        parent_mac=cloud_dev_info.parent_mac,
                        model_id=cloud_dev_info.mid,
                    )

                    # Bind to cloud device (subscribe to MQTT topics). A unit
                    # that does not answer now is kept anyway: its entities
                    # come up unavailable and the regular polls keep trying,
                    # so a slow or busy controller recovers without a restart
                    # (#6). Only a failure to create the device drops it.
                    # A heat pump raises ValueError for an answer that holds
                    # no state, which is no reason to drop it either (#75).
                    try:
                        await device.bind()
                    except (asyncio.TimeoutError, ValueError) as err:
                        _LOGGER.warning(
                            "Cloud device %s did not answer during setup (%s); "
                            "keeping it and retrying on the next polls",
                            device.device_info.name,
                            str(err) or "no answer",
                        )
                    else:
                        _LOGGER.info(
                            "Bound to cloud device: %s (MAC: %s, module: %s, firmware: %s, "
                            "transport: %s, addressing: %s)",
                            device.device_info.name,
                            device.device_info.mac,
                            device._parent_mac,
                            cloud_dev_info.version,
                            device.transport,
                            device.addressing,
                        )

                    # Create coordinator
                    coordinator = CloudDeviceDataUpdateCoordinator(
                        self.hass, self.entry, device
                    )
                    coordinators.append(coordinator)

                    # Initial refresh. Discovery runs after the entry is
                    # loaded, so this is a plain refresh, not the
                    # config-entry first refresh. A failure leaves the
                    # entities unavailable until a poll succeeds; it does
                    # not drop the device.
                    await coordinator.async_refresh()
                    if not coordinator.last_update_success:
                        _LOGGER.warning(
                            "First poll of %s failed; entities start unavailable",
                            device.device_info.name,
                        )

                    # Notify about discovered device
                    coordinator.async_announce()

                except Exception as err:
                    _LOGGER.exception(
                        "Failed to setup cloud device %s: %s",
                        cloud_dev_info.name,
                        err,
                    )

        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.exception("Failed to discover cloud devices: %s", err)

        _LOGGER.info("Successfully discovered %d cloud devices", len(coordinators))
        return coordinators
