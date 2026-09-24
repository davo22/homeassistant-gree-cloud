"""Support for Gree Cloud sensor entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from greeclimate.device import Device

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DISPATCH_DEVICE_DISCOVERED,
    ENERGY_SCALE,
    PROP_COMPRESSOR_FREQ,
    PROP_COMPRESSOR_TEMP,
    PROP_ENERGY_TOTAL,
    PROP_HUMIDITY,
    PROP_OUTDOOR_TEMP,
)
from .coordinator import (
    CloudDeviceDataUpdateCoordinator,
    GreeCloudConfigEntry,
    is_hwhp_device,
)
from .entity import GreeCloudEntity


@dataclass(kw_only=True, frozen=True)
class GreeCloudSensorEntityDescription(SensorEntityDescription):
    """Describes a Gree Cloud sensor entity."""

    value_fn: Callable[[Device], float | None]
    exists_fn: Callable[[Device], bool]


def _energy_total(device: Device) -> float | None:
    """Return cumulative energy in kWh, or None if the device did not report it."""
    raw = device.raw_properties.get(PROP_ENERGY_TOTAL)
    if raw is None:
        return None
    return round(raw * ENERGY_SCALE, 1)


def _has_energy_total(device: Device) -> bool:
    """Return True if the device reports the energy counter.

    Devices silently omit properties they do not support, so a missing key -
    rather than a zero value - is what marks the counter as unavailable. A
    freshly installed unit legitimately reports 0.
    """
    return device.raw_properties.get(PROP_ENERGY_TOTAL) is not None


def _compressor_frequency(device: Device) -> float | None:
    """Return compressor frequency in Hz."""
    return device.raw_properties.get(PROP_COMPRESSOR_FREQ)


def _has_compressor_frequency(device: Device) -> bool:
    """Return True if the device reports compressor frequency.

    Zero is a valid reading - it means the compressor is idle - so presence of
    the key is the only reliable test.
    """
    return device.raw_properties.get(PROP_COMPRESSOR_FREQ) is not None


def _fahrenheit_to_celsius(value: float) -> float:
    """Convert a raw device temperature key to Celsius.

    OutEnvTem / CompressorTem always report Fahrenheit regardless of the
    device's TemUn setting - confirmed by testing on a physical Clivia
    V3.2.M switched between TemUn=0 (Celsius) and TemUn=1 (Fahrenheit);
    these raw keys did not change value across the switch. The fixed
    (°F - 32) * 5/9 conversion is therefore correct unconditionally and
    should not be made conditional on TemUn.
    """
    return round((value - 32) * 5 / 9, 1)


def _compressor_temperature(device: Device) -> float | None:
    """Return compressor temperature in degrees C."""
    raw = device.raw_properties.get(PROP_COMPRESSOR_TEMP)
    if raw is None:
        return None
    return _fahrenheit_to_celsius(raw)


def _has_compressor_temperature(device: Device) -> bool:
    """Return True if the device reports compressor temperature.

    Units without this sensor omit the key entirely rather than reporting 0,
    matching the convention used for other optional properties.
    """
    return device.raw_properties.get(PROP_COMPRESSOR_TEMP) is not None


def _outdoor_temperature(device: Device) -> float | None:
    """Return outdoor temperature in degrees C."""
    raw = device.raw_properties.get(PROP_OUTDOOR_TEMP)
    if raw is None:
        return None
    return _fahrenheit_to_celsius(raw)


def _has_outdoor_temperature(device: Device) -> bool:
    """Return True if the device reports outdoor temperature.

    Units without this sensor omit the key entirely rather than reporting 0,
    matching the convention used for other optional properties.
    """
    return device.raw_properties.get(PROP_OUTDOOR_TEMP) is not None


def _humidity(device: Device) -> float | None:
    """Return relative humidity in percent."""
    return device.raw_properties.get(PROP_HUMIDITY)


def _has_humidity(device: Device) -> bool:
    """Return True if the device has a usable humidity reading.

    Unlike the other properties, units without a humidity sensor report a flat
    0 rather than omitting the key, and 0 %RH is not a plausible indoor value.
    Readings outside 1-100 are therefore treated as "no sensor fitted".
    """
    raw = device.raw_properties.get(PROP_HUMIDITY)
    return isinstance(raw, (int, float)) and 0 < raw <= 100


GREE_CLOUD_SENSORS: tuple[GreeCloudSensorEntityDescription, ...] = (
    GreeCloudSensorEntityDescription(
        key="Energy",
        translation_key="energy_total",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=_energy_total,
        exists_fn=_has_energy_total,
    ),
    GreeCloudSensorEntityDescription(
        key="Humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_humidity,
        exists_fn=_has_humidity,
    ),
    GreeCloudSensorEntityDescription(
        key="Outdoor Temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=_outdoor_temperature,
        exists_fn=_has_outdoor_temperature,
    ),
    GreeCloudSensorEntityDescription(
        key="Compressor Frequency",
        translation_key="compressor_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_compressor_frequency,
        exists_fn=_has_compressor_frequency,
    ),
    GreeCloudSensorEntityDescription(
        key="Compressor Temperature",
        translation_key="compressor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_compressor_temperature,
        exists_fn=_has_compressor_temperature,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Gree Cloud sensors from a config entry."""

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Register the device."""
        # Hot water heat pumps report consumption under a different key.
        if is_hwhp_device(coordinator):
            return
        async_add_entities(
            GreeCloudSensor(coordinator=coordinator, description=description)
            for description in GREE_CLOUD_SENSORS
            if description.exists_fn(coordinator.device)
        )

    for coordinator in entry.runtime_data.coordinators:
        init_device(coordinator)

    entry.async_on_unload(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeCloudSensor(GreeCloudEntity, SensorEntity):
    """Generic Gree Cloud sensor entity."""

    entity_description: GreeCloudSensorEntityDescription

    def __init__(
        self,
        coordinator: CloudDeviceDataUpdateCoordinator,
        description: GreeCloudSensorEntityDescription,
    ) -> None:
        """Initialize the Gree Cloud sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.device_info.mac}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator.device)
