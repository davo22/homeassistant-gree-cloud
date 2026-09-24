"""Support for Gree Cloud select entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from greeclimate.device import Device, Props

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DISPATCH_DEVICE_DISCOVERED,
    PANEL_LIGHT_AUTO,
    PANEL_LIGHT_OFF,
    PANEL_LIGHT_ON,
    PROP_LIGHT_SENSOR,
)
from .coordinator import CloudDeviceDataUpdateCoordinator, GreeCloudConfigEntry, is_hwhp_device
from .entity import GreeCloudEntity


@dataclass(kw_only=True, frozen=True)
class GreeCloudSelectEntityDescription(SelectEntityDescription):
    """Describes a Gree Cloud select entity."""

    get_value_fn: Callable[[Device], str | None]
    set_value_fn: Callable[[Device, str], None]
    exists_fn: Callable[[Device], bool] = lambda device: True


def _get_panel_light(device: Device) -> str | None:
    """Typed helper to read the panel light (Lig/LigSen) as a select option."""
    lig = device.get_property(Props.LIGHT)
    if lig == 0:
        return PANEL_LIGHT_OFF
    if lig == 1:
        lig_sen = device.raw_properties.get(PROP_LIGHT_SENSOR)
        return PANEL_LIGHT_ON if lig_sen == 1 else PANEL_LIGHT_AUTO
    return None


def _set_panel_light(device: Device, option: str) -> None:
    """Typed helper to set the panel light (Lig/LigSen).

    LigSen has no equivalent in greeclimate, so it's written directly
    through raw_properties, the same pattern used for HWHP properties. Lig
    does have a setter (device.light), used here for consistency with the
    rest of the codebase; both end up dirty and go out together in the same
    push_state_update() call.
    """
    device.light = option != PANEL_LIGHT_OFF
    device.raw_properties[PROP_LIGHT_SENSOR] = 1 if option == PANEL_LIGHT_ON else 0
    if PROP_LIGHT_SENSOR not in device._dirty:
        device._dirty.append(PROP_LIGHT_SENSOR)


def _has_panel_light(device: Device) -> bool:
    """Return True if the device reports the panel light (Lig) property."""
    return device.get_property(Props.LIGHT) is not None


GREE_CLOUD_SELECTS: tuple[GreeCloudSelectEntityDescription, ...] = (
    GreeCloudSelectEntityDescription(
        key="Panel Light",
        translation_key="panel_light",
        options=[PANEL_LIGHT_ON, PANEL_LIGHT_AUTO, PANEL_LIGHT_OFF],
        get_value_fn=_get_panel_light,
        set_value_fn=_set_panel_light,
        exists_fn=_has_panel_light,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Gree Cloud selects from a config entry."""

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Register the device."""
        if is_hwhp_device(coordinator):
            return
        async_add_entities(
            GreeCloudSelect(coordinator=coordinator, description=description)
            for description in GREE_CLOUD_SELECTS
            if description.exists_fn(coordinator.device)
        )

    for coordinator in entry.runtime_data.coordinators:
        init_device(coordinator)

    entry.async_on_unload(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeCloudSelect(GreeCloudEntity, SelectEntity):
    """Generic Gree Cloud select entity."""

    entity_description: GreeCloudSelectEntityDescription

    def __init__(
        self,
        coordinator: CloudDeviceDataUpdateCoordinator,
        description: GreeCloudSelectEntityDescription,
    ) -> None:
        """Initialize the Gree Cloud select."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.device_info.mac}_{description.key}"

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self.entity_description.get_value_fn(self.coordinator.device)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.entity_description.set_value_fn(self.coordinator.device, option)
        await self.coordinator.push_state_update()
        self.async_write_ha_state()
