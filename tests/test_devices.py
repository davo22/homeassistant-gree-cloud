"""What each kind of device turns into in Home Assistant.

One recorded device per test, set up through the fake cloud, compared with a
snapshot of every device and entity it produces: ids, names, states,
attributes. See ``tests/README.md`` for how to read and update snapshots.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from syrupy.assertion import SnapshotAssertion

from .common import describe
from .conftest import settle


@pytest.mark.parametrize(
    "fixture",
    ["split_ac", "commercial_ac", "hwhp", "pool", "versati_series7"],
)
async def test_device(
    hass: HomeAssistant, cloud, setup_integration, snapshot: SnapshotAssertion, fixture: str
) -> None:
    cloud.add(fixture)
    entry = await setup_integration()
    assert describe(hass, entry) == snapshot


async def test_versati_series1(
    hass: HomeAssistant, cloud, setup_integration, snapshot: SnapshotAssertion
) -> None:
    """A Versati 5 never answers a status request; it reports by itself (#75)."""
    unit = cloud.add("versati_series1")
    entry = await setup_integration()
    assert describe(hass, entry) == snapshot(name="before the first report")
    await cloud.push(unit)
    await settle(hass, cloud)
    assert describe(hass, entry) == snapshot(name="after the first report")


async def test_vrf_heads(
    hass: HomeAssistant, cloud, setup_integration, snapshot: SnapshotAssertion
) -> None:
    """Four indoor units behind one old controller, on the legacy gateway (#6)."""
    cloud.add("vrf_head", name="Office", mac="bb0000000001")
    cloud.add("vrf_head", name="Kitchen", mac="bb0000000002", state={"Pow": 0, "SetTem": 22, "InTem": 64})
    cloud.add("vrf_head", name="Bedroom", mac="bb0000000003", state={"Mod": 4, "SetTem": 20, "InTem": 61})
    cloud.add("vrf_head", name="Hall", mac="bb0000000004", state={"WdSpd": 0, "InTem": 63})
    entry = await setup_integration()
    assert describe(hass, entry) == snapshot
