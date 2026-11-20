"""The air-to-water protocol rules in ``heatpump.py``; no Home Assistant needed."""

from __future__ import annotations

import pytest

from custom_components.gree_cloud.heatpump import (
    FUNCTION_SWITCHES,
    HEATPUMP_COLUMNS,
    RUN_STATE_COLUMNS,
    ZONE_POWER_COLUMNS,
    WritePolicy,
    classify,
    decode_values,
    numeric,
    power_keys,
    prepare_command,
    setpoint,
    status_columns,
    temperature,
    user_control_policy,
    verify_command_reply,
    weather_dependent_target,
)

from .fake_cloud import load_fixture

SERIES_1 = load_fixture("versati_series1")["state"]
SERIES_7 = load_fixture("versati_series7")["state"]


def pair(high: object, low: object) -> dict[str, object]:
    return {"AllOutWatTemHi": high, "AllOutWatTemLo": low}


@pytest.mark.parametrize(
    ("high", "low", "expected"),
    [
        (136, 2, 36.2),
        (122, 8, 22.8),
        (100, 5, 0.5),
        (95, 5, -4.5),  # decimal arithmetic below zero
        (60, 0, -40.0),
        (100, 0, None),  # zero or no sensor: cannot tell
        (70, 0, None),  # -30.0 is what a missing sensor reads (#75)
        (0, 0, None),
        (255, 0, None),
        (136, 10, None),  # tenths are one digit
        (136.5, 2, None),
        ("136", 2, None),
        (True, 2, None),
        (None, 2, None),
        (136, None, None),
        (30, 0, None),  # -70 C is outside anything a heat pump measures
    ],
)
def test_temperature_pair(high: object, low: object, expected: float | None) -> None:
    assert temperature(pair(high, low), "water_outlet_temperature") == expected


def test_temperature_needs_both_halves() -> None:
    assert temperature({"AllOutWatTemHi": 136}, "water_outlet_temperature") is None
    assert temperature({"AllOutWatTemLo": 2}, "water_outlet_temperature") is None


def test_recorded_temperatures() -> None:
    assert temperature(SERIES_1, "water_inlet_temperature") == 22.8
    assert temperature(SERIES_1, "dhw_temperature") == 54.8
    assert temperature(SERIES_1, "room_temperature") == 21.5
    # Sensor not fitted on that unit: no reading, not -30.0.
    assert temperature(SERIES_1, "heat_pump_outlet_temperature") is None
    assert temperature(SERIES_7, "heat_pump_outlet_temperature") == 37.0
    assert temperature(SERIES_7, "room_temperature") is None


@pytest.mark.parametrize("value", [None, True, False, "45", float("nan"), float("inf"), [45]])
def test_numeric_rejects(value: object) -> None:
    assert numeric(value) is None


def test_numeric_accepts_numbers() -> None:
    assert numeric(45) == 45.0
    assert numeric(4.5) == 4.5
    assert numeric(0) == 0.0


@pytest.mark.parametrize(("value", "expected"), [(45, 45.0), (0, None), (-5, None), (100, 100.0), (101, None), ("45", None)])
def test_setpoint_rejects_placeholders(value: object, expected: float | None) -> None:
    assert setpoint({"HeWatOutTemSet": value}, "HeWatOutTemSet") == expected


def test_classify() -> None:
    assert classify(SERIES_1, mid="9300") == "heatpump"
    assert classify(SERIES_7, mid="9300") == "heatpump"
    assert classify(SERIES_7, mid=9300) == "heatpump"
    # Hydraulic columns on a model that is not registered mean nothing.
    assert classify(SERIES_7, mid="10001") == "ac"
    assert classify(SERIES_7, mid=None) == "ac"
    # Two usable setpoints are the least that makes a heat pump.
    assert classify({"HeWatOutTemSet": 45, "WatBoxTemSet": 50}, mid="9300") == "heatpump"
    assert classify({"HeWatOutTemSet": 45, "WatBoxTemSet": 0}, mid="9300") == "unknown"
    assert classify({"Pow": 1}, mid="9300") == "unknown"
    assert classify({}, mid="9300") == "unknown"


def test_status_columns_by_series() -> None:
    assert status_columns(SERIES_7) == HEATPUMP_COLUMNS
    assert status_columns({}) == HEATPUMP_COLUMNS
    assert status_columns(SERIES_1) == (*HEATPUMP_COLUMNS, *ZONE_POWER_COLUMNS, *RUN_STATE_COLUMNS)
    assert len(HEATPUMP_COLUMNS) == 19
    assert len(status_columns(SERIES_1)) == 26


def test_power_keys() -> None:
    assert power_keys(SERIES_7) == ["Pow"]
    # Series 1: the zone flags go along while they mirror Pow.
    assert power_keys(SERIES_1) == ["Pow", "ZonePow1", "ZonePow2"]
    assert power_keys({**SERIES_1, "Pow": 1, "ZonePow1": 1, "ZonePow2": 1}) == ["Pow", "ZonePow1", "ZonePow2"]
    # A zone switched separately is left alone.
    assert power_keys({**SERIES_1, "Pow": 1, "ZonePow1": 1, "ZonePow2": 0}) == ["Pow"]
    assert power_keys({k: v for k, v in SERIES_1.items() if k != "ZonePow2"}) == ["Pow"]


def test_policy_for_recorded_units() -> None:
    policy = user_control_policy(SERIES_7, mid="9300")
    assert policy.approved == {"Pow", "Mod", "HeWatOutTemSet", "HeHomTemSet", "WatBoxTemSet"}
    assert policy.limits == {
        "HeWatOutTemSet": (20, 60),
        "HeHomTemSet": (18, 30),
        "WatBoxTemSet": (40, 60),
    }
    assert policy.modes == {1, 2, 4}
    # Series 1 has the function buttons of Gree+ on top (#75).
    series1 = user_control_policy(SERIES_1, mid="9300")
    assert series1.approved == policy.approved | {"Quiet", "SvSt", "SwDisFct", "FastHtWter"}
    assert series1.modes == policy.modes
    # ... and hot water up to 80, as Gree+ offers on it.
    assert series1.limits == {**policy.limits, "WatBoxTemSet": (40, 80)}


@pytest.mark.parametrize("key", FUNCTION_SWITCHES)
def test_function_switch_is_offered_only_for_a_reported_flag(key: str) -> None:
    for props in (
        {**SERIES_1, key: 2},
        {**SERIES_1, key: None},
        {k: v for k, v in SERIES_1.items() if k != key},
        # Reported, but by a series it was not seen on.
        {**SERIES_1, "VersatiSeries": 7},
    ):
        policy = user_control_policy(props, mid="9300")
        assert key not in policy.approved
        assert "Pow" in policy.approved
        with pytest.raises(ValueError):
            prepare_command(props, policy, key, 1)


@pytest.mark.parametrize("key", FUNCTION_SWITCHES)
def test_prepare_function_switch_command(key: str) -> None:
    policy = user_control_policy(SERIES_1, mid="9300")
    assert prepare_command(SERIES_1, policy, key, 1) == {"t": "cmd", "opt": [key], "p": [1]}
    assert prepare_command(SERIES_1, policy, key, 0) == {"t": "cmd", "opt": [key], "p": [0]}
    for value in (2, -1, 0.5, None, "1"):
        with pytest.raises(ValueError):
            prepare_command(SERIES_1, policy, key, value)


def test_weather_dependent_target() -> None:
    assert weather_dependent_target(SERIES_1) == 40
    # Switched off, the unit repeats the manual target under this name.
    assert weather_dependent_target({**SERIES_1, "SvSt": 0, "WDTemSet": 21}) is None
    assert weather_dependent_target({"WDTemSet": 38}) == 38
    assert weather_dependent_target({"SvSt": 1, "WDTemSet": 0}) is None
    assert weather_dependent_target(SERIES_7) is None


def test_policy_with_cooling_evidence() -> None:
    policy = user_control_policy(SERIES_7, mid="9300", cooling=True)
    assert policy.limits["CoWatOutTemSet"] == (5, 25)
    assert policy.limits["CoHomTemSet"] == (18, 30)
    assert policy.modes == {1, 2, 3, 4, 5}
    assert {"CoWatOutTemSet", "CoHomTemSet"} <= policy.approved


@pytest.mark.parametrize(
    "props",
    [
        {**SERIES_7, "VersatiSeries": 3},  # a series nobody checked
        {**SERIES_7, "TemUn": 1},  # Fahrenheit: limits would be wrong
        {k: v for k, v in SERIES_7.items() if k != "VersatiSeries"},
    ],
)
def test_policy_is_empty_for_unverified_units(props: dict) -> None:
    assert user_control_policy(props, mid="9300") == WritePolicy()


def test_policy_is_empty_for_other_models() -> None:
    assert user_control_policy(SERIES_7, mid="10001") == WritePolicy()
    assert user_control_policy(SERIES_7, mid=None) == WritePolicy()


def test_policy_without_hot_water_tank() -> None:
    policy = user_control_policy({**SERIES_7, "WatBoxTemSet": 0}, mid="9300")
    assert "WatBoxTemSet" not in policy.approved
    assert policy.modes == {1}


def test_prepare_setpoint_command() -> None:
    policy = user_control_policy(SERIES_7, mid="9300")
    assert prepare_command(SERIES_7, policy, "HeWatOutTemSet", 45) == {"t": "cmd", "opt": ["HeWatOutTemSet"], "p": [45]}
    assert prepare_command(SERIES_7, policy, "WatBoxTemSet", 55.0) == {"t": "cmd", "opt": ["WatBoxTemSet"], "p": [55]}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("HeWatOutTemSet", 19),  # below the limit
        ("HeWatOutTemSet", 61),  # above the limit
        ("HeWatOutTemSet", 45.5),  # whole degrees only
        ("HeWatOutTemSet", "45"),
        ("WatBoxTemSet", 39),
        ("HeHomTemSet", 31),
        ("CoWatOutTemSet", 18),  # cooling was never observed
        ("FastHtWter", 1),  # not an approved control
        ("Quiet", 1),
        ("Mod", 5),  # cooling mode without cooling evidence
        ("Mod", 3),
        ("Mod", 6),
        ("Mod", 1.5),
        ("Pow", 2),
        ("Pow", None),
    ],
)
def test_prepare_command_refuses(key: str, value: object) -> None:
    policy = user_control_policy(SERIES_7, mid="9300")
    with pytest.raises(ValueError):
        prepare_command(SERIES_7, policy, key, value)


def test_prepare_cooling_setpoint_with_evidence() -> None:
    policy = user_control_policy(SERIES_7, mid="9300", cooling=True)
    assert prepare_command(SERIES_7, policy, "CoWatOutTemSet", 12) == {"t": "cmd", "opt": ["CoWatOutTemSet"], "p": [12]}
    assert prepare_command(SERIES_7, policy, "Mod", 5) == {"t": "cmd", "opt": ["Mod"], "p": [5]}
    with pytest.raises(ValueError):
        prepare_command(SERIES_7, policy, "CoWatOutTemSet", 4)


def test_prepare_power_and_mode_commands() -> None:
    policy = user_control_policy(SERIES_7, mid="9300")
    assert prepare_command(SERIES_7, policy, "Pow", 0) == {"t": "cmd", "opt": ["Pow"], "p": [0]}
    assert prepare_command(SERIES_7, policy, "Mod", 2) == {"t": "cmd", "opt": ["Mod"], "p": [2]}
    policy = user_control_policy(SERIES_1, mid="9300")
    assert prepare_command(SERIES_1, policy, "Pow", 1) == {
        "t": "cmd",
        "opt": ["Pow", "ZonePow1", "ZonePow2"],
        "p": [1, 1, 1],
    }


def test_nothing_can_be_written_without_a_policy() -> None:
    with pytest.raises(ValueError):
        prepare_command(SERIES_7, WritePolicy(), "Pow", 1)


def test_decode_values() -> None:
    assert decode_values({"t": "dat", "cols": ["Pow", "Mod"], "dat": [1, 4]}) == {"Pow": 1, "Mod": 4}
    assert decode_values({"t": "res", "r": 200, "opt": ["Pow"], "p": [1]}) == {"Pow": 1}
    assert decode_values({"t": "res", "r": 200, "opt": ["Pow"], "val": [1]}) == {"Pow": 1}
    assert decode_values({"t": "res", "r": 200}) == {}
    assert decode_values({"dat": {"Pow": 1}}) == {"Pow": 1}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "ok",
        {"t": "res", "r": 500},
        {"cols": ["Pow", "Mod"], "dat": [1]},  # never truncate silently
        {"cols": ["Pow", "Pow"], "dat": [1, 0]},
        {"cols": ["Pow", 3], "dat": [1, 0]},
    ],
)
def test_decode_values_rejects(payload: object) -> None:
    with pytest.raises(ValueError):
        decode_values(payload)


def test_verify_command_reply() -> None:
    verify_command_reply({"t": "res", "r": 200, "opt": ["Pow"], "p": [1]}, "Pow", 1)
    verify_command_reply({"t": "res", "r": 200}, "Pow", 1)
    # A state the unit sent by itself that shows the new value counts too.
    verify_command_reply({"t": "dat", "cols": ["Pow"], "dat": [1]}, "Pow", 1)


@pytest.mark.parametrize(
    "reply",
    [
        None,
        {"t": "res", "r": 200, "opt": ["Pow"], "p": [0]},  # echoes another value
        {"t": "res"},  # neither an echo nor r = 200
        {"t": "res", "r": 500},
        {"t": "dat", "cols": ["Mod"], "dat": [1]},
    ],
)
def test_verify_command_reply_rejects(reply: object) -> None:
    with pytest.raises(ValueError):
        verify_command_reply(reply, "Pow", 1)
