"""Binary sensors for Gree Cloud devices (pool heat pump status flags)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from greeclimate_davo22.device import Device

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DISPATCH_DEVICE_DISCOVERED,
    POOL_PROP_COMPRESSOR_STATUS,
    POOL_PROP_DEFROST,
    POOL_PROP_PUMP_STATUS,
)
from .coordinator import (
    CloudDeviceDataUpdateCoordinator,
    GreeCloudConfigEntry,
    is_pool_device,
)
from .entity import GreeCloudEntity


@dataclass(kw_only=True, frozen=True)
class GreeCloudBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Gree Cloud binary sensor backed by one raw property."""

    prop: str
    exists_fn: Callable[[Device], bool]


def _flag(device: Device, prop: str) -> bool | None:
    """Return the 0/1 raw property as a bool, None when not reported."""
    raw = device.raw_properties.get(prop)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return raw == 1


def _reports(prop: str) -> Callable[[Device], bool]:
    return lambda device: _flag(device, prop) is not None


POOL_BINARY_SENSORS: tuple[GreeCloudBinarySensorEntityDescription, ...] = (
    GreeCloudBinarySensorEntityDescription(
        key="Pump",
        translation_key="pump_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        prop=POOL_PROP_PUMP_STATUS,
        exists_fn=_reports(POOL_PROP_PUMP_STATUS),
    ),
    GreeCloudBinarySensorEntityDescription(
        key="Compressor",
        translation_key="compressor_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        prop=POOL_PROP_COMPRESSOR_STATUS,
        exists_fn=_reports(POOL_PROP_COMPRESSOR_STATUS),
    ),
    GreeCloudBinarySensorEntityDescription(
        key="Defrosting",
        translation_key="defrosting",
        prop=POOL_PROP_DEFROST,
        exists_fn=_reports(POOL_PROP_DEFROST),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Gree Cloud binary sensors from a config entry."""

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Register the device (pool heat pumps only, #48)."""
        if not is_pool_device(coordinator):
            return
        async_add_entities(
            GreeCloudBinarySensor(coordinator=coordinator, description=description)
            for description in POOL_BINARY_SENSORS
            if description.exists_fn(coordinator.device)
        )

    for coordinator in entry.runtime_data.coordinators:
        init_device(coordinator)

    entry.async_on_unload(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeCloudBinarySensor(GreeCloudEntity, BinarySensorEntity):
    """Binary sensor backed by one 0/1 raw property."""

    entity_description: GreeCloudBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: CloudDeviceDataUpdateCoordinator,
        description: GreeCloudBinarySensorEntityDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.device_info.mac}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the flag."""
        return _flag(self.coordinator.device, self.entity_description.prop)
