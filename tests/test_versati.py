"""Versati air-to-water heat pumps (model 9300): commands and their safeguards.

Two recorded units. Series 7 (#47) answers status requests and is running in
heat + hot water. Series 1, a Versati 5 (#75), never answers one: it reports
its whole state by itself, also after every command, and it has a power flag
per heating zone that goes along with the power.

A command counts only once the unit shows the new value: an acknowledgement
alone is not enough, and a write is never repeated.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .common import call
from .conftest import settle
from .fake_cloud import FakeUnit

# Series 7
WATER7 = "climate.versati_hydraulic_heating"
MODE7 = "select.versati_heat_pump_mode"
POWER7 = "switch.versati_global_heat_pump_power"

# Series 1
WATER1 = "climate.heat_pump_hydraulic_heating"
ROOM1 = "climate.heat_pump_room_thermostat"
MODE1 = "select.heat_pump_heat_pump_mode"
POWER1 = "switch.heat_pump_global_heat_pump_power"

ZONES_ON = {"Pow": 1, "ZonePow1": 1, "ZonePow2": 1}
ZONES_OFF = {"Pow": 0, "ZonePow1": 0, "ZonePow2": 0}


@pytest.fixture
async def series7(cloud, setup_integration) -> FakeUnit:
    unit = cloud.add("versati_series7")
    await setup_integration()
    unit.forget()
    return unit


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


# -- series 7 -----------------------------------------------------------


@pytest.mark.parametrize(
    ("domain", "service", "entity", "data", "commands"),
    [
        ("climate", "set_temperature", WATER7, {"temperature": 42}, [{"HeWatOutTemSet": 42}]),
        ("climate", "set_hvac_mode", WATER7, {"hvac_mode": "off"}, [{"Pow": 0}]),
        ("climate", "turn_off", WATER7, {}, [{"Pow": 0}]),
        # Already heating.
        ("climate", "set_hvac_mode", WATER7, {"hvac_mode": "heat"}, []),
        ("number", "set_value", "number.versati_heating_water_target", {"value": 42}, [{"HeWatOutTemSet": 42}]),
        ("number", "set_value", "number.versati_heating_room_target", {"value": 22}, [{"HeHomTemSet": 22}]),
        ("number", "set_value", "number.versati_dhw_target", {"value": 50}, [{"WatBoxTemSet": 50}]),
        ("select", "select_option", MODE7, {"option": "hot_water"}, [{"Mod": 2}]),
        ("select", "select_option", MODE7, {"option": "heat"}, [{"Mod": 1}]),
        ("switch", "turn_off", POWER7, {}, [{"Pow": 0}]),
    ],
)
async def test_series7_command(
    hass: HomeAssistant,
    cloud,
    series7: FakeUnit,
    domain: str,
    service: str,
    entity: str,
    data: dict[str, Any],
    commands: list[dict[str, Any]],
) -> None:
    await call(hass, domain, service, entity, **data)
    assert series7.commands == commands
    # What was written is what the unit holds, and what Home Assistant shows.
    for command in commands:
        for key, value in command.items():
            assert series7.state[key] == value


async def test_a_command_is_read_back_before_it_shows(
    hass: HomeAssistant, cloud, series7: FakeUnit
) -> None:
    await call(hass, "climate", "set_temperature", WATER7, temperature=42)
    assert [pack["t"] for pack in series7.received] == ["cmd", "status"]
    assert hass.states.get(WATER7).attributes["temperature"] == 42
    assert hass.states.get("number.versati_heating_water_target").state == "42.0"


async def test_switching_on(hass: HomeAssistant, cloud, setup_integration) -> None:
    unit = cloud.add("versati_series7", state={"Pow": 0})
    await setup_integration()
    assert hass.states.get(WATER7).state == "off"
    unit.forget()

    await call(hass, "climate", "set_hvac_mode", WATER7, hvac_mode="heat")
    assert unit.commands == [{"Pow": 1}]
    assert hass.states.get(WATER7).state == "heat"
    assert hass.states.get(POWER7).state == "on"


async def test_heating_from_hot_water_only_keeps_the_hot_water(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    """The mode goes first: a unit that is off takes it for certain."""
    unit = cloud.add("versati_series7", state={"Pow": 0, "Mod": 2})
    await setup_integration()
    unit.forget()

    await call(hass, "climate", "set_hvac_mode", WATER7, hvac_mode="heat")
    assert unit.commands == [{"Mod": 4}, {"Pow": 1}]
    assert hass.states.get(WATER7).state == "heat"
    assert hass.states.get(MODE7).state == "heat_hot_water"


async def test_hot_water_only_shows_the_heating_as_off(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    cloud.add("versati_series7", state={"Mod": 2})
    await setup_integration()
    assert hass.states.get(WATER7).state == "off"
    assert hass.states.get(POWER7).state == "on"
    assert hass.states.get(MODE7).state == "hot_water"


async def test_the_mode_never_switches_the_unit_on(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    unit = cloud.add("versati_series7", state={"Pow": 0})
    await setup_integration()
    unit.forget()
    await call(hass, "select", "select_option", MODE7, option="hot_water")
    assert unit.commands == [{"Mod": 2}]
    assert unit.state["Pow"] == 0


async def test_mode_and_setpoint_in_one_call_are_refused(
    hass: HomeAssistant, cloud, series7: FakeUnit
) -> None:
    """Two commands of which the second may fail would leave half a change."""
    with pytest.raises(HomeAssistantError, match="Send mode and setpoint separately"):
        await call(hass, "climate", "set_temperature", WATER7, temperature=42, hvac_mode="heat")
    assert series7.commands == []


@pytest.mark.parametrize(
    ("domain", "service", "entity", "data"),
    [
        ("climate", "set_temperature", WATER7, {"temperature": 61}),
        ("climate", "set_temperature", WATER7, {"temperature": 19}),
        ("number", "set_value", "number.versati_dhw_target", {"value": 61}),
        ("number", "set_value", "number.versati_dhw_target", {"value": 39}),
        ("number", "set_value", "number.versati_heating_room_target", {"value": 31}),
    ],
)
async def test_a_setpoint_outside_the_limits_is_never_sent(
    hass: HomeAssistant,
    cloud,
    series7: FakeUnit,
    domain: str,
    service: str,
    entity: str,
    data: dict[str, Any],
) -> None:
    with pytest.raises((ServiceValidationError, HomeAssistantError)):
        await call(hass, domain, service, entity, **data)
    assert series7.received == []


async def test_an_unacknowledged_command_is_an_error_and_not_repeated(
    hass: HomeAssistant, cloud, series7: FakeUnit
) -> None:
    series7.acks_commands = False
    series7.executes_commands = False
    with pytest.raises(HomeAssistantError, match="Command not confirmed; it may have executed. No retry."):
        await call(hass, "climate", "set_temperature", WATER7, temperature=42)
    assert series7.commands == [{"HeWatOutTemSet": 42}]
    assert hass.states.get(WATER7).attributes["temperature"] == 40


async def test_a_rejected_command_is_an_error(hass: HomeAssistant, cloud, series7: FakeUnit) -> None:
    series7.command_result = 400
    with pytest.raises(HomeAssistantError, match="Command not confirmed"):
        await call(hass, "climate", "set_temperature", WATER7, temperature=42)
    assert series7.commands == [{"HeWatOutTemSet": 42}]


async def test_an_acknowledged_command_the_unit_did_not_apply_is_an_error(
    hass: HomeAssistant, cloud, series7: FakeUnit
) -> None:
    """The unit says yes and keeps the old value: three reads, one write."""
    series7.refuses = {"Mod"}
    with pytest.raises(HomeAssistantError, match="the applied value could not be confirmed"):
        await call(hass, "select", "select_option", MODE7, option="hot_water")
    assert series7.commands == [{"Mod": 2}]
    assert len(series7.status_requests) == 3
    assert hass.states.get(MODE7).state == "heat_hot_water"


@pytest.mark.parametrize(
    "state",
    [
        # A series nobody has checked the columns and modes of.
        {"VersatiSeries": 3},
        # Fahrenheit: the limits are in Celsius.
        {"TemUn": 1},
    ],
)
async def test_an_unverified_unit_is_read_only(
    hass: HomeAssistant, cloud, setup_integration, state: dict[str, Any]
) -> None:
    unit = cloud.add("versati_series7", state=state)
    await setup_integration()

    assert hass.states.get("sensor.versati_water_outlet_temperature").state == "36.2"
    shown = hass.states.get(WATER7)
    assert shown.state == "heat"
    assert shown.attributes["writes_enabled"] is False
    assert shown.attributes["supported_features"] == 0
    for domain in ("number", "select", "switch"):
        assert hass.states.async_entity_ids(domain) == []

    unit.forget()
    with pytest.raises(HomeAssistantError):
        await call(hass, "climate", "set_hvac_mode", WATER7, hvac_mode="off")
    assert unit.commands == []


async def test_an_unknown_model_is_not_a_heat_pump(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    """Hydraulic columns alone are not enough: the model has to be a known one."""
    cloud.add("versati_series7", mid="9999")
    await setup_integration()
    assert hass.states.get(WATER7) is None
    assert hass.states.async_entity_ids("number") == []


# -- series 1 -----------------------------------------------------------


async def test_series1_thermostats(hass: HomeAssistant, cloud, series1) -> None:
    """Water and room thermostat of a running unit, as Gree+ shows them."""
    await series1(Pow=1, ZonePow1=1, ZonePow2=1, Mod=4, RmoHomTemHi=122, RmoHomTemLo=1)

    registry = er.async_get(hass)
    assert registry.async_get(WATER1).unique_id == "aa0000000005_versati_heating"
    assert registry.async_get(ROOM1).unique_id == "aa0000000005_versati_room_heating"

    water, room = hass.states.get(WATER1), hass.states.get(ROOM1)
    assert (water.state, water.attributes["current_temperature"], water.attributes["temperature"]) == ("heat", 22.8, 45)
    assert (water.attributes["min_temp"], water.attributes["max_temp"]) == (20, 60)
    assert (room.state, room.attributes["current_temperature"], room.attributes["temperature"]) == ("heat", 22.1, 21)
    assert (room.attributes["min_temp"], room.attributes["max_temp"]) == (18, 30)


@pytest.mark.parametrize(
    ("domain", "service", "entity", "data", "commands"),
    [
        # Power takes both zone flags along, as Gree+ does.
        ("climate", "set_hvac_mode", ROOM1, {"hvac_mode": "heat"}, [ZONES_ON]),
        ("climate", "turn_on", ROOM1, {}, [ZONES_ON]),
        ("climate", "set_hvac_mode", WATER1, {"hvac_mode": "heat"}, [ZONES_ON]),
        ("switch", "turn_on", POWER1, {}, [ZONES_ON]),
        ("climate", "set_temperature", ROOM1, {"temperature": 22}, [{"HeHomTemSet": 22}]),
        ("climate", "set_temperature", WATER1, {"temperature": 42}, [{"HeWatOutTemSet": 42}]),
        ("number", "set_value", "number.heat_pump_dhw_target", {"value": 52}, [{"WatBoxTemSet": 52}]),
        ("select", "select_option", MODE1, {"option": "heat_hot_water"}, [{"Mod": 4}]),
    ],
)
async def test_series1_command(
    hass: HomeAssistant,
    cloud,
    series1,
    domain: str,
    service: str,
    entity: str,
    data: dict[str, Any],
    commands: list[dict[str, Any]],
) -> None:
    unit = await series1()
    await call(hass, domain, service, entity, **data)
    assert unit.commands == commands


async def test_series1_switching_on_and_off(hass: HomeAssistant, cloud, series1) -> None:
    """Both thermostats and the switch show one unit."""
    unit = await series1()
    assert [hass.states.get(e).state for e in (WATER1, ROOM1, POWER1)] == ["off", "off", "off"]

    await call(hass, "climate", "set_hvac_mode", ROOM1, hvac_mode="heat")
    assert [hass.states.get(e).state for e in (WATER1, ROOM1, POWER1)] == ["heat", "heat", "on"]

    # Heating while heating sends nothing.
    unit.forget()
    await call(hass, "climate", "set_hvac_mode", ROOM1, hvac_mode="heat")
    assert unit.commands == []

    await call(hass, "climate", "turn_off", WATER1)
    assert unit.commands == [ZONES_OFF]
    assert [hass.states.get(e).state for e in (WATER1, ROOM1, POWER1)] == ["off", "off", "off"]


async def test_series1_is_confirmed_by_its_own_report(hass: HomeAssistant, cloud, series1) -> None:
    """No status request is answered, so the value comes from what the unit reports."""
    unit = await series1()
    await call(hass, "climate", "set_temperature", ROOM1, temperature=22)
    assert unit.state["HeHomTemSet"] == 22
    assert hass.states.get(ROOM1).attributes["temperature"] == 22
    assert hass.states.get(WATER1).attributes["temperature"] == 45


async def test_series1_zones_switched_separately_are_left_alone(
    hass: HomeAssistant, cloud, series1
) -> None:
    unit = await series1(Pow=1, ZonePow1=1, ZonePow2=0)
    await call(hass, "switch", "turn_off", POWER1)
    assert unit.commands == [{"Pow": 0}]
    assert unit.state["ZonePow1"] == 1


async def test_series1_heating_from_hot_water_only(hass: HomeAssistant, cloud, series1) -> None:
    unit = await series1(Mod=2)
    await call(hass, "climate", "set_hvac_mode", ROOM1, hvac_mode="heat")
    assert unit.commands == [{"Mod": 4}, ZONES_ON]
    assert hass.states.get(ROOM1).state == "heat"


async def test_series1_a_room_target_above_the_limit_is_never_sent(
    hass: HomeAssistant, cloud, series1
) -> None:
    unit = await series1()
    with pytest.raises((ServiceValidationError, HomeAssistantError)):
        await call(hass, "climate", "set_temperature", ROOM1, temperature=35)
    assert unit.commands == []


async def test_series1_without_a_room_sensor_has_no_room_thermostat(
    hass: HomeAssistant, cloud, series1
) -> None:
    """It appears, once, when the sensor starts reporting."""
    unit = await series1(RmoHomTemHi=100, RmoHomTemLo=0)
    assert hass.states.get(WATER1) is not None
    assert hass.states.get(ROOM1) is None

    await cloud.push(unit, RmoHomTemHi=121, RmoHomTemLo=5)
    await settle(hass, cloud)
    assert hass.states.get(ROOM1).attributes["current_temperature"] == 21.5

    await cloud.push(unit, RmoHomTemHi=121, RmoHomTemLo=7)
    await settle(hass, cloud)
    assert hass.states.get(ROOM1).attributes["current_temperature"] == 21.7
    assert hass.states.async_entity_ids("climate") == sorted([WATER1, ROOM1])


async def test_series1_changes_made_elsewhere_show_at_once(
    hass: HomeAssistant, cloud, series1
) -> None:
    """A report needs no poll."""
    unit = await series1()
    await cloud.push(unit, **ZONES_ON, WatBoxTemSet=55)
    await settle(hass, cloud)
    assert hass.states.get(POWER1).state == "on"
    assert hass.states.get("number.heat_pump_dhw_target").state == "55.0"


async def test_series1_stays_available_between_reports(
    hass: HomeAssistant, cloud, series1, poll
) -> None:
    """Unanswered polls are how this series works, not an outage."""
    await series1()
    for _ in range(5):
        await poll()
    assert hass.states.get(WATER1).state == "off"
    assert hass.states.get("sensor.heat_pump_dhw_temperature").state == "54.8"


async def test_series1_half_a_temperature_is_no_temperature(
    hass: HomeAssistant, cloud, series1
) -> None:
    """Whole degrees and tenths from different reports are never put together."""
    unit = await series1()
    sensor = "sensor.heat_pump_water_outlet_temperature"
    assert hass.states.get(sensor).state == "22.8"

    without_tenths = [key for key in unit.state if key != "AllOutWatTemLo"]
    await cloud.push(unit, keys=without_tenths, AllOutWatTemHi=130)
    await settle(hass, cloud)
    assert hass.states.get(sensor).state == "unknown"

    await cloud.push(unit, AllOutWatTemLo=4)
    await settle(hass, cloud)
    assert hass.states.get(sensor).state == "30.4"


async def test_series7_without_usable_setpoints_gets_no_entities(
    hass: HomeAssistant, cloud, setup_integration, poll, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing is created from a state that does not show what the unit is."""
    unit = cloud.add("versati_series7", state={"HeHomTemSet": 0, "WatBoxTemSet": 0})
    await setup_integration()
    await poll()
    assert hass.states.async_all() == []
    assert caplog.text.count("the heat-pump profile cannot be recognized") == 1

    unit.state.update(HeHomTemSet=21, WatBoxTemSet=50)
    await poll()
    assert hass.states.get(WATER7) is not None

