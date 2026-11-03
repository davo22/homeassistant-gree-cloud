"""Shared heat-pump protocol and supported model profiles; no network imports.

Mode values and setpoint names are documented by sarunasr/ha-gree-versati3.
Presence of an unsupported column (often returned as zero) is not a capability.
Hi/Lo encoding: tomikaa87/gree-remote issue 59, corroborated by live mid 9300
reads. A 100/0 pair is ambiguous (zero or missing sensor), not proof of 0 C.

Entity IDs and translation keys retain their historical ``versati_`` prefix
for registry compatibility; Python names describe the shared device family.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from typing import Any

SETPOINTS = {
    "HeWatOutTemSet": "heating_water_target",
    "HeHomTemSet": "heating_room_target",
    "WatBoxTemSet": "dhw_target",
}
COOLING_SETPOINTS = {
    "CoWatOutTemSet": "cooling_water_target",
    "CoHomTemSet": "cooling_room_target",
}
MODE_NAMES = {
    1: "heat",
    2: "hot_water",
    3: "cool_hot_water",
    4: "heat_hot_water",
    5: "cool",
}
HEATPUMP_COLUMNS = (
    "Pow",
    "Mod",
    *SETPOINTS,
    *COOLING_SETPOINTS,
    "VersatiSeries",
    "TemUn",
    "AllInWatTemHi",
    "AllInWatTemLo",
    "AllOutWatTemHi",
    "AllOutWatTemLo",
    "HepOutWatTemHi",
    "HepOutWatTemLo",
    "WatBoxTemHi",
    "WatBoxTemLo",
    "RmoHomTemHi",
    "RmoHomTemLo",
)


def numeric(value: Any) -> float | None:
    """Only accept finite protocol numbers, not nulls, booleans or strings."""
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return float(value) if math.isfinite(value) else None


def setpoint(props: Mapping[str, Any], key: str) -> float | None:
    """Reject zero placeholders; never apply an AC temperature offset."""
    value = numeric(props.get(key))
    # This is a decoding sanity bound, NOT an authorised write range.
    return value if value is not None and 0 < value <= 100 else None


@dataclass(frozen=True)
class HeatPumpProfile:
    """Validated model settings for the shared hydraulic protocol.

    Add a model only after checking its columns, mode values and temperature
    encoding. A matching model ID alone is not permission to write controls.
    """

    control_requirements: Mapping[str, int]
    heating_limits: Mapping[str, tuple[float, float]]
    cooling_limits: Mapping[str, tuple[float, float]]


HEATPUMP_MODELS: dict[str, HeatPumpProfile] = {
    "9300": HeatPumpProfile(
        control_requirements={"VersatiSeries": 7, "TemUn": 0},
        heating_limits={
            "HeWatOutTemSet": (20, 60),
            "HeHomTemSet": (18, 30),
            "WatBoxTemSet": (40, 60),
        },
        cooling_limits={"CoWatOutTemSet": (5, 25), "CoHomTemSet": (18, 30)},
    ),
}


def model_profile(mid: Any) -> HeatPumpProfile | None:
    """Return the explicitly supported profile, never infer one from a name."""
    return HEATPUMP_MODELS.get(str(mid))


def classify(props: Mapping[str, Any], *, mid: Any = None) -> str:
    """Recognize hydraulic data only for models in the supported registry."""
    if model_profile(mid) is None:
        return "ac"
    hydraulic = sum(setpoint(props, key) is not None for key in SETPOINTS)
    return "heatpump" if hydraulic >= 2 else "unknown"


def cooling_confirmed(props: Mapping[str, Any]) -> bool:
    """Only an observed cooling mode is evidence of cooling capability for now."""
    return props.get("Mod") in (3, 5)


def prepare_setpoint(
    props: Mapping[str, Any],
    key: str,
    value: Any,
    *,
    limits: tuple[float, float] | None = None,
) -> dict:
    """Offline command preparation only. No guessed device-specific limits."""
    allowed = dict(SETPOINTS)
    if cooling_confirmed(props):
        allowed.update(COOLING_SETPOINTS)
    number = numeric(value)
    if key not in allowed or setpoint(props, key) is None:
        raise ValueError("Unsupported setpoint")
    if limits is None:
        raise ValueError("Device write limits have not been validated")
    low, high = limits
    if number is None or not low <= number <= high or not number.is_integer():
        raise ValueError("Invalid setpoint")
    return {"t": "cmd", "opt": [key], "p": [int(number)]}


TEMPERATURE_PAIRS = {
    "water_inlet_temperature": ("AllInWatTemHi", "AllInWatTemLo"),
    "water_outlet_temperature": ("AllOutWatTemHi", "AllOutWatTemLo"),
    "heat_pump_outlet_temperature": ("HepOutWatTemHi", "HepOutWatTemLo"),
    "dhw_temperature": ("WatBoxTemHi", "WatBoxTemLo"),
    "room_temperature": ("RmoHomTemHi", "RmoHomTemLo"),
}


def temperature(props: Mapping[str, Any], key: str) -> float | None:
    """Decode a complete pair from one response; reject placeholders/sentinels.

    Even a physically possible zero is ambiguous without sensor-validity data.
    Decimal arithmetic also works for negatives: 95/5 means -4.5 C.
    """
    high_key, low_key = TEMPERATURE_PAIRS[key]
    high, low = numeric(props.get(high_key)), numeric(props.get(low_key))
    if high is None or low is None or not high.is_integer() or not low.is_integer():
        return None
    if not 0 < high < 255 or not 0 <= low <= 9 or (high == 100 and low == 0):
        return None
    result = round(high - 100 + low / 10, 1)
    return result if -50 <= result <= 120 else None


@dataclass(frozen=True)
class WritePolicy:
    """Allowlisted user controls with limits; never an arbitrary protocol writer."""

    approved: frozenset[str] = frozenset()
    limits: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    modes: frozenset[int] = frozenset()


def user_control_policy(
    props: Mapping[str, Any], *, mid: Any, cooling: bool = False
) -> WritePolicy:
    """Enable controls only when the registered model's requirements match.

    Heating water write/ACK/readback was verified on hardware. Other commands
    use the community Versati mapping, not a claim of individual hardware tests.
    Ranges are conservative: water 20..60, DHW 40..60, room 18..30 C.
    Gree Versati IV owner manual section 3.3 documents room 18..30 and DHW
    40..80; we deliberately do not extend the community water maximum to 65/80.
    """
    profile = model_profile(mid)
    if profile is None or any(
        props.get(key) != value for key, value in profile.control_requirements.items()
    ):
        return WritePolicy()
    limits = dict(profile.heating_limits)
    if cooling:
        limits.update(profile.cooling_limits)
    limits = {
        key: bounds
        for key, bounds in limits.items()
        if setpoint(props, key) is not None
    }
    approved = set(limits)
    if numeric(props.get("Pow")) in (0, 1):
        approved.add("Pow")
    modes = {1, 4} if "HeWatOutTemSet" in limits else set()
    if "WatBoxTemSet" in limits:
        modes.add(2)
    else:
        modes.discard(4)
    if cooling and "CoWatOutTemSet" in limits:
        modes.add(5)
        if "WatBoxTemSet" in limits:
            modes.add(3)
    if modes and numeric(props.get("Mod")) in MODE_NAMES:
        approved.add("Mod")
    return WritePolicy(frozenset(approved), limits, frozenset(modes))


def prepare_command(
    props: Mapping[str, Any], policy: WritePolicy, key: str, value: Any
) -> dict:
    """Validate one command; no safety/maintenance parameter can be sent."""
    if key not in policy.approved:
        raise ValueError(f"Write protocol not validated for {key}")
    if key in SETPOINTS or key in COOLING_SETPOINTS:
        limits = policy.limits.get(key)
        if (
            limits is None
            or numeric(limits[0]) is None
            or numeric(limits[1]) is None
            or limits[0] > limits[1]
        ):
            raise ValueError("Device setpoint limits have not been validated")
        # Cooling approval is explicit evidence, unlike a returned unused column.
        state = dict(props)
        if key in COOLING_SETPOINTS and policy.modes.intersection((3, 5)):
            state["Mod"] = 5
        return prepare_setpoint(state, key, value, limits=limits)
    number = numeric(value)
    if number is None or not number.is_integer():
        raise ValueError("Command requires an integer")
    if key == "Pow" and props.get(key) in (0, 1) and number in (0, 1):
        return {"t": "cmd", "opt": [key], "p": [int(number)]}
    if key == "Mod" and number in policy.modes and number in MODE_NAMES:
        return {"t": "cmd", "opt": [key], "p": [int(number)]}
    # FastHtWter is deliberately excluded until its semantics is validated.
    raise ValueError("Unsupported or unsafe command")


def decode_values(payload: Any) -> dict[str, Any]:
    """Strict decode of status/command data, never silently truncate pairs."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid cloud response")
    if payload.get("r") not in (None, 0, 200):
        raise ValueError("Cloud rejected the request")
    for keys_name, values_name in (("cols", "dat"), ("opt", "p"), ("opt", "val")):
        keys, values = payload.get(keys_name), payload.get(values_name)
        if isinstance(keys, list) and isinstance(values, list):
            if (
                not all(isinstance(k, str) for k in keys)
                or len(keys) != len(values)
                or len(set(keys)) != len(keys)
            ):
                raise ValueError("Malformed cloud data columns")
            return dict(zip(keys, values, strict=True))
    if isinstance(payload.get("dat"), dict):
        return payload["dat"]
    return {}


def verify_command_reply(reply: Any, key: str, value: int) -> None:
    """Require explicit acknowledgement or an exact echo, never a bare None."""
    if not isinstance(reply, dict):
        raise ValueError("No command acknowledgement received")
    decoded = decode_values(reply)
    if key in decoded:
        if numeric(decoded[key]) != value:
            raise ValueError("Command acknowledgement value mismatch")
        return
    if reply.get("r") == 200:
        return
    raise ValueError("Unverified command acknowledgement")
