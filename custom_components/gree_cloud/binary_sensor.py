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
    HWHP_ERROR_PROPS,
    HWHP_PROP_BACKUP_HEATER,
    HWHP_PROP_DEFROST,
    HWHP_PROP_DISINFECT_ON,
    HWHP_PROP_DISINFECT_RUNNING,
    HWHP_PROP_FAN_HIGH,
    HWHP_PROP_FAN_LOW,
    HWHP_PROP_HOLIDAY,
    HWHP_PROP_PUMP,
    POOL_PROP_COMPRESSOR_STATUS,
    POOL_PROP_DEFROST,
    POOL_PROP_PUMP_STATUS,
)
from .coordinator import (
    CloudDeviceDataUpdateCoordinator,
    GreeCloudConfigEntry,
    is_hwhp_device,
    is_pool_device,
    is_heatpump_device,
)
from .entity import GreeCloudEntity


@dataclass(kw_only=True, frozen=True)
class GreeCloudBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Gree Cloud binary sensor backed by one raw property."""

    prop: str
    exists_fn: Callable[[Device], bool]
    # When set, computes the state instead of reading `prop` as a 0/1 flag.
    value_fn: Callable[[Device], bool | None] | None = None
    # When set, extra state attributes (e.g. raw error codes).
    attrs_fn: Callable[[Device], dict] | None = None


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


def _any_flag(*props: str) -> Callable[[Device], bool | None]:
    """On when any of the 0/1 flags is 1; None when none of them is reported."""

    def value(device: Device) -> bool | None:
        flags = [_flag(device, prop) for prop in props]
        known = [flag for flag in flags if flag is not None]
        return any(known) if known else None

    return value


def _any_error(device: Device) -> bool | None:
    """On when any HWHP error code is non-zero; None when none is reported."""
    codes = [device.raw_properties.get(prop) for prop in HWHP_ERROR_PROPS]
    known = [c for c in codes if isinstance(c, (int, float)) and not isinstance(c, bool)]
    return any(c != 0 for c in known) if known else None


def _error_codes(device: Device) -> dict:
    return {prop: device.raw_properties.get(prop) for prop in HWHP_ERROR_PROPS}


def _hwhp_flag(key: str, translation_key: str, prop: str, device_class=None) -> GreeCloudBinarySensorEntityDescription:
    return GreeCloudBinarySensorEntityDescription(
        key=key, translation_key=translation_key, device_class=device_class, prop=prop, exists_fn=_reports(prop)
    )


# Hot water heat pump state (#74).
HWHP_BINARY_SENSORS: tuple[GreeCloudBinarySensorEntityDescription, ...] = (
    _hwhp_flag("Backup heater", "backup_heater", HWHP_PROP_BACKUP_HEATER, BinarySensorDeviceClass.RUNNING),
    GreeCloudBinarySensorEntityDescription(
        key="Outdoor fan",
        translation_key="outdoor_fan",
        device_class=BinarySensorDeviceClass.RUNNING,
        prop=HWHP_PROP_FAN_HIGH,
        exists_fn=lambda d: _any_flag(HWHP_PROP_FAN_HIGH, HWHP_PROP_FAN_LOW)(d) is not None,
        value_fn=_any_flag(HWHP_PROP_FAN_HIGH, HWHP_PROP_FAN_LOW),
    ),
    _hwhp_flag("Defrosting", "defrosting", HWHP_PROP_DEFROST),
    _hwhp_flag("Pump", "pump_running", HWHP_PROP_PUMP, BinarySensorDeviceClass.RUNNING),
    GreeCloudBinarySensorEntityDescription(
        key="Error",
        translation_key="error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        prop=HWHP_ERROR_PROPS[0],
        exists_fn=lambda d: _any_error(d) is not None,
        value_fn=_any_error,
        attrs_fn=_error_codes,
    ),
    _hwhp_flag("Disinfection enabled", "disinfection_enabled", HWHP_PROP_DISINFECT_ON),
    _hwhp_flag("Disinfecting", "disinfecting", HWHP_PROP_DISINFECT_RUNNING, BinarySensorDeviceClass.RUNNING),
    _hwhp_flag("Holiday mode", "holiday_mode", HWHP_PROP_HOLIDAY),
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
        if is_heatpump_device(coordinator):
            if coordinator.device_kind == "heatpump" and (coordinator.data or {}).get("Pow") in (0, 1):
                async_add_entities([HeatPumpPower(coordinator)])
            return
        if is_pool_device(coordinator):
            descriptions = POOL_BINARY_SENSORS
        elif is_hwhp_device(coordinator):
            descriptions = HWHP_BINARY_SENSORS
        else:
            return
        async_add_entities(
            GreeCloudBinarySensor(coordinator=coordinator, description=description)
            for description in descriptions
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
        """Return the flag, or the computed state."""
        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(self.coordinator.device)
        return _flag(self.coordinator.device, self.entity_description.prop)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Raw values behind the state, where useful."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.device)

class HeatPumpPower(GreeCloudEntity, BinarySensorEntity):
    """Global PAC power, distinct from the hydraulic circuit's mode."""

    _attr_translation_key = "versati_power"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_info.mac}_versati_power"

    @property
    def is_on(self):
        value = (self.coordinator.data or {}).get("Pow")
        return bool(value) if value in (0, 1) else None
