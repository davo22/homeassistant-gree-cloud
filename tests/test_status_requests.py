"""What the integration asks a unit for, and how much at a time.

Wi-Fi modules drop a status request that is too long without a word:
1.8.0-beta.1 asked every air conditioner for 57 columns and a unit that had
answered 39 columns for months went unavailable. These tests pin the requests
down, so nobody lengthens them without noticing.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from syrupy.assertion import SnapshotAssertion

from custom_components.gree_cloud.coordinator import (
    MAX_STATUS_COLUMNS,
    _column_chunks,
)

from .conftest import settle

MQTT_DEVICES = ["split_ac", "commercial_ac", "hwhp", "pool", "versati_series7"]
ALL_DEVICES = [*MQTT_DEVICES, "versati_series1", "vrf_head"]


def test_the_limit_is_the_longest_request_of_1_7() -> None:
    """Raising it needs proof from real units, not a passing test."""
    assert MAX_STATUS_COLUMNS == 40


@pytest.mark.parametrize(
    ("columns", "sizes"),
    [
        (0, [0]),
        (1, [1]),
        (40, [40]),
        (41, [21, 20]),
        (57, [29, 28]),
        (80, [40, 40]),
        (81, [27, 27, 27]),
    ],
)
def test_long_requests_are_split_evenly(columns: int, sizes: list[int]) -> None:
    names = [f"c{i}" for i in range(columns)]
    chunks = _column_chunks(names)
    assert [len(chunk) for chunk in chunks] == sizes
    assert [name for chunk in chunks for name in chunk] == names


@pytest.mark.parametrize("fixture", ALL_DEVICES)
async def test_status_requests(
    hass: HomeAssistant,
    cloud,
    setup_integration,
    poll,
    snapshot: SnapshotAssertion,
    fixture: str,
) -> None:
    """The exact requests during setup and on a regular poll."""
    unit = cloud.add(fixture)
    await setup_integration()
    assert unit.status_requests == snapshot(name="setup")

    unit.forget()
    await poll()
    assert unit.status_requests == snapshot(name="regular poll")


@pytest.mark.parametrize("fixture", ALL_DEVICES)
async def test_no_request_is_longer_than_the_limit(
    hass: HomeAssistant, cloud, setup_integration, poll, fixture: str
) -> None:
    unit = cloud.add(fixture)
    await setup_integration()
    if fixture == "versati_series1":
        # Its columns depend on what it reported; ask again knowing that.
        await cloud.push(unit)
        await settle(hass, cloud)
    await poll()
    assert unit.status_requests
    assert max(len(columns) for columns in unit.status_requests) <= MAX_STATUS_COLUMNS


@pytest.mark.parametrize("fixture", MQTT_DEVICES)
async def test_a_module_that_drops_long_requests_is_served(
    hass: HomeAssistant, cloud, setup_integration, poll, fixture: str
) -> None:
    """The unit of the beta.1 regression: silent above 40 columns."""
    unit = cloud.add(fixture, max_columns=MAX_STATUS_COLUMNS)
    await setup_integration()
    await poll()
    states = hass.states.async_all()
    assert states
    assert [state.entity_id for state in states if state.state == "unavailable"] == []


async def test_vrf_head_is_asked_five_columns_at_a_time(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    """An old controller answers five columns per request and no more (#6)."""
    unit = cloud.add("vrf_head")
    await setup_integration()
    await poll()
    assert max(len(columns) for columns in unit.status_requests) == 5
    # Through its module, with the head named inside the request.
    requests = [r for r in cloud.gateway_requests if r["pack"].get("t") == "status"]
    assert requests[-1]["route"] == unit.module_mac
    assert requests[-1]["tcid"] == unit.module_mac
    assert requests[-1]["pack"]["mac"] == unit.mac


async def test_an_unanswered_request_costs_only_its_columns(
    hass: HomeAssistant, cloud, setup_integration, poll, caplog: pytest.LogCaptureFixture
) -> None:
    """A head that skips one request keeps its last values for those columns."""
    unit = cloud.add("vrf_head")
    await setup_integration()
    assert hass.states.get("climate.head").attributes["fan_mode"] == "medium-low"
    unit.ignores_columns = {"WdSpd"}
    unit.state.update(SetTem=25, WdSpd=5)
    unit.forget()
    caplog.clear()

    await poll()

    assert len(unit.status_requests) == 8
    state = hass.states.get("climate.head")
    assert state.state != "unavailable"
    assert state.attributes["temperature"] == 25
    assert state.attributes["fan_mode"] == "medium-low"
    assert "5 of 37 properties went unanswered this poll" in caplog.text

    unit.ignores_columns = set()
    await poll()
    assert hass.states.get("climate.head").attributes["fan_mode"] == "high"
