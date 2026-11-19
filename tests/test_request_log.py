"""The debug aid for units that only report while Gree+ is open (#75).

With debug logging on, the requests other clients send to such a unit are
written to the log. Nothing is sent to the unit and nothing changes for any
other unit, or without debug logging.
"""

from __future__ import annotations

import logging

import pytest

from homeassistant.core import HomeAssistant

LOGGER = "custom_components.gree_cloud.coordinator"
TOPIC = "request/aa0000000005"
APP_REQUEST = {"t": "status", "cols": ["hid"]}
WATER = "climate.heat_pump_hydraulic_heating"


def requests_heard(cloud) -> set[str]:
    return {topic for topic in cloud.session.subscriptions if topic.startswith("request/")}


async def test_requests_to_a_unit_living_on_pushes_are_logged(
    hass: HomeAssistant, cloud, setup_integration, poll, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    # Silent during setup: nothing shows yet what it is.
    unit = cloud.add("versati_series1", reports_on_request=False)
    await setup_integration()
    assert requests_heard(cloud) == set()

    # The first report shows what the unit is; from then on its requests are heard.
    await cloud.push(unit)
    assert requests_heard(cloud) == {TOPIC}
    unit.reports_on_request = True
    unit.forget()

    await cloud.app_request(unit, APP_REQUEST)
    assert "Heat Pump: request seen (cid app, to aa0000000005): {'t': 'status', 'cols': ['hid']}" in caplog.text

    # Asked for once, however many reports and polls follow.
    await cloud.push(unit)
    await poll()
    assert caplog.text.count(f"listening on {TOPIC}") == 1
    # Listening sends the unit nothing: the poll is the one request it got.
    assert unit.commands == []
    assert [pack["t"] for pack in unit.received] == ["freqCount"]
    assert hass.states.get(WATER).state != "unavailable"


async def test_listening_starts_with_the_poll_after_debug_logging_is_switched_on(
    hass: HomeAssistant, cloud, setup_integration, poll, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    unit = cloud.add("versati_series1")
    await setup_integration()
    await cloud.push(unit)
    await poll()
    assert requests_heard(cloud) == set()
    await cloud.app_request(unit, APP_REQUEST)
    assert "request seen" not in caplog.text

    caplog.set_level(logging.DEBUG, logger=LOGGER)
    await poll()
    assert requests_heard(cloud) == {TOPIC}
    await cloud.app_request(unit, APP_REQUEST)
    assert "request seen" in caplog.text


@pytest.mark.parametrize("fixture", ["versati_series7", "split_ac"])
async def test_no_listening_to_a_unit_that_answers(
    hass: HomeAssistant, cloud, setup_integration, poll, caplog: pytest.LogCaptureFixture, fixture: str
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    unit = cloud.add(fixture)
    await setup_integration()
    await cloud.push(unit)
    await poll()
    await poll()
    assert requests_heard(cloud) == set()
    assert "request seen" not in caplog.text


async def test_a_broker_that_refuses_is_not_asked_for_ever(
    hass: HomeAssistant, cloud, setup_integration, poll, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    cloud.refused_topics.add("request")
    unit = cloud.add("versati_series1")
    await setup_integration()
    await cloud.push(unit)
    assert cloud.refused == [TOPIC]
    assert f"cannot listen on {TOPIC}" in caplog.text

    for _ in range(3):
        await poll()
        await cloud.push(unit)
    assert cloud.refused == [TOPIC]
    assert hass.states.get(WATER).state != "unavailable"


async def test_listening_again_after_a_reconnect(
    hass: HomeAssistant, cloud, setup_integration, poll, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    unit = cloud.add("versati_series1")
    await setup_integration()
    await cloud.push(unit)
    first = cloud.session

    cloud.drop_connection()
    await poll()
    await poll()
    assert cloud.session is not first
    assert requests_heard(cloud) == {TOPIC}
    await cloud.app_request(unit, APP_REQUEST)
    assert "request seen" in caplog.text
