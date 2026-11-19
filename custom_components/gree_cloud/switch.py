"""Support for Gree Cloud switch entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from greeclimate_davo22.device import Device

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DISPATCH_DEVICE_DISCOVERED
from .coordinator import (
    CloudDeviceDataUpdateCoordinator,
    GreeCloudConfigEntry,
    is_hwhp_device,
    is_pool_device,
    is_heatpump_device,
)
from .entity import GreeCloudEntity


@dataclass(kw_only=True, frozen=True)
class GreeCloudSwitchEntityDescription(SwitchEntityDescription):
    """Describes a Gree Cloud switch entity."""

    get_value_fn: Callable[[Device], bool | None]
    set_value_fn: Callable[[Device, bool], None] | None = None
    command_key: str | None = None


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
        get_value_fn=lambda d: bool(d.quiet),
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


HEATPUMP_POWER_SWITCH = GreeCloudSwitchEntityDescription(
    key="versati_power_control",
    translation_key="versati_power",
    get_value_fn=lambda device: (
        bool(device.raw_properties["Pow"])
        if device.raw_properties.get("Pow") in (0, 1)
        else None
    ),
    command_key="Pow",
)


def _versati_flag(key: str) -> Callable[[Device], bool | None]:
    def is_on(device: Device) -> bool | None:
        value = device.raw_properties.get(key)
        return bool(value) if value in (0, 1) else None

    return is_on


# The function buttons of Gree+ on a Versati 5 (#75): Silence, Compensation
# mode, Disinfect and Rapid.
HEATPUMP_FUNCTION_SWITCHES: tuple[GreeCloudSwitchEntityDescription, ...] = tuple(
    GreeCloudSwitchEntityDescription(
        key=f"versati_{name}",
        translation_key=f"versati_{name}",
        get_value_fn=_versati_flag(command_key),
        command_key=command_key,
    )
    for command_key, name in (
        ("Quiet", "quiet"),
        ("SvSt", "weather_dependent"),
        ("SwDisFct", "disinfection"),
        ("FastHtWter", "fast_hot_water"),
    )
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
        if is_heatpump_device(coordinator):
            if coordinator.device_kind != "heatpump":
                return
            approved = coordinator.device.write_policy.approved
            async_add_entities(
                GreeCloudSwitch(coordinator, description)
                for description in (HEATPUMP_POWER_SWITCH, *HEATPUMP_FUNCTION_SWITCHES)
                if description.command_key in approved
            )
            return
        if is_hwhp_device(coordinator) or is_pool_device(coordinator):
            return
        async_add_entities(
            [
                *(
                    GreeCloudSwitch(coordinator=coordinator, description=description)
                    for description in GREE_CLOUD_SWITCHES
                ),
                GreeCloudBeeperSwitch(coordinator),
            ]
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
    def is_on(self) -> bool | None:
        """Return if the state is turned on."""
        return self.entity_description.get_value_fn(self.coordinator.device)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self._async_set_value(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self._async_set_value(False)

    async def _async_set_value(self, value: bool) -> None:
        """Use the device's command path without staging air-to-water AC properties."""
        description = self.entity_description
        if description.command_key is not None:
            await self.coordinator.async_heatpump_command(
                description.command_key, int(value)
            )
            return
        if description.set_value_fn is None:
            raise ValueError("Switch has no command handler")
        description.set_value_fn(self.coordinator.device, value)
        await self.coordinator.push_state_update()
        self.async_write_ha_state()


class GreeCloudBeeperSwitch(GreeCloudEntity, SwitchEntity, RestoreEntity):
    """Confirmation beep on commands (#50).

    Off adds ``Buzzer_ON_OFF=1`` to every command the integration sends, so the
    indoor unit stays silent. The unit does not report this flag, so the state
    lives in Home Assistant and is restored across restarts; nothing is sent to
    the device when it is toggled.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "beeper"
    _attr_is_on = True

    def __init__(self, coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_info.mac}_Beeper"

    async def async_added_to_hass(self) -> None:
        """Restore the last state and apply it to the device object."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._attr_is_on = last.state == "on"
        self.coordinator.device.beeper = self._attr_is_on

    @callback
    def _handle_coordinator_update(self) -> None:
        """The device never reports the flag; keep our own state."""
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Let the unit beep on commands."""
        self._attr_is_on = True
        self.coordinator.device.beeper = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Silence the unit on commands."""
        self._attr_is_on = False
        self.coordinator.device.beeper = False
        self.async_write_ha_state()
