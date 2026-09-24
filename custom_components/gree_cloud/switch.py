"""Support for Gree Cloud switch entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from greeclimate.device import Device, Mode

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DEHUMIDIFY_MODE_CONTINUOUS,
    DEHUMIDIFY_MODE_OFF,
    DEHUMIDIFY_MODE_ON,
    DEHUMIDIFY_MODE_SMART,
    DISPATCH_DEVICE_DISCOVERED,
    PROP_BUZZER_CTRL,
    PROP_DEHUMIDIFY_MODE,
)
from .coordinator import CloudDeviceDataUpdateCoordinator, GreeCloudConfigEntry, is_hwhp_device
from .entity import GreeCloudEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True, frozen=True)
class GreeCloudSwitchEntityDescription(SwitchEntityDescription):
    """Describes a Gree Cloud switch entity."""

    get_value_fn: Callable[[Device], bool]
    set_value_fn: Callable[[Device, bool], None]
    exists_fn: Callable[[Device], bool] = lambda device: True
    available_fn: Callable[[Device], bool] = lambda device: True


def _set_quiet(device: Device, value: bool) -> None:
    """Typed helper to set device quiet property.

    Deprecated: kept for this release only for backward compatibility with
    existing automations that reference switch.<device>_quiet directly; a
    future release will remove it. Still backed by the same device.quiet
    property as the climate entity's "quiet" fan mode, so the two can't go
    out of sync - there's only one source of truth, this switch and the
    fan mode just read/write the same thing.
    """
    _LOGGER.warning(
        "The Quiet switch is deprecated and will be removed in a future "
        "release; use the climate entity's 'quiet' fan mode instead."
    )
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


def _set_dehumidify_mode(device: Device, value: int) -> None:
    """Write a Dmod value directly through raw_properties.

    Dmod has no setter in greeclimate (it's exposed read-only), so it's
    written directly, the same pattern used for HWHP properties. Dmod holds
    a single value at a time (15=off/0=target dehumidify/1=continuous
    dry/2=smart), so each of the three switches below just writes its own
    value and lets the others read back whatever Dmod ends up holding,
    rather than fighting over it.
    """
    device.raw_properties[PROP_DEHUMIDIFY_MODE] = value
    if PROP_DEHUMIDIFY_MODE not in device._dirty:
        device._dirty.append(PROP_DEHUMIDIFY_MODE)


def _get_dehumidify(device: Device) -> bool:
    """Typed helper to read the Target Dehumidify (Dmod) state."""
    return device.raw_properties.get(PROP_DEHUMIDIFY_MODE) == DEHUMIDIFY_MODE_ON


def _set_dehumidify(device: Device, value: bool) -> None:
    """Typed helper to set the Target Dehumidify (Dmod) state."""
    _set_dehumidify_mode(device, DEHUMIDIFY_MODE_ON if value else DEHUMIDIFY_MODE_OFF)


def _get_continuous_dry(device: Device) -> bool:
    """Typed helper to read the Continuous Dry (Dmod) state."""
    return device.raw_properties.get(PROP_DEHUMIDIFY_MODE) == DEHUMIDIFY_MODE_CONTINUOUS


def _set_continuous_dry(device: Device, value: bool) -> None:
    """Typed helper to set the Continuous Dry (Dmod) state."""
    _set_dehumidify_mode(device, DEHUMIDIFY_MODE_CONTINUOUS if value else DEHUMIDIFY_MODE_OFF)


def _get_smart_drying(device: Device) -> bool:
    """Typed helper to read the Smart Drying (Dmod) state."""
    return device.raw_properties.get(PROP_DEHUMIDIFY_MODE) == DEHUMIDIFY_MODE_SMART


def _set_smart_drying(device: Device, value: bool) -> None:
    """Typed helper to set the Smart Drying (Dmod) state."""
    _set_dehumidify_mode(device, DEHUMIDIFY_MODE_SMART if value else DEHUMIDIFY_MODE_OFF)


def _has_dehumidify_mode(device: Device) -> bool:
    """Return True if the device reports dehumidify mode (Dmod) support.

    Units without this feature omit the Dmod key entirely rather than
    reporting 0, matching the convention used for other optional properties.
    """
    return device.raw_properties.get(PROP_DEHUMIDIFY_MODE) is not None


def _get_silent_mode(device: Device) -> bool:
    """Typed helper to read the Silent Mode (BuzzerCtrl) state."""
    return device.raw_properties.get(PROP_BUZZER_CTRL) == 0


def _set_silent_mode(device: Device, value: bool) -> None:
    """Typed helper to set the Silent Mode (BuzzerCtrl) state.

    BuzzerCtrl has no setter in greeclimate, so it's written directly
    through raw_properties, the same pattern used for Dmod. The raw value
    is inverted relative to the switch: 1 = beep on (normal), 0 = beep off
    (silent) - so "Silent Mode" on means BuzzerCtrl=0.
    """
    device.raw_properties[PROP_BUZZER_CTRL] = 0 if value else 1
    if PROP_BUZZER_CTRL not in device._dirty:
        device._dirty.append(PROP_BUZZER_CTRL)


def _has_silent_mode(device: Device) -> bool:
    """Return True if the device reports Silent Mode (BuzzerCtrl) support.

    Units without this feature omit the key entirely rather than reporting
    a value, matching the convention used for other optional properties.
    """
    return device.raw_properties.get(PROP_BUZZER_CTRL) is not None


def _available_in_modes(*modes: Mode) -> Callable[[Device], bool]:
    """Build an available_fn restricted to the given HVAC modes.

    Several switches only make sense in specific HVAC modes: the
    dehumidify-related ones (Target Dehumidify in both Cool and Dry, Smart
    Drying only while cooling, Continuous Dry only while drying), and XFan
    (Cool and Dry only - it dries the coil after cooling/drying, which is
    meaningless in Heat/Fan/Auto). When the current mode isn't in the
    allowed set, `available` (see GreeCloudSwitch below) turns False and
    the switch shows as unavailable rather than a stale on/off state left
    over from a previous mode.
    """

    def _available(device: Device) -> bool:
        return device.mode in modes

    return _available


_TARGET_DEHUMIDIFY_AVAILABLE = _available_in_modes(Mode.Cool, Mode.Dry)
_SMART_DRYING_AVAILABLE = _available_in_modes(Mode.Cool)
_CONTINUOUS_DRY_AVAILABLE = _available_in_modes(Mode.Dry)
_XFAN_AVAILABLE = _available_in_modes(Mode.Cool, Mode.Dry)


GREE_CLOUD_SWITCHES: tuple[GreeCloudSwitchEntityDescription, ...] = (
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
        available_fn=_XFAN_AVAILABLE,
    ),
    GreeCloudSwitchEntityDescription(
        key="Health mode",
        translation_key="health_mode",
        get_value_fn=lambda d: d.anion,
        set_value_fn=_set_anion,
        entity_registry_enabled_default=False,
    ),
    GreeCloudSwitchEntityDescription(
        key="Dehumidify",
        translation_key="dehumidify",
        get_value_fn=_get_dehumidify,
        set_value_fn=_set_dehumidify,
        exists_fn=_has_dehumidify_mode,
        available_fn=_TARGET_DEHUMIDIFY_AVAILABLE,
    ),
    GreeCloudSwitchEntityDescription(
        key="Continuous Dry",
        translation_key="continuous_dry",
        get_value_fn=_get_continuous_dry,
        set_value_fn=_set_continuous_dry,
        exists_fn=_has_dehumidify_mode,
        available_fn=_CONTINUOUS_DRY_AVAILABLE,
    ),
    GreeCloudSwitchEntityDescription(
        key="Smart Drying",
        translation_key="smart_drying",
        get_value_fn=_get_smart_drying,
        set_value_fn=_set_smart_drying,
        exists_fn=_has_dehumidify_mode,
        available_fn=_SMART_DRYING_AVAILABLE,
    ),
    GreeCloudSwitchEntityDescription(
        key="Silent Mode",
        translation_key="silent_mode",
        get_value_fn=_get_silent_mode,
        set_value_fn=_set_silent_mode,
        exists_fn=_has_silent_mode,
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
        if is_hwhp_device(coordinator):
            return
        async_add_entities(
            GreeCloudSwitch(coordinator=coordinator, description=description)
            for description in GREE_CLOUD_SWITCHES
            if description.exists_fn(coordinator.device)
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
    def available(self) -> bool:
        """Return True if the switch is available in the device's current mode."""
        return super().available and self.entity_description.available_fn(
            self.coordinator.device
        )

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
