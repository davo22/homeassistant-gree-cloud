"""Native heatpump setpoints, exposed only with approved device-specific limits."""

from homeassistant.components.number import NumberEntity, NumberDeviceClass, NumberMode
from homeassistant.const import UnitOfTemperature

from .entity import GreeCloudEntity
from .heatpump import SETPOINTS, COOLING_SETPOINTS, setpoint


async def async_setup_entry(hass, entry, async_add_entities):
    """Do not advertise controls whose write ranges are unverified."""
    entities = []
    for coordinator in entry.runtime_data.coordinators:
        if coordinator.device_kind != "heatpump":
            continue
        policy = coordinator.device.write_policy
        for key in (*SETPOINTS, *COOLING_SETPOINTS):
            if (
                key in policy.approved
                and key in policy.limits
                and setpoint(coordinator.data or {}, key) is not None
            ):
                entities.append(HeatPumpNumber(coordinator, key))
    async_add_entities(entities)


class HeatPumpNumber(GreeCloudEntity, NumberEntity):
    """One atomic setpoint; actual state changes only after confirmed readback."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self.key = key
        self._attr_translation_key = (SETPOINTS | COOLING_SETPOINTS)[key]
        self._attr_unique_id = (
            f"{coordinator.device.device_info.mac}_versati_number_{key}"
        )
        self._attr_native_min_value, self._attr_native_max_value = (
            coordinator.device.write_policy.limits[key]
        )

    @property
    def native_value(self):
        return setpoint(self.coordinator.data or {}, self.key)

    async def async_set_native_value(self, value):
        await self.coordinator.async_heatpump_command(self.key, value)
