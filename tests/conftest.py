"""Shared fixtures: Home Assistant with the integration and a fake Gree cloud."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from greeclimate_davo22 import cloud_device
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.gree_cloud.const import CONF_SERVER, DOMAIN, UPDATE_INTERVAL
from custom_components.gree_cloud.coordinator import HWHPAwareCloudDevice

from .fake_cloud import FakeCloud

USERNAME = "user@example.com"
PASSWORD = "correct horse"

# How long a unit gets to answer in tests. Real units get 10 s; the fake ones
# answer within the same loop iteration, so silence is established quickly.
COMMAND_TIMEOUT = 0.25

SetupIntegration = Callable[..., Awaitable[MockConfigEntry]]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from ``custom_components``."""


@pytest.fixture(autouse=True)
def library_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with a library that has learned nothing yet.

    The library remembers per module what worked (transport, addressing,
    column limit) in module globals; left alone, one test would teach the
    next. The pause between gateway requests protects real controllers and
    only costs time here.
    """
    for name in (
        "_UNITS_BY_MODULE",
        "_MODULE_HINTS",
        "_MODULE_GATEWAY_LOCKS",
        "_MODULE_GATEWAY_LAST",
        "_MODULE_GATEWAY_OFFLINE_UNTIL",
    ):
        monkeypatch.setattr(cloud_device, name, {})
    monkeypatch.setattr(cloud_device, "GATEWAY_REQUEST_SPACING", 0)

    real_init = HWHPAwareCloudDevice.__init__

    def init(self: HWHPAwareCloudDevice, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        self._command_timeout = COMMAND_TIMEOUT

    monkeypatch.setattr(HWHPAwareCloudDevice, "__init__", init)


@pytest.fixture
async def cloud(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[FakeCloud]:
    """The fake Gree cloud; add units to it, then set the integration up."""
    fake = FakeCloud()
    fake.install(monkeypatch)
    yield fake
    # Unload what the test left loaded: closes the broker connection and the
    # API session, and proves on every test that unloading works.
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry for the fake account, not set up yet."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Gree Cloud ({USERNAME})",
        unique_id=USERNAME,
        data={CONF_SERVER: "Europe", CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def setup_integration(
    hass: HomeAssistant, cloud: FakeCloud, config_entry: MockConfigEntry
) -> SetupIntegration:
    """Set the integration up and wait until discovery has finished."""

    async def setup(entry: MockConfigEntry | None = None) -> MockConfigEntry:
        entry = entry or config_entry
        await hass.config_entries.async_setup(entry.entry_id)
        await settle(hass, cloud)
        return entry

    return setup


@pytest.fixture
def poll(hass: HomeAssistant, cloud: FakeCloud) -> Callable[[], Awaitable[None]]:
    """Let the polling interval pass, so every device is polled once.

    The clock is not frozen: the library times its waits with it.
    """

    async def poll() -> None:
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(seconds=UPDATE_INTERVAL + 1)
        )
        await settle(hass, cloud)

    return poll


async def settle(hass: HomeAssistant, cloud: FakeCloud) -> None:
    """Wait for everything in flight: discovery, broker messages, state writes."""
    await hass.async_block_till_done(wait_background_tasks=True)
    await cloud.settle()
    await hass.async_block_till_done(wait_background_tasks=True)
