"""
Home Assistant in memory, as its WebSocket API looks to the daemon: entities, a token, the services called, and the
connections (`FakeHomeAssistant.connect` is a `Connect` of `homeassistant.client`). It sends the states compressed as
`subscribe_entities` does: all of them first (`"a"`), then changes (`"c"` with `"+"` and `"-"`) and removals (`"r"`).
"""

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from pydantic import SecretStr

from xtouch_daemon.config.sections import HomeAssistantConfig
from xtouch_daemon.homeassistant.client import HomeAssistant, HomeAssistantError, TransportClosed

TOKEN = "the-token"
URL = "http://ha.test:8123"


def hass_config(token: str = TOKEN, url: str = URL) -> HomeAssistantConfig:
    return HomeAssistantConfig(url=url, token=SecretStr(token))


class FakeHomeAssistant:
    """
    The entities (`set()`, `remove()`), the token it takes, the services called (`calls`: service, data, entity), and
    the connections. `refuse` connections fail before they start; a service in `failing` fails with that message.
    """

    def __init__(self, token: str = TOKEN) -> None:
        self.token = token
        self.entities: dict[str, tuple[str, dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []
        self.connections: list[FakeTransport] = []
        self.urls: list[str] = []
        self.refuse = 0
        self.failing: dict[str, str] = {}
        self.silent = False
        """Answers no requests (but the login): a Home Assistant that hangs."""
        self.closing = 0.0
        """Seconds a connection takes to close (the closing handshake of a real one)."""

    async def connect(self, url: str) -> FakeTransport:
        self.urls.append(url)
        if self.refuse:
            self.refuse -= 1
            raise HomeAssistantError(f"can't connect to {url}: Connection refused")
        transport = FakeTransport(self)
        self.connections.append(transport)
        return transport

    @property
    def connected(self) -> list[FakeTransport]:
        return [transport for transport in self.connections if not transport.closed]

    def set(self, entity_id: str, state: str, **attributes: Any) -> None:
        """An entity changes (or comes): the subscribers get the difference."""
        old = self.entities.get(entity_id)
        self.entities[entity_id] = (state, dict(attributes))
        if old is None:
            event: dict[str, Any] = {"a": {entity_id: {"s": state, "a": attributes, "c": "ctx", "lc": 1.0}}}
        else:
            plus: dict[str, Any] = {}
            if state != old[0]:
                plus["s"] = state
            changed = {key: value for key, value in attributes.items() if old[1].get(key) != value}
            if changed:
                plus["a"] = changed
            gone = [key for key in old[1] if key not in attributes]
            event = {"c": {entity_id: {"+": plus, **({"-": {"a": gone}} if gone else {})}}}
        self._publish(event)

    def remove(self, entity_id: str) -> None:
        del self.entities[entity_id]
        self._publish({"r": [entity_id]})

    def _publish(self, event: Mapping[str, Any]) -> None:
        for transport in self.connected:
            if transport.subscription is not None:
                transport.push({"id": transport.subscription, "type": "event", "event": event})

    def disconnect(self) -> None:
        """Every connection breaks."""
        for transport in self.connected:
            transport.push(None)

    def states(self) -> list[dict[str, Any]]:
        return [
            {"entity_id": entity_id, "state": state, "attributes": attributes, "context": {"id": "ctx"}}
            for entity_id, (state, attributes) in self.entities.items()
        ]


class FakeTransport:
    """One connection to the fake: what the daemon sends is answered at once, as Home Assistant would."""

    def __init__(self, home: FakeHomeAssistant) -> None:
        self.home = home
        self.inbox: asyncio.Queue[str | None] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.subscription: int | None = None
        self.push({"type": "auth_required", "ha_version": "2026.11.0"})

    def push(self, message: Mapping[str, Any] | None) -> None:
        self.inbox.put_nowait(None if message is None else json.dumps(message))

    async def send(self, message: str) -> None:
        if self.closed:
            raise TransportClosed("the connection ended")
        data = json.loads(message)
        self.sent.append(data)
        kind = data.get("type")
        identity = data.get("id")
        if kind == "auth":
            if data.get("access_token") == self.home.token:
                self.push({"type": "auth_ok", "ha_version": "2026.11.0"})
            else:
                self.push({"type": "auth_invalid", "message": "Invalid access token or password"})
            return
        if self.home.silent:
            return
        if kind == "subscribe_entities":
            self.subscription = identity
            self.push({"id": identity, "type": "result", "success": True, "result": None})
            added = {
                entity_id: {"s": state, "a": attributes, "c": "ctx", "lc": 1.0}
                for entity_id, (state, attributes) in self.home.entities.items()
            }
            self.push({"id": identity, "type": "event", "event": {"a": added}})
        elif kind == "call_service":
            service = f"{data['domain']}.{data['service']}"
            entity = data.get("target", {}).get("entity_id")
            self.home.calls.append((service, data.get("service_data", {}), entity))
            if service in self.home.failing:
                error = {"code": "service_validation_error", "message": self.home.failing[service]}
                self.push({"id": identity, "type": "result", "success": False, "error": error})
            else:
                self.push({"id": identity, "type": "result", "success": True, "result": {"context": {}}})
        elif kind == "get_states":
            self.push({"id": identity, "type": "result", "success": True, "result": self.home.states()})
        else:
            error = {"code": "unknown_command", "message": "Unknown command."}
            self.push({"id": identity, "type": "result", "success": False, "error": error})

    async def receive(self) -> str:
        if self.closed:
            raise TransportClosed("the connection ended")
        message = await self.inbox.get()
        if message is None:
            self.closed = True
            raise TransportClosed("the connection ended")
        return message

    async def close(self) -> None:
        if self.home.closing and not self.closed:
            await asyncio.sleep(self.home.closing)
        self.closed = True


async def connected(home: FakeHomeAssistant, config: HomeAssistantConfig | None = None) -> HomeAssistant:
    """A connection to the fake whose states are in."""
    hass = HomeAssistant(home.connect)
    hass.configure(config or hass_config(home.token))
    for _ in range(20):
        if hass.synced:
            break
        await asyncio.sleep(0)
    assert hass.synced
    return hass
