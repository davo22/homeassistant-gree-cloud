"""Verified binary air-to-water states (unverified bit fields stay raw sensors)."""

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import GreeCloudEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Expose power only if the device actually supplies a binary value."""
    async_add_entities(
        HeatPumpPower(coordinator)
        for coordinator in entry.runtime_data.coordinators
        if coordinator.device_kind == "heatpump"
        and (coordinator.data or {}).get("Pow") in (0, 1)
    )


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
