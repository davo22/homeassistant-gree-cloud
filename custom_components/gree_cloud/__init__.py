"""The Gree Climate Cloud integration."""

from __future__ import annotations

import logging

from greeclimate.cloud_api import GreeCloudApi
from greeclimate.mqtt_client import GreeMqttClient

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_SERVER, DOMAIN
from .coordinator import (
    CloudDiscoveryService,
    GreeCloudConfigEntry,
    GreeCloudRuntimeData,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: GreeCloudConfigEntry) -> bool:
    """Set up Gree Climate Cloud from a config entry."""
    _LOGGER.info("Setting up Gree Climate Cloud integration")

    try:
        # Create Cloud API client
        api = GreeCloudApi.for_server(
            entry.data[CONF_SERVER],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )

        # Login to cloud
        _LOGGER.debug("Logging in to Gree Cloud")
        credentials = await api.login()

        # Create MQTT client
        _LOGGER.debug("Connecting to Gree MQTT broker")
        mqtt_client = GreeMqttClient(credentials.user_id, credentials.token)
        await mqtt_client.connect()

        # Store runtime data
        entry.runtime_data = GreeCloudRuntimeData(
            cloud_api=api,
            mqtt_client=mqtt_client,
            coordinators=[],
        )

        # Discover and setup devices
        discovery = CloudDiscoveryService(hass, entry, api)
        coordinators = await discovery.discover_devices(mqtt_client)
        entry.runtime_data.coordinators = coordinators

        _LOGGER.info("Successfully discovered %d cloud devices", len(coordinators))

        # Setup platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        return True

    except Exception as err:
        _LOGGER.exception("Failed to setup Gree Climate Cloud: %s", err)
        return False


async def async_unload_entry(hass: HomeAssistant, entry: GreeCloudConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Gree Climate Cloud integration")

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Close all devices
        for coordinator in entry.runtime_data.coordinators:
            try:
                await coordinator.device.close()
            except Exception as err:
                _LOGGER.warning("Error closing device: %s", err)

        # Disconnect MQTT client
        try:
            await entry.runtime_data.mqtt_client.disconnect()
        except Exception as err:
            _LOGGER.warning("Error disconnecting MQTT client: %s", err)

        # Close API session
        try:
            await entry.runtime_data.cloud_api.close()
        except Exception as err:
            _LOGGER.warning("Error closing API session: %s", err)

    return unload_ok
