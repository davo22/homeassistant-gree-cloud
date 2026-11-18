"""Helpers shared by the tests."""

from __future__ import annotations

import enum
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er


def _plain(value: Any) -> Any:
    """Turn Home Assistant values into something a snapshot shows readably."""
    if isinstance(value, enum.IntFlag):
        return sorted(flag.name for flag in type(value) if flag in value and flag.name)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(_plain(key)): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(item) for item in value)
    return value


def describe(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Everything the user sees of a config entry: its devices and entities.

    This is what the snapshots hold. Unique ids are part of it on purpose:
    changing one orphans the entity in every installation, with its history,
    its dashboard cards and its automations.
    """
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    described: dict[str, Any] = {"devices": [], "entities": {}}
    names: dict[str, str] = {}
    for device in sorted(
        dr.async_entries_for_config_entry(devices, entry.entry_id), key=lambda d: d.name or ""
    ):
        names[device.id] = device.name
        described["devices"].append(
            {
                "name": device.name,
                "identifiers": sorted(list(identifier) for identifier in device.identifiers),
                "connections": sorted(list(connection) for connection in device.connections),
                "manufacturer": device.manufacturer,
                "model": device.model,
                "sw_version": device.sw_version,
                "via_device": names.get(device.via_device_id) if device.via_device_id else None,
            }
        )
    for item in sorted(
        er.async_entries_for_config_entry(entities, entry.entry_id), key=lambda e: e.entity_id
    ):
        state = hass.states.get(item.entity_id)
        described["entities"][item.entity_id] = {
            "unique_id": item.unique_id,
            "device": names.get(item.device_id),
            "name": item.name or item.original_name,
            "translation_key": item.translation_key,
            "category": _plain(item.entity_category),
            "disabled_by": _plain(item.disabled_by),
            "state": state.state if state else None,
            "attributes": _plain(dict(state.attributes)) if state else None,
        }
    return described


def entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """The entity id behind a unique id; fails when there is no such entity."""
    found = er.async_get(hass).async_get_entity_id(platform, "gree_cloud", unique_id)
    assert found is not None, f"no {platform} entity with the unique id {unique_id}"
    return found


async def call(hass: HomeAssistant, domain: str, service: str, entity: str, **data: Any) -> None:
    """Call a service on one entity, the way an automation or the UI does."""
    await hass.services.async_call(
        domain, service, {"entity_id": entity, **data}, blocking=True
    )
