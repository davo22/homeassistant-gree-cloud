"""Setting the entry up, taking it down, and what happens when the cloud says no."""

from __future__ import annotations

import json
import re
from pathlib import Path

import aiohttp
import aiomqtt
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gree_cloud.const import CONF_SERVER, DOMAIN

from .conftest import PASSWORD, USERNAME
from .fake_cloud import TOKEN, USER_ID

ROOT = Path(__file__).parent.parent


async def test_setup_logs_in_and_connects_to_the_broker_of_the_region(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    cloud.add("split_ac")
    entry = await setup_integration()

    assert entry.state is ConfigEntryState.LOADED
    assert cloud.accounts == [("https://eugrih.gree.com", USERNAME, PASSWORD)]
    assert len(cloud.sessions) == 1
    options = cloud.session.options
    assert options["hostname"] == "mqtt-eu.gree.com"
    # The broker takes the user id and the token of the login.
    assert (options["username"], options["password"]) == (str(USER_ID), TOKEN)
    assert hass.states.get("climate.living_room").state == "off"


@pytest.mark.parametrize(
    ("region", "api", "broker"),
    [
        ("North American", "https://nagrih.gree.com", "mqtt-na.gree.com"),
        ("South American", "https://sagrih.gree.com", "mqtt-sa.gree.com"),
        # The name this region had until 1.6; entries made then still carry it (#34).
        ("Latin American", "https://sagrih.gree.com", "mqtt-sa.gree.com"),
    ],
)
async def test_region(
    hass: HomeAssistant,
    cloud,
    config_entry,
    setup_integration,
    region: str,
    api: str,
    broker: str,
) -> None:
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_SERVER: region}
    )
    entry = await setup_integration()

    assert entry.state is ConfigEntryState.LOADED
    assert cloud.accounts == [(api, USERNAME, PASSWORD)]
    assert cloud.session.options["hostname"] == broker
    # The entry itself is left as it was.
    assert entry.data[CONF_SERVER] == region


@pytest.mark.parametrize(
    "error",
    [aiohttp.ClientConnectionError("Cannot connect to host"), TimeoutError()],
)
async def test_an_unreachable_cloud_is_retried(
    hass: HomeAssistant, cloud, setup_integration, error: Exception
) -> None:
    """Home Assistant tries again by itself; the user has nothing to do."""
    cloud.add("split_ac")
    cloud.login_error = error
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert cloud.api_closes == 1

    cloud.login_error = None
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("climate.living_room").state == "off"


async def test_a_broker_that_refuses_the_login_is_retried(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    """The login just succeeded, so the refusal is the cloud's trouble of the moment (#83)."""
    cloud.add("split_ac")
    cloud.connect_error = aiomqtt.MqttCodeError(4, "Bad user name or password")
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert cloud.logins == 1
    assert cloud.api_closes == 1


async def test_a_rejected_login_fails_the_setup(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    cloud.login_error = Exception("Login failed: wrong password")
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_an_account_without_devices_loads(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.async_all() == []


async def test_a_failing_device_list_leaves_the_entry_loaded(
    hass: HomeAssistant, cloud, setup_integration, caplog: pytest.LogCaptureFixture
) -> None:
    cloud.add("split_ac")
    cloud.devices_error = aiohttp.ClientConnectionError("Cannot connect to host")
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.async_all() == []
    assert "Failed to discover cloud devices" in caplog.text


async def test_unloading_closes_the_connections(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    cloud.add("split_ac")
    entry = await setup_integration()
    assert cloud.session.open

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not cloud.session.open
    assert cloud.api_closes == 1
    assert hass.states.get("climate.living_room").state == "unavailable"


async def test_reloading_starts_afresh(hass: HomeAssistant, cloud, setup_integration) -> None:
    unit = cloud.add("split_ac")
    entry = await setup_integration()

    unit.state["SetTem"] = 25
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.LOADED
    assert cloud.logins == 2
    assert [session.open for session in cloud.sessions] == [False, True]
    assert hass.states.get("climate.living_room").attributes["temperature"] == 25


async def test_two_accounts_side_by_side(hass: HomeAssistant, cloud, setup_integration) -> None:
    cloud.add("split_ac")
    first = await setup_integration()
    second = MockConfigEntry(
        domain=DOMAIN,
        unique_id="other@example.com",
        data={CONF_SERVER: "Europe", CONF_USERNAME: "other@example.com", CONF_PASSWORD: PASSWORD},
    )
    second.add_to_hass(hass)
    await setup_integration(second)
    assert first.state is ConfigEntryState.LOADED
    assert second.state is ConfigEntryState.LOADED


# -- packaging --------------------------------------------------------------


def test_the_tests_run_against_the_library_the_integration_installs() -> None:
    """Otherwise the suite would prove something about another library version."""
    manifest = json.loads((ROOT / "custom_components/gree_cloud/manifest.json").read_text())
    pins = [
        line.strip()
        for line in (ROOT / "requirements_test.txt").read_text().splitlines()
        if line.startswith("greeclimate-davo22")
    ]
    assert pins == manifest["requirements"]


def test_the_version_is_one_hacs_can_compare() -> None:
    manifest = json.loads((ROOT / "custom_components/gree_cloud/manifest.json").read_text())
    assert manifest["domain"] == DOMAIN
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])


def test_translations_match_the_strings() -> None:
    """English is what the code falls back to; a missing key shows as a raw key."""
    strings = json.loads((ROOT / "custom_components/gree_cloud/strings.json").read_text())
    english = json.loads((ROOT / "custom_components/gree_cloud/translations/en.json").read_text())
    assert english == strings
