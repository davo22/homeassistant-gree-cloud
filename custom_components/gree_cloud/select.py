"""Support for Gree Cloud select entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from greeclimate.device import Device, Mode

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DEHUMIDIFY_MODE_OFF,
    DEHUMIDIFY_MODE_ON,
    DEHUMIDIFY_MODE_SMART,
    DEHUMIDIFY_OPTION_COOLING,
    DEHUMIDIFY_OPTION_DEHUMIDIFY,
    DISPATCH_DEVICE_DISCOVERED,
    PROP_DEHUMIDIFY_MODE,
)
from .coordinator import CloudDeviceDataUpdateCoordinator, GreeCloudConfigEntry, is_hwhp_device
from .entity import GreeCloudEntity


@dataclass(kw_only=True, frozen=True)
class GreeCloudSelectEntityDescription(SelectEntityDescription):
    """Describes a Gree Cloud select entity."""

    get_value_fn: Callable[[Device], str | None]
    set_value_fn: Callable[[Device, str], None]
    exists_fn: Callable[[Device], bool] = lambda device: True
    available_fn: Callable[[Device], bool] = lambda device: True


def _get_dehumidify_mode(device: Device) -> str | None:
    """Typed helper to read the dehumidify mode (Dmod) as a select option.

    Dmod=DEHUMIDIFY_MODE_SMART (Smart Drying) is a variant of the
    dehumidify state rather than a third selector option, so it also reads
    back as "dehumidify" here; the separate Smart Drying switch exposes the
    smart/plain distinction.
    """
    raw = device.raw_properties.get(PROP_DEHUMIDIFY_MODE)
    if raw == DEHUMIDIFY_MODE_OFF:
        return DEHUMIDIFY_OPTION_COOLING
    if raw in (DEHUMIDIFY_MODE_ON, DEHUMIDIFY_MODE_SMART):
        return DEHUMIDIFY_OPTION_DEHUMIDIFY
    return None


def _set_dehumidify_mode(device: Device, option: str) -> None:
    """Typed helper to set the dehumidify mode (Dmod).

    Dmod has no setter in greeclimate (it's exposed read-only), so it's
    written directly through raw_properties, the same pattern used for
    HWHP properties. Selecting "Cooling" always fully disables
    dehumidification, including Smart Drying; selecting
    "Cooling + Dehumidify" turns on plain (non-smart) dehumidify.
    """
    value = DEHUMIDIFY_MODE_OFF if option == DEHUMIDIFY_OPTION_COOLING else DEHUMIDIFY_MODE_ON
    device.raw_properties[PROP_DEHUMIDIFY_MODE] = value
    if PROP_DEHUMIDIFY_MODE not in device._dirty:
        device._dirty.append(PROP_DEHUMIDIFY_MODE)


def _has_dehumidify_mode(device: Device) -> bool:
    """Return True if the device reports dehumidify mode support.

    Units without this feature omit the Dmod key entirely rather than
    reporting a value, matching the convention used for other optional
    properties.
    """
    return device.raw_properties.get(PROP_DEHUMIDIFY_MODE) is not None


def _dehumidify_mode_available(device: Device) -> bool:
    """Dehumidify mode only applies in Cool or Dry mode."""
    return device.mode in (Mode.Cool, Mode.Dry)


GREE_CLOUD_SELECTS: tuple[GreeCloudSelectEntityDescription, ...] = (
    GreeCloudSelectEntityDescription(
        key="Dehumidify Mode",
        translation_key="dehumidify_mode",
        options=[DEHUMIDIFY_OPTION_COOLING, DEHUMIDIFY_OPTION_DEHUMIDIFY],
        get_value_fn=_get_dehumidify_mode,
        set_value_fn=_set_dehumidify_mode,
        exists_fn=_has_dehumidify_mode,
        available_fn=_dehumidify_mode_available,
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
    def available(self) -> bool:
        """Return True if the select is available in the device's current mode."""
        return super().available and self.entity_description.available_fn(
            self.coordinator.device
        )

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self.entity_description.get_value_fn(self.coordinator.device)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.entity_description.set_value_fn(self.coordinator.device, option)
        await self.coordinator.push_state_update()
        self.async_write_ha_state()
