"""Units that stop answering, a broker connection that drops, and getting back."""

from __future__ import annotations

import logging

import pytest
from homeassistant.core import HomeAssistant

from .common import call
from .conftest import settle

AC = "climate.living_room"


def _warnings(caplog: pytest.LogCaptureFixture, text: str) -> int:
    return sum(
        text in record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING
    )


async def test_two_missed_polls_are_forgiven(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    """The cloud loses a request now and then; the state stays."""
    unit = cloud.add("split_ac")
    await setup_integration()

    unit.answers_status = False
    await poll()
    await poll()
    assert hass.states.get(AC).state == "off"
    assert hass.states.get(AC).attributes["temperature"] == 21

    unit.answers_status = True
    unit.state["SetTem"] = 24
    await poll()
    assert hass.states.get(AC).attributes["temperature"] == 24


async def test_an_outage_and_the_way_back(
    hass: HomeAssistant, cloud, setup_integration, poll, caplog: pytest.LogCaptureFixture
) -> None:
    unit = cloud.add("split_ac")
    other = cloud.add("split_ac", name="Bedroom", mac="aa00000000b2")
    await setup_integration()

    unit.answers_status = False
    for _ in range(3):
        await poll()
    assert hass.states.get(AC).state == "unavailable"
    assert hass.states.get("switch.living_room_panel_light").state == "unavailable"
    assert hass.states.get("sensor.living_room_outdoor_temperature").state == "unavailable"
    # Only the unit that is away.
    assert hass.states.get("climate.bedroom").state == "off"
    assert other.status_requests

    # Said once, however long it lasts.
    for _ in range(3):
        await poll()
    assert _warnings(caplog, "gree_cloud-Living Room is unavailable after 3 timeouts") == 1

    unit.answers_status = True
    unit.state["Pow"] = 1
    await poll()
    assert hass.states.get(AC).state == "heat"

    # The next outage is announced again.
    unit.answers_status = False
    for _ in range(3):
        await poll()
    assert hass.states.get(AC).state == "unavailable"
    assert _warnings(caplog, "gree_cloud-Living Room is unavailable after 3 timeouts") == 2


async def test_a_unit_that_is_silent_at_setup_is_kept(
    hass: HomeAssistant, cloud, setup_integration, poll, caplog: pytest.LogCaptureFixture
) -> None:
    """It starts unavailable, not as a made-up "off", and comes up by itself."""
    unit = cloud.add("split_ac", answers_status=False)
    cloud.add("split_ac", name="Bedroom", mac="aa00000000b2")
    await setup_integration()

    assert _warnings(caplog, "Cloud device Living Room did not answer during setup") == 1
    assert hass.states.get(AC).state == "unavailable"
    assert hass.states.get("switch.living_room_panel_light").state == "unavailable"
    assert hass.states.get("climate.bedroom").state == "off"

    await poll()
    assert hass.states.get(AC).state == "unavailable"

    unit.answers_status = True
    await poll()
    assert hass.states.get(AC).state == "off"
    assert hass.states.get(AC).attributes["current_temperature"] == 19
    assert hass.states.get("switch.living_room_panel_light").state == "on"


async def test_a_heat_pump_that_is_silent_at_setup_gets_its_entities_later(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    """What it is shows only in its state, so the entities wait for that (#75)."""
    unit = cloud.add("versati_series7", answers_status=False)
    await setup_integration()
    assert hass.states.async_all() == []

    await poll()
    assert hass.states.async_all() == []

    unit.answers_status = True
    await poll()
    assert hass.states.get("climate.versati_hydraulic_heating").state == "heat"
    assert hass.states.get("sensor.versati_water_outlet_temperature").state == "36.2"
    created = len(hass.states.async_all())

    await poll()
    assert len(hass.states.async_all()) == created


async def test_a_module_the_gateway_reports_offline(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    unit = cloud.add("vrf_head")
    await setup_integration()
    assert hass.states.get("climate.head").state == "cool"

    cloud.offline.add(unit.module_mac)
    for _ in range(3):
        await poll()
    assert hass.states.get("climate.head").state == "unavailable"

    cloud.offline.clear()
    await poll()
    assert hass.states.get("climate.head").state == "cool"


# -- the broker connection ---------------------------------------------------


async def test_a_dropped_connection_is_replaced_at_the_next_poll(
    hass: HomeAssistant, cloud, setup_integration, poll, caplog: pytest.LogCaptureFixture
) -> None:
    """The broker drops the connection when the token expires; a new login brings a new one."""
    unit = cloud.add("split_ac")
    other = cloud.add("split_ac", name="Bedroom", mac="aa00000000b2")
    await setup_integration()

    cloud.drop_connection()
    unit.state["SetTem"] = 24
    await poll()

    assert _warnings(caplog, "MQTT disconnected — attempting to reconnect") == 1
    assert (cloud.logins, cloud.connect_attempts, len(cloud.sessions)) == (2, 2, 2)
    assert hass.states.get(AC).attributes["temperature"] == 24
    assert hass.states.get("climate.bedroom").state == "off"

    # Both units talk through the new connection from now on.
    unit.forget()
    other.forget()
    unit.state["SetTem"] = 25
    await poll()
    assert unit.status_requests and other.status_requests
    assert hass.states.get(AC).attributes["temperature"] == 25
    assert len(cloud.sessions) == 2

    await call(hass, "climate", "set_temperature", AC, temperature=22)
    assert unit.commands == [{"SetTem": 22, "TemRec": 0, "Add0.5": 0}]


async def test_a_command_on_a_dropped_connection_is_sent_after_reconnecting(
    hass: HomeAssistant, cloud, setup_integration
) -> None:
    """What the user asked for, not what the unit reported while reconnecting."""
    unit = cloud.add("split_ac")
    await setup_integration()
    unit.forget()

    cloud.drop_connection()
    await call(hass, "climate", "set_temperature", AC, temperature=24)
    await settle(hass, cloud)

    assert unit.commands == [{"SetTem": 24, "TemRec": 0, "Add0.5": 0}]
    assert len(cloud.sessions) == 2
    assert hass.states.get(AC).attributes["temperature"] == 24


async def test_a_failing_reconnect_is_tried_again(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    cloud.add("split_ac")
    await setup_integration()

    cloud.drop_connection()
    cloud.login_error = TimeoutError()
    await poll()
    await poll()
    assert hass.states.get(AC).state == "off"
    await poll()
    assert hass.states.get(AC).state == "unavailable"
    assert cloud.logins == 4

    cloud.login_error = None
    await poll()
    assert hass.states.get(AC).state == "off"
    assert len(cloud.sessions) == 2


async def test_a_heat_pump_command_on_a_dropped_connection_is_an_error(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    """Never silently lost, never repeated; the next poll reconnects."""
    unit = cloud.add("versati_series7")
    await setup_integration()
    unit.forget()

    cloud.drop_connection()
    with pytest.raises(Exception):
        await call(hass, "climate", "set_temperature", "climate.versati_hydraulic_heating", temperature=42)
    assert unit.commands == []

    await poll()
    await call(hass, "climate", "set_temperature", "climate.versati_hydraulic_heating", temperature=42)
    assert unit.commands == [{"HeWatOutTemSet": 42}]
