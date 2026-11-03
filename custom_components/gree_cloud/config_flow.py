"""Config flow for Gree Climate Cloud integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_EXTERNAL_TEMPERATURE_SENSORS,
    CONF_SERVER,
    DOMAIN,
    GREE_CLOUD_SERVERS,
    OPT_DEVICE,
    OPT_TEMPERATURE_SENSOR,
)

_LOGGER = logging.getLogger(__name__)


class GreeCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gree Climate Cloud."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> GreeCloudOptionsFlow:
        """Create the options flow."""
        return GreeCloudOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check if already configured
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            # Validate credentials by attempting to login
            try:
                from greeclimate_davo22.cloud_api import GreeCloudApi

                api = GreeCloudApi.for_server(
                    user_input[CONF_SERVER],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )

                # Try to login to validate credentials
                await api.login()
                await api.close()

                # Create the config entry
                return self.async_create_entry(
                    title=f"Gree Cloud ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

            except ValueError as err:
                _LOGGER.error("Invalid server selection: %s", err)
                errors["base"] = "invalid_auth"
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error during Gree Cloud login: %s", err)
                if "401" in str(err) or "auth" in str(err).lower():
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"

        # Show the configuration form
        data_schema = vol.Schema(
            {
                vol.Required(CONF_SERVER, default="Europe"): vol.In(
                    list(GREE_CLOUD_SERVERS.keys())
                ),
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )


class GreeCloudOptionsFlow(config_entries.OptionsFlow):
    """Per-device options: an external sensor for the current temperature (#10).

    Step 1 picks the device, step 2 picks (or clears) the sensor. The result is
    stored as ``options[CONF_EXTERNAL_TEMPERATURE_SENSORS] = {mac: entity_id}``;
    the entry is reloaded by the update listener in ``__init__``.
    """

    def __init__(self) -> None:
        """Initialize."""
        self._mac: str | None = None

    def _devices(self) -> dict[str, str]:
        """Return {mac: name} for the discovered air-conditioner devices."""
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is None:
            return {}
        return {
            coordinator.device.device_info.mac: coordinator.device.device_info.name
            for coordinator in runtime.coordinators
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick the device to configure."""
        devices = self._devices()
        if not devices:
            return self.async_abort(reason="no_devices")

        if user_input is not None:
            self._mac = user_input[OPT_DEVICE]
            return await self.async_step_device()

        sensors = self.config_entry.options.get(CONF_EXTERNAL_TEMPERATURE_SENSORS, {})
        options = [
            SelectOptionDict(
                value=mac,
                label=f"{name} ({sensors[mac]})" if mac in sensors else name,
            )
            for mac, name in devices.items()
        ]
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(OPT_DEVICE): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick or clear the external temperature sensor for the chosen device."""
        sensors = dict(self.config_entry.options.get(CONF_EXTERNAL_TEMPERATURE_SENSORS, {}))

        if user_input is not None:
            entity_id = user_input.get(OPT_TEMPERATURE_SENSOR)
            if entity_id:
                sensors[self._mac] = entity_id
            else:
                sensors.pop(self._mac, None)
            return self.async_create_entry(
                title="",
                data={**self.config_entry.options, CONF_EXTERNAL_TEMPERATURE_SENSORS: sensors},
            )

        schema = vol.Schema(
            {
                vol.Optional(
                    OPT_TEMPERATURE_SENSOR,
                    description={"suggested_value": sensors.get(self._mac)},
                ): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                )
            }
        )
        return self.async_show_form(
            step_id="device",
            data_schema=schema,
            description_placeholders={"device": self._devices().get(self._mac, self._mac)},
        )
