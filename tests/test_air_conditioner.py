"""Air conditioners: what a service call sends to the unit.

Every test starts from the recorded split unit: off, heating mode, 21 °C,
fan medium-low, both swings on, panel light on.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.gree_cloud.const import CONF_EXTERNAL_TEMPERATURE_SENSORS

from .common import call
from .conftest import settle
from .fake_cloud import FakeUnit

CLIMATE = "climate.living_room"


@pytest.fixture
async def unit(cloud, setup_integration) -> FakeUnit:
    unit = cloud.add("split_ac")
    await setup_integration()
    unit.forget()
    return unit


@pytest.mark.parametrize(
    ("service", "data", "commands", "state", "attributes"),
    [
        (
            "set_temperature",
            {"temperature": 23},
            [{"SetTem": 23, "TemRec": 0, "Add0.5": 0}],
            "off",
            {"temperature": 23},
        ),
        # The mode goes out before the power, in separate commands.
        ("set_hvac_mode", {"hvac_mode": "auto"}, [{"Mod": 0}, {"Pow": 1}], "auto", {}),
        ("set_hvac_mode", {"hvac_mode": "cool"}, [{"Mod": 1}, {"Pow": 1}], "cool", {}),
        ("set_hvac_mode", {"hvac_mode": "dry"}, [{"Mod": 2}, {"Pow": 1}], "dry", {}),
        ("set_hvac_mode", {"hvac_mode": "fan_only"}, [{"Mod": 3}, {"Pow": 1}], "fan_only", {}),
        # Already in heating mode: only the power is new.
        ("set_hvac_mode", {"hvac_mode": "heat"}, [{"Pow": 1}], "heat", {}),
        ("turn_on", {}, [{"Pow": 1}], "heat", {}),
        (
            "set_temperature",
            {"temperature": 24, "hvac_mode": "cool"},
            [{"Mod": 1}, {"Pow": 1}, {"SetTem": 24, "TemRec": 0, "Add0.5": 0}],
            "cool",
            {"temperature": 24},
        ),
        ("set_fan_mode", {"fan_mode": "auto"}, [{"WdSpd": 0}], "off", {"fan_mode": "auto"}),
        ("set_fan_mode", {"fan_mode": "low"}, [{"WdSpd": 1}], "off", {"fan_mode": "low"}),
        ("set_fan_mode", {"fan_mode": "medium"}, [{"WdSpd": 3}], "off", {"fan_mode": "medium"}),
        (
            "set_fan_mode",
            {"fan_mode": "medium-high"},
            [{"WdSpd": 4}],
            "off",
            {"fan_mode": "medium-high"},
        ),
        ("set_fan_mode", {"fan_mode": "high"}, [{"WdSpd": 5}], "off", {"fan_mode": "high"}),
        (
            "set_swing_mode",
            {"swing_mode": "default"},
            [{"SwUpDn": 0}],
            "off",
            {"swing_mode": "default"},
        ),
        (
            "set_swing_mode",
            {"swing_mode": "fixed_upper"},
            [{"SwUpDn": 2}],
            "off",
            {"swing_mode": "fixed_upper"},
        ),
        (
            "set_swing_mode",
            {"swing_mode": "fixed_lower"},
            [{"SwUpDn": 6}],
            "off",
            {"swing_mode": "fixed_lower"},
        ),
        (
            "set_swing_horizontal_mode",
            {"swing_horizontal_mode": "left"},
            [{"SwingLfRig": 2}],
            "off",
            {"swing_horizontal_mode": "left"},
        ),
        (
            "set_swing_horizontal_mode",
            {"swing_horizontal_mode": "right"},
            [{"SwingLfRig": 6}],
            "off",
            {"swing_horizontal_mode": "right"},
        ),
        ("set_preset_mode", {"preset_mode": "eco"}, [{"SvSt": 1}], "off", {"preset_mode": "eco"}),
        ("set_preset_mode", {"preset_mode": "boost"}, [{"Tur": 1}], "off", {"preset_mode": "boost"}),
        (
            "set_preset_mode",
            {"preset_mode": "sleep"},
            [{"SwhSlp": 1}, {"SlpMod": 1}],
            "off",
            {"preset_mode": "sleep"},
        ),
        ("set_preset_mode", {"preset_mode": "away"}, [{"StHt": 1}], "off", {"preset_mode": "away"}),
    ],
)
async def test_climate_command(
    hass: HomeAssistant,
    cloud,
    unit: FakeUnit,
    service: str,
    data: dict[str, Any],
    commands: list[dict[str, Any]],
    state: str,
    attributes: dict[str, Any],
) -> None:
    await call(hass, "climate", service, CLIMATE, **data)
    assert unit.commands == commands
    shown = hass.states.get(CLIMATE)
    assert shown.state == state
    assert {key: shown.attributes[key] for key in attributes} == attributes


async def test_turning_off(hass: HomeAssistant, cloud, setup_integration) -> None:
    unit = cloud.add("split_ac", state={"Pow": 1})
    await setup_integration()
    assert hass.states.get(CLIMATE).state == "heat"

    unit.forget()
    await call(hass, "climate", "set_hvac_mode", CLIMATE, hvac_mode="off")
    assert unit.commands == [{"Pow": 0}]
    assert hass.states.get(CLIMATE).state == "off"

    await call(hass, "climate", "turn_on", CLIMATE)
    await call(hass, "climate", "turn_off", CLIMATE)
    assert unit.commands[1:] == [{"Pow": 1}, {"Pow": 0}]


async def test_leaving_a_preset_switches_it_off(hass: HomeAssistant, cloud, unit: FakeUnit) -> None:
    await call(hass, "climate", "set_preset_mode", CLIMATE, preset_mode="boost")
    await call(hass, "climate", "set_preset_mode", CLIMATE, preset_mode="eco")
    await call(hass, "climate", "set_preset_mode", CLIMATE, preset_mode="none")
    assert unit.commands == [{"Tur": 1}, {"Tur": 0}, {"SvSt": 1}, {"SvSt": 0}]
    assert hass.states.get(CLIMATE).attributes["preset_mode"] == "none"


async def test_what_the_unit_took_shows_after_the_next_poll(
    hass: HomeAssistant, cloud, unit: FakeUnit, poll
) -> None:
    """The state comes from the unit, not from what Home Assistant sent."""
    await call(hass, "climate", "set_temperature", CLIMATE, temperature=25, hvac_mode="cool")
    await poll()
    shown = hass.states.get(CLIMATE)
    assert (shown.state, shown.attributes["temperature"]) == ("cool", 25)
    assert unit.state["SetTem"] == 25


async def test_changes_made_elsewhere_show_after_the_next_poll(
    hass: HomeAssistant, cloud, unit: FakeUnit, poll
) -> None:
    """The remote control, the Gree+ app."""
    unit.state.update(Pow=1, Mod=1, SetTem=26, WdSpd=5, TemSen=67)
    await poll()
    shown = hass.states.get(CLIMATE)
    assert shown.state == "cool"
    assert shown.attributes["temperature"] == 26
    assert shown.attributes["current_temperature"] == 27
    assert shown.attributes["fan_mode"] == "high"


@pytest.mark.parametrize(
    ("switch", "turn_on", "turn_off"),
    [
        ("panel_light", {"Lig": 1}, {"Lig": 0}),
        ("quiet", {"Quiet": 2}, {"Quiet": 0}),
        ("fresh_air", {"Air": 1}, {"Air": 0}),
        ("xfan", {"Blo": 1}, {"Blo": 0}),
    ],
)
async def test_switch(
    hass: HomeAssistant,
    cloud,
    setup_integration,
    switch: str,
    turn_on: dict[str, int],
    turn_off: dict[str, int],
) -> None:
    unit = cloud.add("split_ac", state={"Lig": 0})
    await setup_integration()
    unit.forget()
    entity = f"switch.living_room_{switch}"
    assert hass.states.get(entity).state == "off"

    await call(hass, "switch", "turn_on", entity)
    assert hass.states.get(entity).state == "on"
    await call(hass, "switch", "turn_off", entity)
    assert hass.states.get(entity).state == "off"
    assert unit.commands == [turn_on, turn_off]


async def test_beeper_off_silences_every_command(hass: HomeAssistant, cloud, unit: FakeUnit) -> None:
    """The flag rides on the commands; switching it sends nothing (#50)."""
    await call(hass, "switch", "turn_off", "switch.living_room_beeper")
    assert unit.commands == []
    assert hass.states.get("switch.living_room_beeper").state == "off"

    await call(hass, "climate", "set_temperature", CLIMATE, temperature=22)
    await call(hass, "switch", "turn_off", "switch.living_room_panel_light")
    assert unit.commands == [
        {"SetTem": 22, "TemRec": 0, "Add0.5": 0, "Buzzer_ON_OFF": 1},
        {"Lig": 0, "Buzzer_ON_OFF": 1},
    ]

    await call(hass, "switch", "turn_on", "switch.living_room_beeper")
    await call(hass, "climate", "set_temperature", CLIMATE, temperature=23)
    assert unit.commands[2:] == [{"SetTem": 23, "TemRec": 0, "Add0.5": 0}]


async def test_beeper_stays_off_across_a_restart(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    """The unit does not report the flag, so Home Assistant remembers it."""
    mock_restore_cache(hass, [State("switch.living_room_beeper", "off")])
    unit = cloud.add("split_ac")
    await setup_integration()
    assert hass.states.get("switch.living_room_beeper").state == "off"

    unit.forget()
    await call(hass, "climate", "turn_on", CLIMATE)
    assert unit.commands == [{"Pow": 1, "Buzzer_ON_OFF": 1}]


@pytest.mark.parametrize(("option", "gear"), [("a1", 2), ("a2", 4), ("off", 0)])
async def test_power_limit(
    hass: HomeAssistant, cloud, setup_integration, option: str, gear: int
) -> None:
    """The gears are 0, 2 and 4, as captured from the app (#43)."""
    unit = cloud.add("split_ac", state={"PowReduceType": 1, "PowReduceGear": 1})
    await setup_integration()
    unit.forget()
    entity = "select.living_room_power_limit"
    # A gear the app never sends is shown as unknown, not as a guess.
    assert hass.states.get(entity).state == "unknown"
    assert hass.states.get(entity).attributes["raw_gear"] == 1

    await call(hass, "select", "select_option", entity, option=option)
    assert unit.commands == [{"PowReduceGear": gear}]
    assert hass.states.get(entity).state == option


async def test_no_power_limit_on_a_unit_without_it(hass: HomeAssistant, cloud, unit: FakeUnit) -> None:
    assert hass.states.async_entity_ids("select") == []


async def test_an_unanswered_command_does_not_fail_the_call(
    hass: HomeAssistant, cloud, unit: FakeUnit, caplog: pytest.LogCaptureFixture
) -> None:
    """The unit may have taken it; the next poll tells."""
    unit.acks_commands = False
    with caplog.at_level(logging.WARNING):
        await call(hass, "climate", "turn_on", CLIMATE)
    assert unit.commands == [{"Pow": 1}]
    assert hass.states.get(CLIMATE).state == "heat"


# -- half degrees ---------------------------------------------------------


@pytest.mark.parametrize(
    ("temperature", "command"),
    [
        (22.5, {"SetTem": 22, "TemRec": 1, "SetDeciTem": 225, "Add0.5": 1}),
        (23, {"SetTem": 23, "TemRec": 0, "SetDeciTem": 230, "Add0.5": 0}),
        (23.5, {"SetTem": 23, "TemRec": 1, "SetDeciTem": 235, "Add0.5": 1}),
    ],
)
async def test_half_degrees(
    hass: HomeAssistant, cloud, setup_integration, poll, temperature: float, command: dict[str, int]
) -> None:
    """A unit that reports HalfTemEn takes tenths in SetDeciTem (#49)."""
    unit = cloud.add("commercial_ac")
    await setup_integration()
    unit.forget()
    entity = "climate.upstairs"
    assert hass.states.get(entity).attributes["target_temp_step"] == 0.5

    await call(hass, "climate", "set_temperature", entity, temperature=temperature)
    assert unit.commands == [command]
    await poll()
    assert hass.states.get(entity).attributes["temperature"] == temperature


async def test_whole_degrees_only_without_half_degree_support(
    hass: HomeAssistant, cloud, unit: FakeUnit
) -> None:
    assert hass.states.get(CLIMATE).attributes["target_temp_step"] == 1


# -- external temperature sensor (#10) ------------------------------------


@pytest.fixture
async def with_sensor(hass: HomeAssistant, cloud, config_entry, setup_integration) -> FakeUnit:
    hass.states.async_set("sensor.room", "22.46", {"unit_of_measurement": "°C"})
    unit = cloud.add("split_ac")
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_EXTERNAL_TEMPERATURE_SENSORS: {unit.mac: "sensor.room"}},
    )
    await setup_integration()
    return unit


async def test_external_sensor_supplies_the_current_temperature(
    hass: HomeAssistant, cloud, with_sensor: FakeUnit
) -> None:
    shown = hass.states.get(CLIMATE)
    assert shown.attributes["current_temperature"] == 22.5
    assert shown.attributes["external_temperature_sensor"] == "sensor.room"

    hass.states.async_set("sensor.room", "23.1", {"unit_of_measurement": "°C"})
    await settle(hass, cloud)
    assert hass.states.get(CLIMATE).attributes["current_temperature"] == 23.1


async def test_external_sensor_in_fahrenheit(hass: HomeAssistant, cloud, with_sensor: FakeUnit) -> None:
    hass.states.async_set("sensor.room", "68", {"unit_of_measurement": "°F"})
    await settle(hass, cloud)
    assert hass.states.get(CLIMATE).attributes["current_temperature"] == 20.0


@pytest.mark.parametrize("reading", ["unavailable", "unknown", "nonsense"])
async def test_unit_reading_is_used_while_the_external_sensor_has_none(
    hass: HomeAssistant, cloud, with_sensor: FakeUnit, reading: str
) -> None:
    hass.states.async_set("sensor.room", reading)
    await settle(hass, cloud)
    assert hass.states.get(CLIMATE).attributes["current_temperature"] == 19


async def test_other_units_keep_their_own_reading(
    hass: HomeAssistant, cloud, config_entry, setup_integration
) -> None:
    hass.states.async_set("sensor.room", "25.0", {"unit_of_measurement": "°C"})
    cloud.add("split_ac")
    cloud.add("split_ac", name="Bedroom", mac="aa0000000009")
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_EXTERNAL_TEMPERATURE_SENSORS: {"aa0000000009": "sensor.room"}},
    )
    await setup_integration()
    assert hass.states.get(CLIMATE).attributes["current_temperature"] == 19
    assert "external_temperature_sensor" not in hass.states.get(CLIMATE).attributes
    assert hass.states.get("climate.bedroom").attributes["current_temperature"] == 25.0


# -- indoor units behind a controller (#6) --------------------------------


async def test_vrf_head_is_commanded_through_its_controller(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    """The command goes to the module and names the head as ``sub``."""
    office = cloud.add("vrf_head", name="Office", mac="bb0000000001")
    kitchen = cloud.add("vrf_head", name="Kitchen", mac="bb0000000002", state={"Pow": 0})
    await setup_integration()
    seen = len(cloud.gateway_requests)

    await call(hass, "climate", "set_temperature", "climate.office", temperature=22)
    await call(hass, "climate", "set_hvac_mode", "climate.kitchen", hvac_mode="cool")

    module = office.module_mac
    assert cloud.gateway_requests[seen:] == [
        {
            "route": module,
            "tcid": module,
            "pack": {
                "t": "cmd",
                "opt": ["SetTem", "TemRec", "Add0.5"],
                "p": [22, 0, 0],
                "sub": "bb0000000001",
            },
        },
        {
            "route": module,
            "tcid": module,
            "pack": {"t": "cmd", "opt": ["Pow"], "p": [1], "sub": "bb0000000002"},
        },
    ]
    assert office.commands == [{"SetTem": 22, "TemRec": 0, "Add0.5": 0}]
    assert kitchen.commands == [{"Pow": 1}]
    assert hass.states.get("climate.office").attributes["temperature"] == 22
    assert hass.states.get("climate.kitchen").state == "cool"


async def test_unit_set_to_fahrenheit(hass: HomeAssistant, cloud, setup_integration, poll) -> None:
    """Its numbers are Fahrenheit from the first state on, not after a change."""
    unit = cloud.add("split_ac", state={"TemUn": 1, "SetTem": 21, "TemRec": 0})
    await setup_integration()
    # 21 with TemRec 0 stands for 69 °F; Home Assistant here shows Celsius.
    state = hass.states.get(CLIMATE)
    assert state.attributes["temperature"] == 21
    assert (state.attributes["min_temp"], state.attributes["max_temp"]) == (8, 30)

    unit.forget()
    await call(hass, "climate", "set_temperature", CLIMATE, temperature=24)
    assert unit.commands == [{"SetTem": 24, "TemRec": 0, "Add0.5": 0}]
    await poll()
    assert hass.states.get(CLIMATE).attributes["temperature"] == 24


async def test_unit_switched_to_fahrenheit_while_running(
    hass: HomeAssistant, cloud, unit: FakeUnit, poll
) -> None:
    unit.state.update(TemUn=1, SetTem=27, TemRec=0)  # 80 °F
    await poll()
    assert hass.states.get(CLIMATE).attributes["temperature"] == 27
    unit.state.update(TemUn=0, SetTem=23)
    await poll()
    assert hass.states.get(CLIMATE).attributes["temperature"] == 23


async def test_energy_counter(hass: HomeAssistant, cloud, setup_integration, poll) -> None:
    """Tenths of a kWh, only on a unit that reports the counter."""
    unit = cloud.add("split_ac", state={"ElcAll": 1234})
    await setup_integration()
    state = hass.states.get("sensor.living_room_energy")
    assert state.state == "123.4"
    assert state.attributes["unit_of_measurement"] == "kWh"
    assert state.attributes["state_class"] == "total_increasing"

    unit.state["ElcAll"] = 1240
    await poll()
    assert hass.states.get("sensor.living_room_energy").state == "124.0"


async def test_no_energy_sensor_without_the_counter(hass: HomeAssistant, cloud, unit: FakeUnit) -> None:
    assert hass.states.get("sensor.living_room_energy") is None

