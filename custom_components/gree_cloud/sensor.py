"""Support for Gree Cloud sensor entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from greeclimate_davo22.device import Device

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
    PROP_ENERGY_TOTAL,
    PROP_HUMIDITY,
)
from .coordinator import (
    CloudDeviceDataUpdateCoordinator,
    GreeCloudConfigEntry,
    is_hwhp_device,
)
from .entity import GreeCloudEntity
from .heatpump import (
    COOLING_SETPOINTS,
    SETPOINTS,
    TEMPERATURE_PAIRS,
    cooling_confirmed,
    setpoint,
    temperature,
)


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
        key="Compressor Frequency",
        translation_key="compressor_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_compressor_frequency,
        exists_fn=_has_compressor_frequency,
    ),
)


def _heatpump_sensor_description(
    key: str, translation_key: str, *, measurement: bool = False
) -> GreeCloudSensorEntityDescription:
    """Describe a air-to-water value using the common cloud sensor implementation."""

    def value_fn(device: Device) -> float | None:
        decoder = temperature if measurement else setpoint
        return decoder(device.raw_properties, key)

    def exists_fn(device: Device) -> bool:
        if key in COOLING_SETPOINTS and not cooling_confirmed(device.raw_properties):
            return False
        return value_fn(device) is not None

    return GreeCloudSensorEntityDescription(
        key=f"versati_{key}",
        translation_key=translation_key,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT if measurement else None,
        suggested_display_precision=1 if measurement else None,
        value_fn=value_fn,
        exists_fn=exists_fn,
    )


HEATPUMP_SENSORS: tuple[GreeCloudSensorEntityDescription, ...] = (
    *(
        _heatpump_sensor_description(key, translation)
        for key, translation in (SETPOINTS | COOLING_SETPOINTS).items()
    ),
    *(
        _heatpump_sensor_description(key, key, measurement=True)
        for key in TEMPERATURE_PAIRS
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Gree Cloud sensors from a config entry."""

    heatpump_registered: set[str] = set()

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Register the device."""
        # Hot water heat pumps report consumption under a different key.
        if coordinator.device_kind == "heatpump":

            @callback
            def add_new_sensors():
                entities = []
                for description in HEATPUMP_SENSORS:
                    if not description.exists_fn(coordinator.device):
                        continue
                    entity = GreeCloudSensor(coordinator, description)
                    if entity.unique_id not in heatpump_registered:
                        heatpump_registered.add(entity.unique_id)
                        entities.append(entity)
                if entities:
                    async_add_entities(entities)

            add_new_sensors()
            entry.async_on_unload(coordinator.async_add_listener(add_new_sensors))
            return
        if coordinator.device_kind != "ac" or is_hwhp_device(coordinator):
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
