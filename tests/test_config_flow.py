"""Adding the account, and the per-device options."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.gree_cloud.const import (
    CONF_EXTERNAL_TEMPERATURE_SENSORS,
    CONF_SERVER,
    DOMAIN,
    GREE_CLOUD_SERVERS,
    GREE_MQTT_SERVERS,
    OPT_DEVICE,
    OPT_TEMPERATURE_SENSOR,
    REGION_ALIASES,
)

from .conftest import PASSWORD, USERNAME, settle

ACCOUNT = {CONF_SERVER: "Europe", CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return result["flow_id"]


async def test_adding_the_account(hass: HomeAssistant, cloud) -> None:
    cloud.add("split_ac")
    flow = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow, ACCOUNT)
    await settle(hass, cloud)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Gree Cloud ({USERNAME})"
    assert result["data"] == ACCOUNT
    assert result["result"].unique_id == USERNAME
    # The login was tried with what the user typed, on the server they chose.
    assert cloud.accounts[0] == ("https://eugrih.gree.com", USERNAME, PASSWORD)
    # And the new entry is set up at once.
    assert hass.states.get("climate.living_room") is not None


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (Exception("Login failed: 401 Unauthorized"), "invalid_auth"),
        (Exception("Authentication failed"), "invalid_auth"),
        (ValueError("Unknown server"), "invalid_auth"),
        (aiohttp.ClientConnectionError("Cannot connect to host"), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
    ],
)
async def test_a_failed_login_shows_the_form_again(
    hass: HomeAssistant, cloud, error: Exception, shown: str
) -> None:
    cloud.add("split_ac")
    cloud.login_error = error
    flow = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow, ACCOUNT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": shown}
    assert hass.config_entries.async_entries(DOMAIN) == []

    # The user corrects the input and gets in.
    cloud.login_error = None
    result = await hass.config_entries.flow.async_configure(flow, ACCOUNT)
    await settle(hass, cloud)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_session_of_the_login_check_is_closed(hass: HomeAssistant, cloud) -> None:
    flow = await _start(hass)
    await hass.config_entries.flow.async_configure(flow, ACCOUNT)
    await settle(hass, cloud)
    # Two logins: the check of the form, then the setup of the entry.
    assert cloud.logins == 2
    assert cloud.api_closes == 1


async def test_an_account_is_added_once(hass: HomeAssistant, cloud, setup_integration) -> None:
    await setup_integration()
    flow = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow, ACCOUNT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


def test_every_region_has_a_broker() -> None:
    """A region without one would silently use the European broker."""
    assert set(GREE_MQTT_SERVERS) == set(GREE_CLOUD_SERVERS)
    for old, new in REGION_ALIASES.items():
        assert old not in GREE_CLOUD_SERVERS
        assert new in GREE_CLOUD_SERVERS


# -- options: the external temperature sensor (#10) ------------------------


async def _pick_device(hass: HomeAssistant, entry, mac: str) -> str:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {OPT_DEVICE: mac}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "device"
    return result["flow_id"]


async def test_choosing_an_external_temperature_sensor(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    unit = cloud.add("split_ac")
    cloud.add("split_ac", name="Bedroom", mac="aa00000000b2")
    entry = await setup_integration()
    hass.states.async_set("sensor.room", "23.4", {"unit_of_measurement": "°C"})

    flow = await _pick_device(hass, entry, unit.mac)
    result = await hass.config_entries.options.async_configure(
        flow, {OPT_TEMPERATURE_SENSOR: "sensor.room"}
    )
    await settle(hass, cloud)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_EXTERNAL_TEMPERATURE_SENSORS: {unit.mac: "sensor.room"}}
    # The entry was reloaded, so the choice applies without a restart.
    assert cloud.logins == 2
    assert hass.states.get("climate.living_room").attributes["current_temperature"] == 23.4
    assert hass.states.get("climate.bedroom").attributes["current_temperature"] == 19


async def test_clearing_the_external_temperature_sensor(
    hass: HomeAssistant, cloud, config_entry, setup_integration
) -> None:
    unit = cloud.add("split_ac")
    other = cloud.add("split_ac", name="Bedroom", mac="aa00000000b2")
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            CONF_EXTERNAL_TEMPERATURE_SENSORS: {unit.mac: "sensor.room", other.mac: "sensor.bedroom"}
        },
    )
    entry = await setup_integration()

    flow = await _pick_device(hass, entry, unit.mac)
    result = await hass.config_entries.options.async_configure(flow, {})
    await settle(hass, cloud)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_EXTERNAL_TEMPERATURE_SENSORS: {other.mac: "sensor.bedroom"}}


async def test_the_device_list_names_the_sensor_in_use(
    hass: HomeAssistant, cloud, config_entry, setup_integration
) -> None:
    unit = cloud.add("split_ac")
    cloud.add("split_ac", name="Bedroom", mac="aa00000000b2")
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_EXTERNAL_TEMPERATURE_SENSORS: {unit.mac: "sensor.room"}}
    )
    entry = await setup_integration()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    choices = result["data_schema"].schema[OPT_DEVICE].config["options"]
    assert choices == [
        {"value": unit.mac, "label": "Living Room (sensor.room)"},
        {"value": "aa00000000b2", "label": "Bedroom"},
    ]


async def test_no_options_without_devices(hass: HomeAssistant, cloud, setup_integration) -> None:
    entry = await setup_integration()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices"
