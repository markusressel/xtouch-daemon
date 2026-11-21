"""
The connection to the WebSocket API of Home Assistant (`[homeassistant]`), for the parts bound to its entities: it logs
in with the long-lived token, follows the states of all entities (`subscribe_entities`, as the frontend of Home
Assistant does), and calls services. One connection serves the daemon; it connects again after it broke, waiting
longer each time (RECONNECT_DELAYS), but not after Home Assistant refused the token: that takes another token.

While it is not connected the entities have no state (`state()` is None): the parts show them unknown. The transport
is injectable (`Connect`): the tests use one in memory (`tests/support/homeassistant.py`).

`fetch_entities()` connects once, for the entities Home Assistant has: the suggestions of the GUI, and a check of the
address and the token.
"""

import asyncio
import contextlib
import itertools
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from websockets.asyncio.client import connect as websocket_client
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.sections import HomeAssistantConfig
from xtouch_daemon.homeassistant.states import EntityState, apply_event, from_state

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAYS = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
"""Seconds before each attempt to connect again after the connection broke; the last one repeats."""
REQUEST_TIMEOUT = 10.0
"""Seconds Home Assistant may take to answer a request (a service call, the states)."""
MAX_MESSAGE = 64 * 1024 * 1024
"""The largest message the daemon takes, in bytes: the states of every entity come in one."""


class HomeAssistantError(Exception):
    """Home Assistant could not be reached, refused a request, or the connection ended."""


class TokenRefused(HomeAssistantError):
    """Home Assistant refused the token: the daemon does not try again until the configuration changes."""


class TransportClosed(HomeAssistantError):
    """The connection ended."""


class Transport(Protocol):
    """A connection to the WebSocket API: text messages both ways."""

    async def send(self, message: str) -> None:
        """Sends a message; TransportClosed when the connection ended."""
        ...

    async def receive(self) -> str:
        """The next message; TransportClosed when the connection ended."""
        ...

    async def close(self) -> None: ...


type Connect = Callable[[str], Awaitable[Transport]]
"""Connects to the WebSocket API at an address (`ws://.../api/websocket`); HomeAssistantError if it can't."""


class _WebSocket:
    """A `Transport` over the `websockets` library."""

    def __init__(self, connection: Any):
        self._connection = connection

    async def send(self, message: str) -> None:
        try:
            await self._connection.send(message)
        except ConnectionClosed as e:
            raise TransportClosed(f"the connection ended ({e})") from e

    async def receive(self) -> str:
        try:
            message = await self._connection.recv()
        except ConnectionClosed as e:
            raise TransportClosed(f"the connection ended ({e})") from e
        return message.decode() if isinstance(message, bytes) else str(message)

    async def close(self) -> None:
        await self._connection.close()


async def websocket_connect(url: str) -> Transport:
    """Connects to the WebSocket API at `url` with the `websockets` library."""
    try:
        connection = await websocket_client(url, max_size=MAX_MESSAGE, open_timeout=REQUEST_TIMEOUT)
    except (OSError, TimeoutError, InvalidURI, InvalidHandshake) as e:
        raise HomeAssistantError(f"can't connect to {url}: {e}") from e
    return _WebSocket(connection)


async def _receive(transport: Transport) -> dict[str, Any]:
    text = await transport.receive()
    try:
        message = json.loads(text)
    except ValueError as e:
        raise HomeAssistantError(f"Home Assistant sent something that is no JSON: {text[:80]!r}") from e
    if not isinstance(message, dict):
        raise HomeAssistantError(f"Home Assistant sent something unexpected: {text[:80]!r}")
    return cast(dict[str, Any], message)


async def authenticate(transport: Transport, token: str) -> str:
    """Logs in with the token; the version of Home Assistant. TokenRefused for a token it does not take."""
    hello = await _receive(transport)
    if hello.get("type") != "auth_required":
        raise HomeAssistantError(f"this is no WebSocket API of Home Assistant (it sent {hello.get('type')!r})")
    await transport.send(json.dumps({"type": "auth", "access_token": token}))
    answer = await _receive(transport)
    if answer.get("type") == "auth_invalid":
        raise TokenRefused(f"Home Assistant refused the token ({answer.get('message', 'no reason')})")
    if answer.get("type") != "auth_ok":
        raise HomeAssistantError(f"Home Assistant did not log in (it sent {answer.get('type')!r})")
    return str(answer.get("ha_version", ""))


@dataclass(frozen=True)
class Fetched:
    """What `fetch()` found: the version of Home Assistant, and its entities by id."""

    version: str
    entities: tuple[EntityState, ...]


async def fetch_entities(config: HomeAssistantConfig, connect: Connect = websocket_connect) -> list[EntityState]:
    """
    The entities Home Assistant has now, by id: connects, logs in, asks, and closes again. HomeAssistantError (with
    why) if it can't; ConfigError for a token it can't read.
    """
    return list((await fetch(config, connect)).entities)


async def fetch(config: HomeAssistantConfig, connect: Connect = websocket_connect) -> Fetched:
    """`fetch_entities()` with the version of Home Assistant: the test of the settings in the GUI."""
    token = config.resolve_token()
    transport = await connect(config.websocket_url)
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            version = await authenticate(transport, token)
            await transport.send(json.dumps({"id": 1, "type": "get_states"}))
            while True:
                message = await _receive(transport)
                if message.get("id") == 1 and message.get("type") == "result":
                    entities = sorted(_states_of(message), key=lambda entity: entity.entity_id)
                    return Fetched(version, tuple(entities))
    except TimeoutError:
        raise HomeAssistantError(f"Home Assistant did not answer within {REQUEST_TIMEOUT:g} s") from None
    finally:
        with contextlib.suppress(HomeAssistantError, OSError):
            await transport.close()


def _states_of(message: Mapping[str, Any]) -> list[EntityState]:
    _check(message)
    return [from_state(item) for item in cast(list[Mapping[str, Any]], message.get("result") or [])]


def _check(result: Mapping[str, Any]) -> None:
    """HomeAssistantError for a result that says it failed, with Home Assistant's words."""
    if not result.get("success", False):
        error = cast(Mapping[str, Any], result.get("error") or {})
        raise HomeAssistantError(str(error.get("message") or error.get("code") or "it failed"))


type Listener = Callable[[], None]


class HomeAssistant:
    """
    The connection of the daemon to Home Assistant. `configure()` gives it the section to connect with (None: no
    connection); `watch()` calls back when an entity changed, and when the connection came or went. `on_change` is
    called when the connection changed: for the live view.
    """

    def __init__(self, connect: Connect = websocket_connect):
        self._connect = connect
        self.config: HomeAssistantConfig | None = None
        self.states: dict[str, EntityState] = {}
        """The entities by id, while connected."""
        self.connected = False
        """Logged in."""
        self.synced = False
        """Connected, and the states of all entities are in."""
        self.ever_synced = False
        """Whether the states were in at some time: from then on, an entity without a state is unavailable."""
        self.error: str | None = None
        """Why the last attempt to connect failed or the connection ended; None while connected and before that."""
        self.version: str | None = None
        """The version of Home Assistant, once connected."""
        self.on_change: Callable[[], None] = lambda: None
        self._listeners: dict[str, list[Listener]] = {}
        self._warned: set[str] = set()
        """The entities the log said Home Assistant does not have (once each, per connection)."""
        self._task: asyncio.Task[None] | None = None
        self._ending: set[asyncio.Task[None]] = set()
        """The connections of an earlier configuration that are ending (`close()` waits for them)."""
        self._transport: Transport | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._subscription: int | None = None

    # -- the connection -------------------------------------------------------------------------------------------

    def configure(self, config: HomeAssistantConfig | None) -> None:
        """Connects with `config`, None for no connection; the same section as before keeps the connection."""
        if config == self.config and (config is None or self._task is not None):
            return
        self.config = config
        self._stop()
        if config is not None:
            self._task = asyncio.create_task(self._run(config), name="homeassistant")
        self.on_change()

    def _stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._ending.add(self._task)
            self._task.add_done_callback(self._ending.discard)
            self._task = None

    async def close(self) -> None:
        """Ends the connection, and waits for its end."""
        self.config = None
        self._stop()
        await asyncio.gather(*self._ending, return_exceptions=True)

    async def _run(self, config: HomeAssistantConfig) -> None:
        try:
            token = config.resolve_token()
        except ConfigError as e:
            self.error = str(e)
            _LOGGER.error(f"Home Assistant: {e}")
            self.on_change()
            return
        attempt = 0
        delay = RECONNECT_DELAYS[0]
        while True:
            try:
                await self._session(config, token)
            except TokenRefused as e:
                self.error = str(e)
                _LOGGER.error(f"{e}: create a new long-lived access token, put it into [homeassistant] and reload")
                return
            except HomeAssistantError as e:
                if self.connected:
                    # it was there: the first attempt comes soon
                    attempt = 0
                self.error = str(e)
                delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
                log = _LOGGER.warning if attempt == 0 else _LOGGER.debug
                log(f"Home Assistant at {config.url}: {e}, connecting again in {delay:g} s")
                attempt += 1
            finally:
                self._ended()
            await asyncio.sleep(delay)

    async def _session(self, config: HomeAssistantConfig, token: str) -> None:
        transport = await self._connect(config.websocket_url)
        try:
            self.version = await authenticate(transport, token)
            self._transport = transport
            self.connected = True
            self.error = None
            _LOGGER.info(f"Connected to Home Assistant {self.version} at {config.url}")
            self.on_change()
            self._subscription = next(self._ids)
            await transport.send(json.dumps({"id": self._subscription, "type": "subscribe_entities"}))
            while True:
                self._handle(await _receive(transport))
        finally:
            with contextlib.suppress(HomeAssistantError, OSError):
                await transport.close()

    def _ended(self) -> None:
        """The connection ended (or never came): the entities have no state now, the requests no answer."""
        was = self.connected or bool(self.states)
        self._transport = None
        self.connected = self.synced = False
        self._subscription = None
        self._warned.clear()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(HomeAssistantError("the connection to Home Assistant ended"))
        self._pending.clear()
        changed = set(self.states)
        self.states.clear()
        self.on_change()
        if was:
            self._notify(changed | set(self._listeners))

    def _handle(self, message: Mapping[str, Any]) -> None:
        kind = message.get("type")
        identity = message.get("id")
        if kind == "result" and isinstance(identity, int):
            if identity == self._subscription:
                _check(message)
            elif (future := self._pending.pop(identity, None)) is not None and not future.done():
                future.set_result(dict(message))
        elif kind == "event" and identity == self._subscription:
            changed = apply_event(self.states, cast(Mapping[str, Any], message.get("event") or {}))
            if not self.synced:
                self.synced = self.ever_synced = True
                self.on_change()
                changed |= set(self._listeners)
                for entity_id in self._listeners:
                    self._warn_missing(entity_id)
            self._notify(changed)

    def _warn_missing(self, entity_id: str) -> None:
        if self.synced and entity_id not in self.states and entity_id not in self._warned:
            self._warned.add(entity_id)
            _LOGGER.warning(f"Home Assistant has no entity {entity_id}: its parts show nothing")

    def _notify(self, entity_ids: set[str]) -> None:
        for entity_id in entity_ids:
            for listener in list(self._listeners.get(entity_id, ())):
                listener()

    # -- the entities ---------------------------------------------------------------------------------------------

    def watch(self, entity_id: str, listener: Listener) -> None:
        """Calls `listener` when the entity changed, and when the connection came or went."""
        self._listeners.setdefault(entity_id, []).append(listener)
        self._warn_missing(entity_id)

    def unwatch(self, entity_id: str, listener: Listener) -> None:
        listeners = self._listeners.get(entity_id, [])
        if listener in listeners:
            listeners.remove(listener)
        if not listeners:
            self._listeners.pop(entity_id, None)

    @property
    def watched(self) -> int:
        """How many entities parts show or set."""
        return len(self._listeners)

    def state(self, entity_id: str) -> EntityState | None:
        """The entity as Home Assistant has it now; None while not connected, or for an entity it does not have."""
        return self.states.get(entity_id)

    def entities(self) -> list[EntityState]:
        """The entities Home Assistant has, by id (none while not connected)."""
        return sorted(self.states.values(), key=lambda entity: entity.entity_id)

    # -- requests -------------------------------------------------------------------------------------------------

    async def _request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        transport = self._transport
        if transport is None:
            raise HomeAssistantError("not connected to Home Assistant")
        identity = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[identity] = future
        try:
            await transport.send(json.dumps({"id": identity, **message}))
            async with asyncio.timeout(REQUEST_TIMEOUT):
                result = await future
        except TimeoutError:
            raise HomeAssistantError(f"Home Assistant did not answer within {REQUEST_TIMEOUT:g} s") from None
        finally:
            self._pending.pop(identity, None)
        _check(result)
        return result

    async def call_service(self, service: str, data: Mapping[str, Any] | None, entity_id: str | None) -> None:
        """Calls a service (`light.turn_on`), on an entity; HomeAssistantError with why if it failed."""
        domain, _, name = service.partition(".")
        message: dict[str, Any] = {"type": "call_service", "domain": domain, "service": name}
        if data:
            message["service_data"] = dict(data)
        if entity_id is not None:
            message["target"] = {"entity_id": entity_id}
        await self._request(message)

    async def get_states(self) -> list[EntityState]:
        """The entities as Home Assistant has them now, asked for (`entities()` has those it sent)."""
        return sorted(_states_of(await self._request({"type": "get_states"})), key=lambda entity: entity.entity_id)


def describe_entity(entity: EntityState) -> str:
    """An entity for people: its name and its id, e.g. `Desk lamp (light.desk)`."""
    return f"{entity.name} ({entity.entity_id})" if entity.name != entity.entity_id else entity.entity_id
