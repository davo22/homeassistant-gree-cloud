"""A Gree cloud that lives inside the test process.

The integration and the ``greeclimate-davo22`` library run unchanged. Three
points where they would leave the machine are replaced:

* the account API (``GreeCloudApi.login`` / ``get_all_devices``),
* the MQTT broker connection (``aiomqtt.Client``),
* the legacy TLS gateway (``GreeCloudGateway.request``).

Everything in between is real: envelopes, AES packs, topics, addressing,
timeouts, the library's request/response matching. A test therefore sees the
exact packs a real unit would receive, and a unit here answers the way the
recorded one did (see ``tests/fixtures`` and ``tests/README.md``).
"""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiomqtt
from greeclimate_davo22 import cloud_device, mqtt_client
from greeclimate_davo22.cipher import CipherV1
from greeclimate_davo22.cloud_api import CloudCredentials, CloudDeviceInfo, GreeCloudApi
from greeclimate_davo22.cloud_gateway import GreeCloudGateway
from greeclimate_davo22.exceptions import DeviceOfflineError

FIXTURES = Path(__file__).parent / "fixtures"

USER_ID = 100200
TOKEN = "fake-token"

# Gateway shapes of a command to a unit behind a module, as the library sends
# them: {(envelope names the unit, fields in the pack): name}.
_GATEWAY_COMMAND_SHAPES = {
    (False, ("sub",)): "sub",
    (False, ("mac", "sub")): "sub+mac",
    (True, ()): "tcid-unit",
    (True, ("sub",)): "tcid-unit+sub",
    (False, ("mac",)): "mac",
}


def load_fixture(name: str) -> dict[str, Any]:
    """Return the recorded device ``tests/fixtures/<name>.json``."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _guess_module(mac: str) -> str:
    """The module a unit id derives from, the way the library guesses it."""
    return mac[:-2] if mac.endswith("00") and len(mac) > 12 else mac


class FakeUnit:
    """One device in the fake cloud: its cloud record, its state, its manners."""

    def __init__(self, fixture: dict[str, Any], **overrides: Any) -> None:
        fixture = copy.deepcopy(fixture)
        record = {**fixture["record"]}
        for name in list(overrides):
            if name in record:
                record[name] = overrides.pop(name)
        self.record = CloudDeviceInfo(**record)
        self.state: dict[str, Any] = fixture["state"]
        self.state.update(overrides.pop("state", {}))
        self.hid: str | None = fixture.get("hid")

        # Manners. The defaults describe a split air conditioner on MQTT.
        self.answers_status: bool = fixture.get("answers_status", True)
        # Sends its whole state by itself after a command changed it.
        self.reports_changes: bool = fixture.get("reports_changes", False)
        # Acknowledges a request for a report and then sends its whole state.
        self.reports_on_request: bool = fixture.get("reports_on_request", False)
        # ...the other way round: the state first, the acknowledgement after.
        self.reports_before_ack: bool = False
        self.acks_commands: bool = True
        self.executes_commands: bool = True
        self.command_result: int = 200
        # Longer status requests are dropped without an answer.
        self.max_columns: int | None = fixture.get("max_columns")
        # A status request naming any of these is dropped without an answer.
        self.ignores_columns: set[str] = set()
        # "omit": unknown columns are left out; "zero": answered with 0.
        self.unknown_columns: str = fixture.get("unknown_columns", "omit")
        self.transport: str = fixture.get("transport", "mqtt")
        # MQTT: "tcid" (unit named by the envelope) and/or "pack" (inside the pack).
        self.mqtt_addressing: set[str] = set(fixture.get("mqtt_addressing", ["tcid"]))
        # Gateway: the request shapes this unit answers.
        self.status_addressing: set[str] = set(fixture.get("status_addressing", ["unit"]))
        self.command_addressing: set[str] = set(fixture.get("command_addressing", ["plain"]))
        # Properties the unit acknowledges but does not apply.
        self.refuses: set[str] = set()
        for name, value in overrides.items():
            if not hasattr(self, name):
                raise TypeError(f"FakeUnit has no setting {name!r}")
            setattr(self, name, value)

        self.cipher = CipherV1(self.record.key.encode())
        # Every pack the unit received, decrypted, in order.
        self.received: list[dict[str, Any]] = []

    @property
    def mac(self) -> str:
        return self.record.mac

    @property
    def module_mac(self) -> str:
        """MAC of the Wi-Fi module the unit is reached through."""
        return (self.record.parent_mac or "").strip() or _guess_module(self.mac)

    @property
    def reply_mac(self) -> str:
        """What the unit puts in ``mac`` of its replies.

        A module with one unit answers with its own MAC (as recorded from a
        commercial unit); a head of a multi-head system with the head's id.
        """
        return self.module_mac if self.mac.startswith(self.module_mac) else self.mac

    @property
    def status_requests(self) -> list[list[str]]:
        """The column lists of the status requests received so far."""
        return [pack["cols"] for pack in self.received if pack.get("t") == "status"]

    @property
    def commands(self) -> list[dict[str, Any]]:
        """The commands received so far, each as ``{property: value}``."""
        return [
            dict(zip(pack["opt"], pack["p"]))
            for pack in self.received
            if pack.get("t") == "cmd"
        ]

    def forget(self) -> None:
        """Drop what was received so far (typically: the setup traffic)."""
        self.received.clear()

    def dat(self, keys: list[str] | None = None) -> dict[str, Any]:
        """A state pack as the unit sends it by itself."""
        keys = list(self.state) if keys is None else keys
        pack = {"t": "dat", "mac": self.reply_mac, "cols": keys, "dat": [self.state[k] for k in keys]}
        if self.reply_mac == self.module_mac:
            pack["cid"] = self.reply_mac
        return pack

    def answer(self, pack: dict[str, Any]) -> dict[str, Any] | None:
        """Take one decrypted pack; return the reply, or None for silence."""
        self.received.append(copy.deepcopy(pack))
        if pack.get("t") == "status":
            return self._answer_status(pack["cols"])
        if pack.get("t") == "cmd":
            return self._answer_command(pack["opt"], pack["p"])
        if self.asked_to_report(pack):
            return {"t": "res", "r": 200}
        return None

    def asked_to_report(self, pack: dict[str, Any]) -> bool:
        """True for a request for a report that this unit follows."""
        return self.reports_on_request and pack.get("t") == "freqCount"

    @property
    def report_requests(self) -> list[dict[str, Any]]:
        """The requests for a report received so far."""
        return [pack for pack in self.received if pack.get("t") == "freqCount"]

    def _answer_status(self, cols: list[str]) -> dict[str, Any] | None:
        if not self.answers_status:
            return None
        if self.max_columns is not None and len(cols) > self.max_columns:
            return None
        if self.ignores_columns.intersection(cols):
            return None
        known: list[str] = []
        values: list[Any] = []
        for col in cols:
            if col == "hid":
                if self.hid:
                    known.append(col)
                    values.append(self.hid)
            elif col in self.state:
                known.append(col)
                values.append(self.state[col])
            elif self.unknown_columns == "zero":
                known.append(col)
                values.append(0)
        reply = {"t": "dat", "uid": 0, "mac": self.reply_mac, "dat": values, "cols": known, "r": 200}
        if self.reply_mac == self.module_mac:
            reply["cid"] = self.reply_mac
        return reply

    def _answer_command(self, opt: list[str], p: list[Any]) -> dict[str, Any] | None:
        if self.command_result != 200:
            return {"t": "res", "mac": self.reply_mac, "r": self.command_result}
        if self.executes_commands:
            for key, value in zip(opt, p):
                # The beeper flag belongs to the command, not to the state.
                if key != cloud_device.BUZZER_FLAG and key not in self.refuses:
                    self.state[key] = value
        if not self.acks_commands:
            return None
        return {"t": "res", "mac": self.reply_mac, "r": 200, "opt": list(opt), "p": list(p), "val": list(p)}


@dataclass
class _Message:
    """What ``aiomqtt`` hands to the library for a received publication."""

    topic: str
    payload: bytes


class _Dropped:
    """Queue marker: the broker connection is gone."""


class FakeMqttSession:
    """Stands in for ``aiomqtt.Client``: one connection to the fake broker."""

    def __init__(self, cloud: "FakeCloud", **options: Any) -> None:
        self.cloud = cloud
        self.options = options
        self.subscriptions: set[str] = set()
        self.open = False
        self.dropped = False
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._handling = False

    async def __aenter__(self) -> "FakeMqttSession":
        self.cloud.connect_attempts += 1
        if self.cloud.connect_error is not None:
            raise self.cloud.connect_error
        self.open = True
        self.cloud.sessions.append(self)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.open = False

    # The library iterates ``client.messages``.
    @property
    def messages(self) -> "FakeMqttSession":
        return self

    def __aiter__(self) -> "FakeMqttSession":
        return self

    async def __anext__(self) -> _Message:
        if self._handling:
            # The library came back for more: the previous message is handled.
            self._handling = False
            self._queue.task_done()
        item = await self._queue.get()
        self._handling = True
        if isinstance(item, _Dropped):
            raise aiomqtt.MqttError("Disconnected during message iteration")
        return item

    def _check(self, what: str) -> None:
        if self.dropped or not self.open:
            raise aiomqtt.MqttCodeError(4, f"Could not {what}")

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        self._check("subscribe")
        if topic.partition("/")[0] in self.cloud.refused_topics:
            self.cloud.refused.append(topic)
            raise aiomqtt.MqttCodeError(135, "Could not subscribe")
        self.subscriptions.add(topic)

    async def unsubscribe(self, topic: str) -> None:
        self._check("unsubscribe")
        self.subscriptions.discard(topic)

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        self._check("publish message")
        self.cloud._published(topic, json.loads(payload))

    def listens_to(self, topic: str) -> bool:
        for pattern in self.subscriptions:
            if pattern == topic:
                return True
            if pattern.endswith("/#") and topic.startswith(pattern[:-1]):
                return True
        return False

    def deliver(self, topic: str, envelope: dict[str, Any]) -> None:
        if self.open and not self.dropped and self.listens_to(topic):
            self._queue.put_nowait(_Message(topic, json.dumps(envelope).encode()))

    def drop(self) -> None:
        """Lose the connection, the way the broker does after a token expiry."""
        self.dropped = True
        self._queue.put_nowait(_Dropped())

    async def settle(self) -> None:
        """Wait until the library has handled everything delivered so far."""
        if self.open and not self.dropped:
            await self._queue.join()


@dataclass
class FakeCloud:
    """The account: its units, and a record of everything asked of it."""

    units: list[FakeUnit] = field(default_factory=list)
    # Set to an exception to make the next logins / broker connections fail.
    login_error: BaseException | None = None
    connect_error: BaseException | None = None
    devices_error: BaseException | None = None
    logins: int = 0
    connect_attempts: int = 0
    api_closes: int = 0
    # (base url, user name, password) of every API client that logged in.
    accounts: list[tuple[str, str, str]] = field(default_factory=list)
    sessions: list[FakeMqttSession] = field(default_factory=list)
    # (topic, envelope) of everything published to the broker.
    published: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    # Kinds of topic ("request") the broker lets nobody subscribe to, and the
    # subscriptions it turned down.
    refused_topics: set[str] = field(default_factory=set)
    refused: list[str] = field(default_factory=list)
    # {"route", "tcid", "pack"} of every legacy gateway request.
    gateway_requests: list[dict[str, Any]] = field(default_factory=list)
    # Modules the legacy gateway reports offline (QueryOnline).
    offline: set[str] = field(default_factory=set)

    # -- arranging -------------------------------------------------------

    def add(self, fixture: str | dict[str, Any], **overrides: Any) -> FakeUnit:
        """Put a recorded device into the account; returns it for inspection.

        *overrides* replace fields of the cloud record (``name``, ``mac``,
        ``version``...), settings of :class:`FakeUnit` (``answers_status``,
        ``max_columns``...) or, as ``state={...}``, reported properties.
        """
        if isinstance(fixture, str):
            fixture = load_fixture(fixture)
        unit = FakeUnit(fixture, **overrides)
        if any(other.mac == unit.mac for other in self.units):
            raise ValueError(f"Two units with the MAC {unit.mac}")
        self.units.append(unit)
        return unit

    @property
    def session(self) -> FakeMqttSession:
        """The broker connection currently in use."""
        return self.sessions[-1]

    # -- acting ----------------------------------------------------------

    async def push(self, unit: FakeUnit, keys: list[str] | None = None, **changes: Any) -> None:
        """Let *unit* report its state by itself (after applying *changes*).

        The whole state unless *keys* names the properties. Returns once the
        library has processed the message.
        """
        unit.state.update(changes)
        self._report(unit, keys)
        await self.settle()

    async def settle(self) -> None:
        """Wait until every delivered broker message has been handled."""
        for session in self.sessions:
            await session.settle()

    async def app_request(self, unit: FakeUnit, pack: dict[str, Any]) -> None:
        """Let another client (the Gree+ app) ask *unit* something.

        Only what a listener on the unit's request topic gets to see: the unit
        does not act on it.
        """
        encrypted, _ = unit.cipher.encrypt(pack)
        envelope = {"t": "pack", "i": 0, "uid": 0, "cid": "app", "tcid": unit.mac, "pack": encrypted}
        self._broadcast(f"request/{unit.module_mac}", envelope)
        await self.settle()

    def drop_connection(self) -> None:
        """Cut the broker connection; publishing now fails with code 4."""
        for session in self.sessions:
            if session.open and not session.dropped:
                session.drop()

    # -- the broker ------------------------------------------------------

    def _report(self, unit: FakeUnit, keys: list[str] | None = None) -> None:
        encrypted, _ = unit.cipher.encrypt(unit.dat(keys))
        envelope = {"t": "pack", "i": 0, "uid": 0, "cid": unit.mac, "tcid": "", "pack": encrypted}
        self._broadcast(f"status/{unit.module_mac}/{unit.mac}", envelope)

    def _broadcast(self, topic: str, envelope: dict[str, Any]) -> None:
        for session in self.sessions:
            session.deliver(topic, envelope)

    def _published(self, topic: str, envelope: dict[str, Any]) -> None:
        self.published.append((topic, envelope))
        kind, _, module = topic.partition("/")
        if kind != "request":
            return
        # The broker hands a request to whoever listens on that topic, the
        # sender included (seen on a running Home Assistant).
        self._broadcast(topic, envelope)
        found = self._mqtt_target(module, envelope)
        if found is None:
            return
        unit, pack = found
        before = dict(unit.state)
        reply = unit.answer(pack)
        reports = unit.asked_to_report(pack)
        if reports and unit.reports_before_ack:
            self._report(unit)
            reports = False
        if reply is not None:
            encrypted, _ = unit.cipher.encrypt(reply)
            self._broadcast(
                f"response/{module}/{envelope['cid']}",
                {"t": "pack", "i": 0, "uid": 0, "cid": unit.mac, "tcid": envelope["cid"], "pack": encrypted},
            )
        if reports or (unit.reports_changes and unit.state != before):
            self._report(unit)

    def _mqtt_target(self, module: str, envelope: dict[str, Any]) -> tuple[FakeUnit, dict[str, Any]] | None:
        """The unit a published request reaches, with the decrypted pack."""
        tcid = envelope.get("tcid")
        for unit in self.units:
            if unit.module_mac != module or unit.transport != "mqtt":
                continue
            try:
                pack = unit.cipher.decrypt(envelope["pack"])
            except Exception:  # a pack made with another unit's key
                continue
            if not isinstance(pack, dict) or "t" not in pack:
                continue
            named = pack.get("mac") or pack.get("sub")
            if tcid == unit.mac and named in (None, unit.mac):
                if unit.mac == module or "tcid" in unit.mqtt_addressing:
                    return unit, pack
            elif tcid == module and named == unit.mac and "pack" in unit.mqtt_addressing:
                return unit, pack
        return None

    # -- the legacy gateway ---------------------------------------------

    def _gateway_request(
        self, route: str, cipher: Any, command: dict[str, Any], tcid: str | None
    ) -> dict[str, Any]:
        tcid = tcid or route
        self.gateway_requests.append({"route": route, "tcid": tcid, "pack": copy.deepcopy(command)})
        reachable = [
            unit
            for unit in self.units
            if unit.transport == "gateway" and unit.module_mac not in self.offline
        ]
        online = {unit.module_mac for unit in reachable} | {
            unit.mac for unit in reachable if "unit" in unit.status_addressing
        }
        if route not in online:
            raise DeviceOfflineError(f"Device {route} is offline (QueryOnline)")

        for unit in reachable:
            shape = self._gateway_shape(unit, route, tcid, command)
            if shape is None:
                continue
            accepted = unit.command_addressing if command.get("t") == "cmd" else unit.status_addressing
            if shape not in accepted:
                continue
            try:
                # Through the unit's own key, as on the wire.
                pack = unit.cipher.decrypt(cipher.encrypt(command)[0])
            except Exception:
                continue
            reply = unit.answer(pack)
            if reply is None:
                break
            return cipher.decrypt(unit.cipher.encrypt(reply)[0])
        raise asyncio.TimeoutError(f"No reply from {route} (tcid {tcid})")

    @staticmethod
    def _gateway_shape(unit: FakeUnit, route: str, tcid: str, command: dict[str, Any]) -> str | None:
        """Name the way a gateway request addresses *unit*; None when it does not."""
        fields = tuple(sorted(k for k in ("mac", "sub") if k in command))
        if any(command[k] != unit.mac for k in fields):
            return None
        module = unit.module_mac
        if unit.mac == module:
            # A module with its own unit: status names it, commands are bare.
            if route != unit.mac or tcid != unit.mac:
                return None
            if command.get("t") == "cmd":
                return "plain" if not fields else None
            return "unit" if fields == ("mac",) else None
        if command.get("t") == "cmd":
            if route not in (module, unit.mac) or tcid not in (module, unit.mac):
                return None
            if tcid == module and not fields:
                return None
            return _GATEWAY_COMMAND_SHAPES.get((tcid == unit.mac, fields))
        if fields == ("mac",):
            if route == unit.mac and tcid == unit.mac:
                return "unit"
            if route == module:
                return "module" if tcid == module else "module-as-unit" if tcid == unit.mac else None
            return None
        if not fields and route == module and tcid == module:
            return "module-plain"
        return None

    # -- wiring ----------------------------------------------------------

    def install(self, monkeypatch: Any) -> None:
        """Route the library's three exits into this cloud."""
        cloud = self

        async def login(api: GreeCloudApi) -> CloudCredentials:
            cloud.logins += 1
            if cloud.login_error is not None:
                raise cloud.login_error
            cloud.accounts.append((api.base_url, api.username, api.password))
            api.user_id, api.token = USER_ID, TOKEN
            return CloudCredentials(user_id=USER_ID, token=TOKEN)

        async def get_all_devices(api: GreeCloudApi) -> list[CloudDeviceInfo]:
            if cloud.devices_error is not None:
                raise cloud.devices_error
            return [copy.copy(unit.record) for unit in cloud.units]

        real_close = GreeCloudApi.close

        async def close(api: GreeCloudApi) -> None:
            cloud.api_closes += 1
            await real_close(api)

        async def request(
            gateway: GreeCloudGateway,
            mac: str,
            cipher: Any,
            command: dict[str, Any],
            tcid: str | None = None,
            timeout: float | None = None,
        ) -> dict[str, Any]:
            return cloud._gateway_request(mac, cipher, command, tcid)

        def connect_to_broker(**options: Any) -> FakeMqttSession:
            return FakeMqttSession(cloud, **options)

        monkeypatch.setattr(GreeCloudApi, "login", login)
        monkeypatch.setattr(GreeCloudApi, "get_all_devices", get_all_devices)
        monkeypatch.setattr(GreeCloudApi, "close", close)
        monkeypatch.setattr(GreeCloudGateway, "request", request)
        monkeypatch.setattr(mqtt_client.aiomqtt, "Client", connect_to_broker)
