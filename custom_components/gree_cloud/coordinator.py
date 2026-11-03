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
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    HWHP_PROP_WSTATE,
    MAX_ERRORS,
    PROP_COMPRESSOR_FREQ,
    PROP_ENERGY_TOTAL,
    PROP_POWER_REDUCE_GEAR,
    PROP_POWER_REDUCE_TYPE,
    UPDATE_INTERVAL,
)
from .heatpump import (
    HEATPUMP_COLUMNS,
    TEMPERATURE_PAIRS,
    WritePolicy,
    classify,
    model_profile,
    prepare_command,
    verify_command_reply,
    user_control_policy,
)

_LOGGER = logging.getLogger(__name__)

# Extra raw properties requested from the device in addition to the standard Props enum.
# These cover Hot Water Heat Pump (HWHP) devices that expose different sensor keys.
_STANDARD_PROPS: list[str] = [x.value for x in Props]
_HWHP_EXTRA_PROPS = [
    HWHP_PROP_WATER_TEMP,
    HWHP_PROP_SET_TEM_INT,
    HWHP_PROP_SET_TEM_DEC,
    HWHP_PROP_WSTATE,
    HWHP_PROP_POW_CONSUMP,
    HWHP_PROP_WATER_PERCENT,
]

# Extra properties reported by AC units, surfaced by the sensor platform. The
# cloud serves these even though the local UDP protocol does not, so they are
# only available on this integration.
_SENSOR_EXTRA_PROPS = [
    PROP_ENERGY_TOTAL,
    PROP_COMPRESSOR_FREQ,
    PROP_POWER_REDUCE_GEAR,
    PROP_POWER_REDUCE_TYPE,
]


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

    write_policy = WritePolicy()

    def __init__(self, *args, enable_heatpump_controls=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.enable_heatpump_controls = enable_heatpump_controls
        self._cooling_observed = False
        self.write_policy = WritePolicy()

    def _refresh_write_policy(self):
        """Profile selection never sends commands and preserves the cooling evidence."""
        if not self.enable_heatpump_controls:
            return
        self._cooling_observed |= self.raw_properties.get("Mod") in (3, 5)
        self.write_policy = user_control_policy(
            self.raw_properties, mid=getattr(self, "cloud_mid", None), cooling=self._cooling_observed
        ) if getattr(self, "device_kind", "unknown") == "heatpump" else WritePolicy()

    def handle_state_update(self, **kwargs):
        """Never combine Hi/Lo halves from different MQTT messages."""
        if model_profile(getattr(self, "cloud_mid", None)) is None:
            super().handle_state_update(**kwargs)
            return
        for high, low in TEMPERATURE_PAIRS.values():
            if (high in kwargs) != (low in kwargs):
                self.raw_properties.pop(high, None)
                self.raw_properties.pop(low, None)
                kwargs.pop(high, None)
                kwargs.pop(low, None)
        super().handle_state_update(**kwargs)

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
            if self.uses_mqtt and not self._mqtt_client.is_connected:
                raise HomeAssistantError("MQTT disconnected; command was not sent")
            # Only allowlisted user commands can reach the transport.
            try:
                self._strict_command_reply = True
                reply = await (self._mqtt_request(command, self._command_timeout)
                               if self.uses_mqtt else self._gateway.request(
                                   self._child_mac, self._gateway_cipher(), command))
                verify_command_reply(reply, key, command["p"][0])
            except (ValueError, asyncio.TimeoutError) as err:
                raise HomeAssistantError("Command not confirmed; it may have executed. No retry.") from err
            finally:
                self._strict_command_reply = False
            # Cloud state can lag behind the ACK, or a late bare ACK can wake
            # the status request. Retry reads only, never the accepted write.
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(1)
                try:
                    data = await (self._mqtt_request({"t": "status", "cols": list(HEATPUMP_COLUMNS)}, self._command_timeout)
                                  if self.uses_mqtt else self._gateway_status({"t": "status", "cols": list(HEATPUMP_COLUMNS)}))
                except asyncio.TimeoutError:
                    continue
                if isinstance(data, dict) and data.get(key) == command["p"][0]:
                    break
            else:
                raise HomeAssistantError(
                    "Command acknowledged, but the applied value could not be confirmed. "
                    "It may have executed; the write was not retried."
                )
            for column in HEATPUMP_COLUMNS:
                self.raw_properties.pop(column, None)
            self.handle_state_update(**data)
            return copy.deepcopy(self.raw_properties)

    def _handle_mqtt_message(self, topic, message):
        """Capture full ACKs only for air-to-water commands; preserve the AC handler."""
        if getattr(self, "_strict_command_reply", False):
            if self._parent_mac not in topic and self._child_mac not in topic:
                return
            if 'response/' in topic and message.pack and self._response_event:
                try:
                    reply = self.device_cipher.decrypt(message.pack)
                    if reply.get('t') in ('res', 'cmd', 'dat'):
                        self._response_data = reply
                        self._response_event.set()
                except Exception:
                    pass
            return  # An unsolicited status must not masquerade as a command ACK.
        super()._handle_mqtt_message(topic, message)

    def _status_columns(self) -> list[str]:
        """Standard properties plus the HWHP and sensor extras."""
        if model_profile(getattr(self, "cloud_mid", None)) is not None:
            return list(HEATPUMP_COLUMNS)
        return _STANDARD_PROPS + _HWHP_EXTRA_PROPS + _SENSOR_EXTRA_PROPS

    async def update_state(self) -> None:
        """Read only; reject empty acknowledgements instead of reporting success."""
        async with self.request_lock:
            if model_profile(getattr(self, "cloud_mid", None)) is None:
                self.device_kind = "ac"
                await super().update_state()
                return
            command = {"t": "status", "cols": self._status_columns()}
            data = await (
                self._mqtt_request(command, self._command_timeout)
                if self.uses_mqtt else self._gateway_status(command)
            )
            if not isinstance(data, dict) or not data or not any(
                key in data for key in ("Pow", "Mod", "HeWatOutTemSet", "SetTem", "WatTmp")
            ):
                raise ValueError("Cloud returned no usable device state")
            # A missing field in the latest poll is unknown, not a stale reading.
            if getattr(self, "device_kind", "unknown") != "ac":
                for key in self._status_columns():
                    self.raw_properties.pop(key, None)
            self.handle_state_update(**data)
            detected = classify(self.raw_properties, mid=getattr(self, "cloud_mid", None))
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
        if model_profile(getattr(self, "cloud_mid", None)) is not None:
            raise HomeAssistantError("This model requires the air-to-water command path")
        async with self.request_lock:
            return await super().push_state_update()


def is_hwhp_device(coordinator: "CloudDeviceDataUpdateCoordinator") -> bool:
    """Return True if the device appears to be a Hot Water Heat Pump.

    Detection requires a positive WatTmp raw value (actual = raw - 100).
    Standard AC units return 0 for unknown properties; a real HWHP reports
    actual water temperature (40–80 °C → raw 140–180), so raw > 0 is the
    discriminator.
    """
    if coordinator.device_kind == "heatpump":
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
            "unknown" if model_profile(getattr(self.device, "cloud_mid", None)) else "ac",
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update the state of the device from cloud."""
        _LOGGER.debug(
            "Updating cloud device state: %s, error count: %d",
            self.name,
            self._error_count,
        )
        try:
            if self.device_kind == "heatpump" and self.device.uses_mqtt and not self.device._mqtt_client.is_connected:
                if not await _try_reconnect(self.hass, self.config_entry):
                    raise UpdateFailed("MQTT disconnected")
            await self.device.update_state()
            self._error_count = 0
            _LOGGER.debug(
                "Raw properties for %s: %s", self.name, self.device.raw_properties
            )
            return copy.deepcopy(self.device.raw_properties)

        except asyncio.TimeoutError as error:
            if self.device_kind != "ac" and not is_hwhp_device(self):
                raise UpdateFailed("Device status timed out") from error
            self._error_count += 1
            if self._error_count >= MAX_ERRORS:
                _LOGGER.warning(
                    "Cloud device %s is unavailable after %d timeouts",
                    self.name,
                    self._error_count,
                )
                raise UpdateFailed(
                    f"Cloud device {self.name} is unavailable, timeout"
                ) from error
            # Return last known state if within error threshold
            return copy.deepcopy(self.device.raw_properties)

        except Exception as error:
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
            if self.device_kind != "ac" and not is_hwhp_device(self):
                raise UpdateFailed("Device status failed") from error
            _LOGGER.exception("Error updating cloud device %s: %s", self.name, error)
            if self._error_count >= MAX_ERRORS:
                raise UpdateFailed(
                    f"Cloud device {self.name} failed to update"
                ) from error
            return copy.deepcopy(self.device.raw_properties)

    async def push_state_update(self):
        """Send state updates to the cloud device."""
        if self.device_kind == "heatpump" or (
            self.device_kind == "unknown" and not is_hwhp_device(self)
        ):
            raise HomeAssistantError("Air-to-water/unidentified device writes are disabled")
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
                reconnected = await _try_reconnect(self.hass, self.config_entry)
                if reconnected:
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
        coordinators = []

        try:
            # Get all devices from cloud
            _LOGGER.debug("Fetching devices from Gree Cloud")
            cloud_devices = await self.api.get_all_devices()

            _LOGGER.info("Found %d cloud devices", len(cloud_devices))

            # Create coordinator for each device
            for cloud_dev_info in cloud_devices:
                device = None
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
                        enable_heatpump_controls=True,
                    )
                    device.cloud_mid = getattr(cloud_dev_info, "mid", None)

                    # Bind to cloud device (subscribe to MQTT topics)
                    await device.bind()

                    _LOGGER.info(
                        "Bound to cloud device: %s (MAC: %s, firmware: %s, transport: %s)",
                        device.device_info.name,
                        device.device_info.mac,
                        cloud_dev_info.version,
                        device.transport,
                    )

                    # Create coordinator
                    coordinator = CloudDeviceDataUpdateCoordinator(
                        self.hass, self.entry, device
                    )

                    # Initial refresh
                    await coordinator.async_config_entry_first_refresh()
                    coordinators.append(coordinator)

                    # Notify about discovered device
                    async_dispatcher_send(
                        self.hass, DISPATCH_DEVICE_DISCOVERED, coordinator
                    )

                except Exception as err:
                    if device is not None:
                        await device.close()
                    _LOGGER.exception(
                        "Failed to setup cloud device %s: %s",
                        cloud_dev_info.name,
                        err,
                    )

        except Exception as err:
            _LOGGER.exception("Failed to discover cloud devices: %s", err)

        return coordinators
