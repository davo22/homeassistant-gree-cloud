"""Config flow for Gree Climate Cloud integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_SERVER, DOMAIN, GREE_CLOUD_SERVERS

_LOGGER = logging.getLogger(__name__)


class GreeCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gree Climate Cloud."""

    VERSION = 1

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
                from greeclimate.cloud_api import GreeCloudApi

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
