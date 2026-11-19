"""Asking a Versati series 1 to report (#75).

That series leaves status requests unanswered. Gree+ sends it a request for
a report once a minute; the unit acknowledges that and then sends its whole
state by itself, and its changes for the time being. Left alone it reports
nothing, so the integration sends the same request with every poll, and once
to a heat pump that was never heard from. No other unit ever gets it.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from .conftest import settle

REQUEST = {"t": "freqCount", "opt": ["SendFreq"], "p": [1], "mac": "aa0000000005"}
WATER = "climate.heat_pump_hydraulic_heating"
TANK = "water_heater.heat_pump_hot_water"


def kinds(unit) -> list[str]:
    return [pack["t"] for pack in unit.received]


async def test_entities_without_the_app(hass: HomeAssistant, cloud, setup_integration) -> None:
    """After a restart the unit is asked once its status request stays unanswered."""
    unit = cloud.add("versati_series1")
    await setup_integration()
    await settle(hass, cloud)
    assert kinds(unit)[:2] == ["status", "freqCount"]
    assert unit.report_requests == [REQUEST] * len(unit.report_requests)
    assert hass.states.get(WATER).state == "off"
    assert hass.states.get(TANK).attributes["temperature"] == unit.state["WatBoxTemSet"]


async def test_poll_asks_for_a_report(hass: HomeAssistant, cloud, setup_integration, poll) -> None:
    """The state follows the unit with nobody else asking, and no status request is sent."""
    unit = cloud.add("versati_series1")
    await setup_integration()
    await settle(hass, cloud)
    unit.forget()

    # Changed at the unit; it tells nobody.
    unit.state["WatBoxTemSet"] = 47
    await poll()
    await settle(hass, cloud)
    assert unit.received == [REQUEST]
    assert hass.states.get(TANK).attributes["temperature"] == 47

    unit.state["WatBoxTemSet"] = 52
    await poll()
    await settle(hass, cloud)
    assert unit.received == [REQUEST] * 2
    assert hass.states.get(TANK).attributes["temperature"] == 52


async def test_report_ahead_of_the_acknowledgement(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    """Seen once in seven: the state arrives first and ends the wait."""
    unit = cloud.add("versati_series1", reports_before_ack=True)
    await setup_integration()
    await settle(hass, cloud)
    unit.forget()

    unit.state["WatBoxTemSet"] = 47
    await poll()
    await settle(hass, cloud)
    assert unit.received == [REQUEST]
    assert hass.states.get(TANK).attributes["temperature"] == 47


async def test_unit_that_does_not_acknowledge_is_asked_its_state(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    """No acknowledgement: the poll goes on to the status request, as before."""
    unit = cloud.add("versati_series1")
    await setup_integration()
    await settle(hass, cloud)
    unit.forget()

    unit.reports_on_request = False
    await poll()
    assert kinds(unit) == ["freqCount", "status"]
    assert hass.states.get(WATER).state == "off"

    # Back again: one request, and the state is current.
    unit.forget()
    unit.reports_on_request = True
    unit.state["WatBoxTemSet"] = 47
    await poll()
    await settle(hass, cloud)
    assert unit.received == [REQUEST]
    assert hass.states.get(TANK).attributes["temperature"] == 47


async def test_silent_heat_pump_is_asked_after_every_unanswered_poll(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    """Never heard from: the status request first, exactly as before, then the ask."""
    unit = cloud.add("versati_series1", reports_on_request=False)
    await setup_integration()
    assert hass.states.get(WATER) is None
    unit.forget()

    await poll()
    assert kinds(unit) == ["status", "freqCount"]
    assert hass.states.get(WATER) is None


async def test_series7_that_reported_first_is_still_asked_its_state(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    """A report before the first answer does not turn a series 7 into a series 1."""
    unit = cloud.add("versati_series7", answers_status=False, reports_on_request=True)
    await setup_integration()
    await cloud.push(unit)
    await settle(hass, cloud)
    unit.answers_status = True
    unit.forget()

    await poll()
    assert kinds(unit) == ["status"]
    await poll()
    assert kinds(unit) == ["status", "status"]


@pytest.mark.parametrize(
    "fixture", ["versati_series7", "split_ac", "hwhp", "pool", "commercial_ac", "vrf_head"]
)
async def test_units_that_answer_are_never_asked_to_report(
    hass: HomeAssistant, cloud, setup_integration, poll, fixture: str
) -> None:
    unit = cloud.add(fixture)
    await setup_integration()
    await poll()
    await cloud.push(unit)
    await poll()
    assert unit.status_requests
    assert unit.report_requests == []


@pytest.mark.parametrize("fixture", ["split_ac", "hwhp", "pool", "commercial_ac"])
async def test_silent_air_conditioner_is_never_asked_to_report(
    hass: HomeAssistant, cloud, setup_integration, poll, fixture: str
) -> None:
    unit = cloud.add(fixture, answers_status=False)
    await setup_integration()
    await poll()
    await cloud.push(unit)
    await poll()
    assert unit.status_requests
    assert unit.report_requests == []
