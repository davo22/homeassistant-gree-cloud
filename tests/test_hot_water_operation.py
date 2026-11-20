"""The hot water operation of a Versati 5 (#75).

Hot water is part of the unit's mode, and Rapid ("Fast hot water") is a flag
next to it. The hot water entity sets both: off takes hot water out of the
mode, heat pump and performance put it in, without and with Rapid. The unit's
power is switched from here only in Hot water mode, where hot water is all the
unit makes, and nothing is written that is already so.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .common import call
from .conftest import settle
from .fake_cloud import FakeUnit

TANK = "water_heater.heat_pump_hot_water"
RUNNING = {"Pow": 1, "ZonePow1": 1, "ZonePow2": 1}


@pytest.fixture
def series1(hass: HomeAssistant, cloud, setup_integration):
    """Set a series 1 unit up in the given state, after its first report."""

    async def series1(**state: Any) -> FakeUnit:
        unit = cloud.add("versati_series1", state=state)
        await setup_integration()
        await cloud.push(unit)
        await settle(hass, cloud)
        unit.forget()
        return unit

    return series1


@pytest.mark.parametrize(
    ("state", "shown"),
    [
        ({**RUNNING, "Mod": 1}, "off"),
        ({**RUNNING, "Mod": 2}, "heat_pump"),
        ({**RUNNING, "Mod": 4}, "heat_pump"),
        ({**RUNNING, "Mod": 2, "FastHtWter": 1}, "performance"),
        ({**RUNNING, "Mod": 4, "FastHtWter": 1}, "performance"),
        # Rapid left on does not count without hot water in the mode.
        ({**RUNNING, "Mod": 1, "FastHtWter": 1}, "off"),
        ({"Pow": 0, "Mod": 2, "FastHtWter": 1}, "off"),
    ],
)
async def test_operation_shown(hass: HomeAssistant, cloud, series1, state, shown: str) -> None:
    await series1(**state)
    tank = hass.states.get(TANK)
    assert tank.state == shown
    assert tank.attributes["operation_mode"] == shown
    assert tank.attributes["operation_list"] == ["off", "heat_pump", "performance"]


@pytest.mark.parametrize(
    ("state", "operation", "commands"),
    [
        ({"Mod": 1}, "heat_pump", [{"Mod": 4}]),
        ({"Mod": 1}, "performance", [{"Mod": 4}, {"FastHtWter": 1}]),
        ({"Mod": 4}, "performance", [{"FastHtWter": 1}]),
        ({"Mod": 2}, "performance", [{"FastHtWter": 1}]),
        ({"Mod": 2, "FastHtWter": 1}, "heat_pump", [{"FastHtWter": 0}]),
        ({"Mod": 1, "FastHtWter": 1}, "heat_pump", [{"Mod": 4}, {"FastHtWter": 0}]),
        ({"Mod": 4}, "off", [{"Mod": 1}]),
        ({"Mod": 4, "FastHtWter": 1}, "off", [{"Mod": 1}]),
        # A unit seen cooling: Cool <-> Cool + hot water.
        ({"Mod": 5}, "heat_pump", [{"Mod": 3}]),
        ({"Mod": 3}, "off", [{"Mod": 5}]),
        # Already so: nothing is written.
        ({"Mod": 4}, "heat_pump", []),
        ({"Mod": 2, "FastHtWter": 1}, "performance", []),
        ({"Mod": 1}, "off", []),
    ],
)
async def test_operation_set(
    hass: HomeAssistant, cloud, series1, state, operation: str, commands
) -> None:
    unit = await series1(**RUNNING, **state)
    await call(hass, "water_heater", "set_operation_mode", TANK, operation_mode=operation)
    assert unit.commands == commands
    assert hass.states.get(TANK).state == operation


async def test_on_and_off(hass: HomeAssistant, cloud, series1) -> None:
    """The on/off of the card: hot water in and out of the mode, Rapid left alone."""
    unit = await series1(**RUNNING, Mod=1)
    await call(hass, "water_heater", "turn_on", TANK)
    assert unit.commands == [{"Mod": 4}]
    assert hass.states.get(TANK).state == "heat_pump"

    unit.forget()
    await call(hass, "water_heater", "turn_on", TANK)
    assert unit.commands == []

    await call(hass, "water_heater", "set_operation_mode", TANK, operation_mode="performance")
    unit.forget()
    await call(hass, "water_heater", "turn_on", TANK)
    assert unit.commands == []
    assert hass.states.get(TANK).state == "performance"

    await call(hass, "water_heater", "turn_off", TANK)
    assert unit.commands == [{"Mod": 1}]
    assert hass.states.get(TANK).state == "off"


OFF = {"Pow": 0, "ZonePow1": 0, "ZonePow2": 0}


@pytest.mark.parametrize("service", ["set_operation_mode", "turn_off"])
async def test_hot_water_only_is_switched_off_as_a_whole(
    hass: HomeAssistant, cloud, series1, service: str
) -> None:
    """In Hot water mode there is no mode without hot water: off is the power."""
    unit = await series1(**RUNNING, Mod=2)
    data = {"operation_mode": "off"} if service == "set_operation_mode" else {}
    await call(hass, "water_heater", service, TANK, **data)
    assert unit.commands == [OFF]
    assert hass.states.get(TANK).state == "off"

    unit.forget()
    await call(hass, "water_heater", service, TANK, **data)
    assert unit.commands == []


@pytest.mark.parametrize(
    ("state", "service", "data", "commands", "shown"),
    [
        ({}, "turn_on", {}, [RUNNING], "heat_pump"),
        ({}, "set_operation_mode", {"operation_mode": "heat_pump"}, [RUNNING], "heat_pump"),
        (
            {},
            "set_operation_mode",
            {"operation_mode": "performance"},
            [RUNNING, {"FastHtWter": 1}],
            "performance",
        ),
        # Rapid left on from before is taken off again.
        (
            {"FastHtWter": 1},
            "set_operation_mode",
            {"operation_mode": "heat_pump"},
            [RUNNING, {"FastHtWter": 0}],
            "heat_pump",
        ),
    ],
)
async def test_hot_water_only_is_switched_on_again(
    hass: HomeAssistant, cloud, series1, state, service: str, data, commands, shown: str
) -> None:
    unit = await series1(**OFF, Mod=2, **state)
    await call(hass, "water_heater", service, TANK, **data)
    assert unit.commands == commands
    assert hass.states.get(TANK).state == shown


@pytest.mark.parametrize("operation", ["heat_pump", "performance"])
@pytest.mark.parametrize("mode", [1, 4])
async def test_the_operation_never_starts_the_heating(
    hass: HomeAssistant, cloud, series1, operation: str, mode: int
) -> None:
    """Switching the unit on in these modes would heat the house as well."""
    unit = await series1(Pow=0, Mod=mode)
    with pytest.raises(HomeAssistantError, match="switch it on first"):
        await call(hass, "water_heater", "set_operation_mode", TANK, operation_mode=operation)
    with pytest.raises(HomeAssistantError, match="switch it on first"):
        await call(hass, "water_heater", "turn_on", TANK)
    assert unit.commands == []
    # Off is what it already is.
    await call(hass, "water_heater", "turn_off", TANK)
    assert unit.commands == []


async def test_no_operation_in_a_mode_the_integration_does_not_know(
    hass: HomeAssistant, cloud, series1
) -> None:
    unit = await series1(**RUNNING, Mod=9)
    assert "operation_list" not in hass.states.get(TANK).attributes
    with pytest.raises((HomeAssistantError, ServiceValidationError)):
        await call(hass, "water_heater", "set_operation_mode", TANK, operation_mode="heat_pump")
    assert unit.commands == []


async def test_an_operation_the_entity_does_not_have_is_refused(hass: HomeAssistant, cloud, series1) -> None:
    unit = await series1(**RUNNING, Mod=4)
    with pytest.raises((HomeAssistantError, ServiceValidationError)):
        await call(hass, "water_heater", "set_operation_mode", TANK, operation_mode="eco")
    assert unit.commands == []


async def test_rapid_the_unit_did_not_apply_is_an_error(hass: HomeAssistant, cloud, series1) -> None:
    """The mode went through, Rapid did not: an error, and no second try."""
    unit = await series1(**RUNNING, Mod=1)
    unit.refuses = {"FastHtWter"}
    with pytest.raises(HomeAssistantError, match="the applied value could not be confirmed"):
        await call(hass, "water_heater", "set_operation_mode", TANK, operation_mode="performance")
    assert unit.commands == [{"Mod": 4}, {"FastHtWter": 1}]
    assert hass.states.get(TANK).state == "heat_pump"


async def test_no_operation_without_the_rapid_flag(hass: HomeAssistant, cloud, setup_integration) -> None:
    unit = cloud.add("versati_series1", state={**RUNNING, "Mod": 4})
    del unit.state["FastHtWter"]
    await setup_integration()
    await settle(hass, cloud)
    tank = hass.states.get(TANK)
    assert tank.state == "heat_pump"
    assert "operation_list" not in tank.attributes
    with pytest.raises((HomeAssistantError, ServiceValidationError)):
        await call(hass, "water_heater", "turn_off", TANK)
    assert unit.commands == []


async def test_series7_hot_water_is_as_it_was(hass: HomeAssistant, cloud, setup_integration) -> None:
    """A unit without the Rapid function: target only, no operation to choose."""
    unit = cloud.add("versati_series7")
    await setup_integration()
    unit.forget()
    tank = hass.states.get("water_heater.versati_hot_water")
    assert tank.state == "heat_pump"
    assert tank.attributes["supported_features"] == 1
    assert "operation_list" not in tank.attributes
    with pytest.raises((HomeAssistantError, ServiceValidationError)):
        await call(hass, "water_heater", "set_operation_mode", "water_heater.versati_hot_water", operation_mode="off")
    assert unit.commands == []
