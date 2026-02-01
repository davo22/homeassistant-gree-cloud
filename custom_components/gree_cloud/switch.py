"""Support for Gree Cloud switch entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from greeclimate.device import Device

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DISPATCH_DEVICE_DISCOVERED
from .coordinator import CloudDeviceDataUpdateCoordinator, GreeCloudConfigEntry
from .entity import GreeCloudEntity


@dataclass(kw_only=True, frozen=True)
class GreeCloudSwitchEntityDescription(SwitchEntityDescription):
    """Describes a Gree Cloud switch entity."""

    get_value_fn: Callable[[Device], bool]
    set_value_fn: Callable[[Device, bool], None]


def _set_light(device: Device, value: bool) -> None:
    """Typed helper to set device light property."""
    device.light = value


def _set_quiet(device: Device, value: bool) -> None:
    """Typed helper to set device quiet property."""
    device.quiet = value


def _set_fresh_air(device: Device, value: bool) -> None:
    """Typed helper to set device fresh_air property."""
    device.fresh_air = value


def _set_xfan(device: Device, value: bool) -> None:
    """Typed helper to set device xfan property."""
    device.xfan = value


def _set_anion(device: Device, value: bool) -> None:
    """Typed helper to set device anion property."""
    device.anion = value


GREE_CLOUD_SWITCHES: tuple[GreeCloudSwitchEntityDescription, ...] = (
    GreeCloudSwitchEntityDescription(
        key="Panel Light",
        translation_key="light",
        get_value_fn=lambda d: d.light,
        set_value_fn=_set_light,
    ),
    GreeCloudSwitchEntityDescription(
        key="Quiet",
        translation_key="quiet",
        get_value_fn=lambda d: d.quiet,
        set_value_fn=_set_quiet,
    ),
    GreeCloudSwitchEntityDescription(
        key="Fresh Air",
        translation_key="fresh_air",
        get_value_fn=lambda d: d.fresh_air,
        set_value_fn=_set_fresh_air,
    ),
    GreeCloudSwitchEntityDescription(
        key="XFan",
        translation_key="xfan",
        get_value_fn=lambda d: d.xfan,
        set_value_fn=_set_xfan,
    ),
    GreeCloudSwitchEntityDescription(
        key="Health mode",
        translation_key="health_mode",
        get_value_fn=lambda d: d.anion,
        set_value_fn=_set_anion,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Gree Cloud HVAC device from a config entry."""

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Register the device."""
        async_add_entities(
            GreeCloudSwitch(coordinator=coordinator, description=description)
            for description in GREE_CLOUD_SWITCHES
        )

    for coordinator in entry.runtime_data.coordinators:
        init_device(coordinator)

    entry.async_on_unload(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeCloudSwitch(GreeCloudEntity, SwitchEntity):
    """Generic Gree Cloud switch entity."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    entity_description: GreeCloudSwitchEntityDescription

    def __init__(
        self,
        coordinator: CloudDeviceDataUpdateCoordinator,
        description: GreeCloudSwitchEntityDescription,
    ) -> None:
        """Initialize the Gree Cloud device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.device_info.mac}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return if the state is turned on."""
        return self.entity_description.get_value_fn(self.coordinator.device)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self.entity_description.set_value_fn(self.coordinator.device, True)
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self.entity_description.set_value_fn(self.coordinator.device, False)
        await self.coordinator.push_state_update()
        self.async_write_ha_state()
