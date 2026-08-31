"""Support for Gree commercial multi-split units behind a shared WiFi controller.

Several indoor units sit behind one controller and share its MQTT topics
(``request/<controller>``, ``status/<controller>/#``). Each message is tagged
with a ``sub`` field holding the indoor unit's MAC.

Upstream ``greeclimate`` has no concept of this, so it:

* derives the MQTT "parent" MAC by stripping the trailing ``00`` from the unit
  MAC -- which only works when the controller happens to be the unit's own
  module, and is wrong when the controller is a separate device; and
* merges every sibling unit's state into one entity, and never tells the
  controller which indoor unit a command is for.

This module recovers the real controller MAC from the cloud API's ``pmac``
field and adds ``sub`` awareness on top of :class:`CloudDevice`.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import json
import logging

from greeclimate.cloud_api import GreeCloudApi
from greeclimate.cloud_device import CloudDevice
from greeclimate.device import Props
from greeclimate.mqtt_client import MqttDeviceMessage

from .const import COMMERCIAL_PROP_IN_TEMP

_LOGGER = logging.getLogger(__name__)

# Columns we poll for. The commercial indoor units report a large custom column
# set; these are the ones that map to climate features. The controller also
# pushes a full unsolicited status burst whenever we (re)subscribe.
_STATUS_COLS: list[str] = [
    Props.POWER.value,
    Props.MODE.value,
    Props.TEMP_SET.value,
    Props.TEMP_DECI.value,
    Props.TEMP_HALF_DEGREE.value,
    Props.FAN_SPEED.value,
    Props.SWING_HORIZ.value,
    Props.SWING_VERT.value,
    Props.TURBO.value,
    Props.QUIET.value,
    Props.SLEEP.value,
    Props.POWER_SAVE.value,
    Props.XFAN.value,
    Props.FRESH_AIR.value,
    COMMERCIAL_PROP_IN_TEMP,
]


async def async_get_parent_macs(api: GreeCloudApi) -> dict[str, str]:
    """Return ``{device mac: controller mac}`` from the API's ``pmac`` field.

    ``greeclimate``'s :meth:`GreeCloudApi.get_devices` does not surface ``pmac``,
    so re-issue ``GetDevsInRoomsOfHomeV2`` using the api's own request helpers.
    Any device without a ``pmac`` is omitted (it is not controller-fronted).
    """

    async def _call(endpoint: str, payload: dict, hash_props: list[str]):
        now = datetime.now(timezone.utc)
        body = json.dumps(api._prepare_body(payload, now, hash_props))
        encrypted = await api._send_request(endpoint, body)
        return json.loads(api._decrypt(base64.b64decode(encrypted)))

    homes = await _call(
        "/App/GetHomes",
        {"token": api.token, "uid": api.user_id},
        ["token", "uid"],
    )
    out: dict[str, str] = {}
    for home in homes.get("home", []):
        devs = await _call(
            "/App/GetDevsInRoomsOfHomeV2",
            {"token": api.token, "homeId": home["id"], "uid": api.user_id},
            ["token", "uid", "homeId"],
        )
        for room in devs.get("rooms", []):
            for dev in room.get("devs", []):
                mac = (dev.get("mac") or "").strip()
                pmac = (dev.get("pmac") or "").strip()
                if mac and pmac:
                    out[mac] = pmac
    return out


class CommercialCloudDevice(CloudDevice):
    """One indoor unit behind a shared commercial WiFi controller."""

    def __init__(self, *args, parent_mac: str, **kwargs) -> None:
        """Initialise, overriding the MQTT parent with the real controller MAC."""
        super().__init__(*args, **kwargs)
        self._child_mac = self.device_info.mac
        self._parent_mac = parent_mac

    # -- receive ----------------------------------------------------------------
    def _handle_mqtt_message(
        self, topic: str, message: MqttDeviceMessage
    ) -> None:
        """Ignore messages addressed to a sibling unit on the same controller."""
        if message.pack and ("status/" in topic or "response/" in topic):
            try:
                decrypted = self.device_cipher.decrypt(message.pack)
            except Exception:  # noqa: BLE001 - the base class logs decrypt errors
                decrypted = None
            if isinstance(decrypted, dict):
                sub = decrypted.get("sub")
                if sub and sub != self._child_mac:
                    _LOGGER.debug(
                        "Ignoring message for sibling %s (this device is %s)",
                        sub,
                        self._child_mac,
                    )
                    return
        super()._handle_mqtt_message(topic, message)

    def handle_state_update(self, **kwargs) -> None:
        """Map commercial column names onto the standard ``Props``."""
        if COMMERCIAL_PROP_IN_TEMP in kwargs:
            kwargs.setdefault(
                Props.TEMP_SENSOR.value, kwargs.pop(COMMERCIAL_PROP_IN_TEMP)
            )
        # Commercial units omit these; default them so target_temperature and the
        # unit accessor return a value instead of None.
        if Props.TEMP_SET.value in kwargs:
            kwargs.setdefault(Props.TEMP_BIT.value, 0)
            kwargs.setdefault(Props.TEMP_UNIT.value, 0)
        super().handle_state_update(**kwargs)

    # -- send -----------------------------------------------------------------
    async def _publish(self, command: dict) -> None:
        """Publish a pack stamped with the controller (``mac``) and unit (``sub``)."""
        command = {**command, "mac": self._parent_mac, "sub": self._child_mac}
        await self._mqtt_client.publish_command(
            self._parent_mac, command, self.device_cipher, self._child_mac
        )

    async def update_state(self) -> None:
        """Refresh state.

        The controller answers a poll with the requested columns but blank
        values, and pushes the real values on the status topic (on connect and
        on change). Wait briefly for real data; a blank ack is not an error, and
        a missing reply just means the last known state still stands.
        """
        cols = list(_STATUS_COLS)
        if not self.hid:
            cols.append("hid")

        self._response_event = asyncio.Event()
        self._response_data = None
        await self._publish({"t": "status", "cols": cols})

        try:
            for _ in range(2):
                await asyncio.wait_for(self._response_event.wait(), timeout=3)
                clean = {
                    k: v
                    for k, v in (self._response_data or {}).items()
                    if v not in ("", None)
                }
                if clean:
                    self.handle_state_update(**clean)
                    return
                self._response_event = asyncio.Event()
                self._response_data = None
        except asyncio.TimeoutError:
            _LOGGER.debug(
                "No fresh state for commercial unit %s; keeping last known",
                self._child_mac,
            )
        finally:
            self._response_event = None
            self._response_data = None

    async def _send_command(self, opt: list, p: list) -> None:
        """Send one command pack (with ``mac``/``sub``) and wait for the ack."""
        self._response_event = asyncio.Event()
        await self._publish({"t": "cmd", "opt": opt, "p": p})
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=3)
        except asyncio.TimeoutError:
            _LOGGER.debug(
                "No ack from commercial unit %s (command may still have applied)",
                self._child_mac,
            )
        finally:
            self._response_event = None
