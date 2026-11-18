"""Swimming-pool heat pump (model 9302, #48): readings and commands.

The recorded unit is heating: water in at 22.5 °C, out at 24 °C, target 36 °C.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.gree_cloud.pool import pool_temperature

from .common import call
from .fake_cloud import FakeUnit

POOL = "climate.pool"


@pytest.mark.parametrize(
    ("props", "expected"),
    [
        ({"InTemInt": 120, "InTemDec": 5}, 20.5),
        ({"InTemInt": 122, "InTemDec": 0}, 22.0),
        ({"InTemInt": 95, "InTemDec": 5}, -4.5),
        ({"InTemInt": 124}, 24.0),
        # No reading: missing, zero, or not a number.
        ({"InTemInt": "124", "InTemDec": "5"}, None),
        ({"InTemInt": True}, None),
        ({}, None),
        ({"InTemInt": 0, "InTemDec": 5}, None),
        ({"InTemInt": None}, None),
        ({"InTemInt": "?"}, None),
    ],
)
def test_temperatures_have_an_offset_of_100_and_separate_tenths(
    props: dict[str, Any], expected: float | None
) -> None:
    assert pool_temperature(props, "InTemInt", "InTemDec") == expected


def test_a_limit_has_no_tenths() -> None:
    assert pool_temperature({"HeatTemMax": 140}, "HeatTemMax") == 40.0


@pytest.fixture
async def unit(cloud, setup_integration) -> FakeUnit:
    unit = cloud.add("pool")
    await setup_integration()
    unit.forget()
    return unit


@pytest.mark.parametrize(
    ("service", "data", "commands"),
    [
        # Every command carries FlagPool = 1 in front, as the app sends it.
        (
            "set_temperature",
            {"temperature": 28.5},
            [{"FlagPool": 1, "SetTemInt": 28, "SetTemDec": 5}],
        ),
        (
            "set_temperature",
            {"temperature": 30},
            [{"FlagPool": 1, "SetTemInt": 30, "SetTemDec": 0}],
        ),
        ("set_hvac_mode", {"hvac_mode": "off"}, [{"FlagPool": 1, "Pow": 0}]),
        ("turn_off", {}, [{"FlagPool": 1, "Pow": 0}]),
        ("set_hvac_mode", {"hvac_mode": "cool"}, [{"FlagPool": 1, "Wmod": 1}]),
        ("set_hvac_mode", {"hvac_mode": "auto"}, [{"FlagPool": 1, "Wmod": 2}]),
        # Already heating: nothing to send.
        ("set_hvac_mode", {"hvac_mode": "heat"}, []),
    ],
)
async def test_climate_command(
    hass: HomeAssistant,
    cloud,
    unit: FakeUnit,
    service: str,
    data: dict[str, Any],
    commands: list[dict[str, Any]],
) -> None:
    await call(hass, "climate", service, POOL, **data)
    assert unit.commands == commands


async def test_the_first_property_of_a_command_is_the_flag(
    hass: HomeAssistant, cloud, unit: FakeUnit
) -> None:
    await call(hass, "climate", "set_temperature", POOL, temperature=28.5)
    command = next(pack for pack in unit.received if pack["t"] == "cmd")
    assert command["opt"] == ["FlagPool", "SetTemInt", "SetTemDec"]
    assert command["p"] == [1, 28, 5]


async def test_the_setpoint_shows_at_once_and_after_the_poll(
    hass: HomeAssistant, cloud, unit: FakeUnit, poll
) -> None:
    await call(hass, "climate", "set_temperature", POOL, temperature=28.5)
    assert hass.states.get(POOL).attributes["temperature"] == 28.5
    await poll()
    assert hass.states.get(POOL).attributes["temperature"] == 28.5


async def test_switching_on_from_off_selects_the_mode_first(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    unit = cloud.add("pool", state={"Pow": 0})
    await setup_integration()
    assert hass.states.get(POOL).state == "off"

    unit.forget()
    await call(hass, "climate", "set_hvac_mode", POOL, hvac_mode="cool")
    assert unit.commands == [{"FlagPool": 1, "Wmod": 1}, {"FlagPool": 1, "Pow": 1}]
    assert hass.states.get(POOL).state == "cool"

    await call(hass, "climate", "turn_off", POOL)
    await call(hass, "climate", "turn_on", POOL)
    assert unit.commands[2:] == [{"FlagPool": 1, "Pow": 0}, {"FlagPool": 1, "Pow": 1}]
    assert hass.states.get(POOL).state == "cool"


@pytest.mark.parametrize(("option", "value"), [("fast", 1), ("eco", 2), ("smart", 0)])
async def test_function(
    hass: HomeAssistant, cloud, setup_integration, option: str, value: int
) -> None:
    unit = cloud.add("pool", state={"PoolFunc": 2 if option == "smart" else 0})
    await setup_integration()
    unit.forget()
    await call(hass, "select", "select_option", "select.pool_function", option=option)
    assert unit.commands == [{"FlagPool": 1, "PoolFunc": value}]
    assert hass.states.get("select.pool_function").state == option


async def test_a_command_the_unit_rejects_is_an_error(
    hass: HomeAssistant, cloud, unit: FakeUnit
) -> None:
    unit.command_result = 400
    with pytest.raises(HomeAssistantError, match=r"rejected the command \(r=400\)"):
        await call(hass, "climate", "set_temperature", POOL, temperature=28)
    assert hass.states.get(POOL).attributes["temperature"] == 36.0


async def test_a_command_without_an_answer_is_an_error(
    hass: HomeAssistant, cloud, unit: FakeUnit, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("custom_components.gree_cloud.pool._COMMAND_TIMEOUT", 0.25)
    unit.acks_commands = False
    unit.executes_commands = False
    with pytest.raises(HomeAssistantError, match="did not acknowledge the command"):
        await call(hass, "climate", "set_temperature", POOL, temperature=28)
    assert hass.states.get(POOL).attributes["temperature"] == 36.0


async def test_readings_follow_the_unit(hass: HomeAssistant, cloud, unit: FakeUnit, poll) -> None:
    unit.state.update(InTemInt=127, InTemDec=5, OutTemInt=129, OutTemDec=0, ComStatus=0)
    await poll()
    assert hass.states.get("sensor.pool_water_inlet_temperature").state == "27.5"
    assert hass.states.get("sensor.pool_water_outlet_temperature").state == "29.0"
    assert hass.states.get("binary_sensor.pool_compressor").state == "off"
    assert hass.states.get(POOL).attributes["current_temperature"] == 27.5
