"""Home Assistant 2026.11 renamed the temperatures of climate and water heater
entities to native_ names; the old ones stop working in 2027.11 (#75).

Older versions read only the old names, newer ones warn in the log about every
class that provides an old name without the new one. So each class has both.
"""

from __future__ import annotations

import inspect

import pytest
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.water_heater import WaterHeaterEntity
from homeassistant.core import HomeAssistant

from custom_components.gree_cloud import climate, pool, water_heater

TEMPERATURES = (
    "temperature_unit",
    "current_temperature",
    "target_temperature",
    "target_temperature_high",
    "target_temperature_low",
)
ENTITY_CLASSES = [
    cls
    for module in (climate, pool, water_heater)
    for cls in vars(module).values()
    if inspect.isclass(cls)
    and cls.__module__ == module.__name__
    and issubclass(cls, (ClimateEntity, WaterHeaterEntity))
]


def test_every_temperature_entity_is_checked() -> None:
    assert {cls.__name__ for cls in ENTITY_CLASSES} >= {
        "GreeCloudClimateEntity",
        "GreeHeatPumpClimate",
        "GreeHeatPumpRoomClimate",
        "GreeCloudPoolClimateEntity",
        "GreeCloudWaterHeaterEntity",
        "GreeHeatPumpWaterHeater",
    }


@pytest.mark.parametrize("cls", ENTITY_CLASSES, ids=lambda cls: cls.__name__)
def test_temperatures_under_the_old_and_the_new_name(cls: type) -> None:
    """A class that has one of the two names has the other, with the same value."""
    members = vars(cls)
    for name in TEMPERATURES:
        assert (name in members) == (f"native_{name}" in members), name
        assert (f"_attr_{name}" in members) == (f"_attr_native_{name}" in members), name
        if name in members:
            assert members[name] is members[f"native_{name}"], name


async def test_a_unit_in_fahrenheit_under_both_names(
    hass: HomeAssistant, cloud, setup_integration, poll
) -> None:
    """The unit follows the device under whichever name Home Assistant reads."""
    unit = cloud.add("split_ac")
    await setup_integration()
    entity = hass.data["climate"].get_entity("climate.living_room")
    assert entity._attr_native_temperature_unit == entity._attr_temperature_unit == "°C"
    unit.state.update(TemUn=1, SetTem=27, TemRec=0)
    await poll()
    assert entity._attr_native_temperature_unit == entity._attr_temperature_unit == "°F"
    unit.state.update(TemUn=0, SetTem=23)
    await poll()
    assert entity._attr_native_temperature_unit == entity._attr_temperature_unit == "°C"
