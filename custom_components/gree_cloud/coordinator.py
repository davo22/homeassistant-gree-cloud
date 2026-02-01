"""Helper and wrapper classes for Gree Cloud module."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from greeclimate.cloud_api import CloudDeviceInfo, GreeCloudApi
from greeclimate.cloud_device import CloudDevice
from greeclimate.deviceinfo import DeviceInfo
from greeclimate.mqtt_client import GreeMqttClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_SERVER,
    DISPATCH_DEVICE_DISCOVERED,
    DOMAIN,
    MAX_ERRORS,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type GreeCloudConfigEntry = ConfigEntry[GreeCloudRuntimeData]


@dataclass
class GreeCloudRuntimeData:
    """Runtime data for Gree Climate Cloud integration."""

    cloud_api: GreeCloudApi
    mqtt_client: GreeMqttClient
    coordinators: list[CloudDeviceDataUpdateCoordinator]


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
            return copy.deepcopy(self.device.raw_properties)

        except asyncio.TimeoutError as error:
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
        self, mqtt_client: GreeMqttClient
    ) -> list[CloudDeviceDataUpdateCoordinator]:
        """Discover all cloud devices."""
        coordinators = []

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
                    )

                    # Create cloud device instance
                    device = CloudDevice(
                        mqtt_client=mqtt_client,
                        device_info=device_info,
                        device_key=cloud_dev_info.key,
                        cipher_version=1,  # Default to v1, can be made configurable
                    )

                    # Bind to cloud device (subscribe to MQTT topics)
                    await device.bind()

                    _LOGGER.debug(
                        "Bound to cloud device: %s (MAC: %s)",
                        device.device_info.name,
                        device.device_info.mac,
                    )

                    # Create coordinator
                    coordinator = CloudDeviceDataUpdateCoordinator(
                        self.hass, self.entry, device
                    )
                    coordinators.append(coordinator)

                    # Initial refresh
                    await coordinator.async_config_entry_first_refresh()

                    # Notify about discovered device
                    async_dispatcher_send(
                        self.hass, DISPATCH_DEVICE_DISCOVERED, coordinator
                    )

                except Exception as err:
                    _LOGGER.exception(
                        "Failed to setup cloud device %s: %s",
                        cloud_dev_info.name,
                        err,
                    )

        except Exception as err:
            _LOGGER.exception("Failed to discover cloud devices: %s", err)

        return coordinators
