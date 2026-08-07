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
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DISPATCH_DEVICE_DISCOVERED, ENERGY_SCALE, PROP_ENERGY_TOTAL
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
