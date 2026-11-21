"""
The participants from a plugin inside the voice chat client: the daemon serves a Unix socket
(`$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock`, mode 0600), a plugin connects and sends what it knows, one JSON object
per line, and gets the commands back the same way. The protocol is the same for every client, so the daemon needs no
library of any of them. Its messages are the models in `protocol.py`, which say what each key means.

The daemon greets a plugin that connects with its protocol version (`Greeting`):

    {"daemon":"xtouch-daemon","version":"0.1.0","protocol":1}

From the plugin, the whole state each time (`PluginState`, like the live view: a plugin that sends 20 times a second
while someone talks needs nothing else):

    {"protocol": 1, "client": "mumble", "channel": "Lobby", "capabilities": ["volume", "mute", "levels"],
     "participants": [{"id": "12", "name": "Alice", "talking": true, "muted": false, "volume": 100, "level": 0.4,
                       "pre_fader_level": 0.8}]}

To the plugin (`SetVolume`, `SetMuted`):

    {"set_volume":{"id":"12","volume":80}}
    {"set_muted":{"id":"12","muted":true}}

A new protocol version means lines that an older side would get wrong; new optional keys don't need one, and both
sides ignore keys they don't know. The daemon ignores the lines of a protocol it does not know (and says so), and the
lines that are not the protocol.

One plugin per client, several at once: the client is the `client` of the first state line (`a client` without one).
While a plugin of that client is connected, a new one gets `{"error":"another mumble plugin is connected"}`
(`Refusal`) and is closed: two instances of a client with the plugin enabled would otherwise take the socket from each
other. Before its first state line a connection counts for nothing. The participants of all plugins are together, with
the client in front of their ids (`mumble:12`); a command goes to the plugin of the participant, with the id there.
When a plugin goes, so do its participants.
"""

import asyncio
import contextlib
import dataclasses
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from xtouch_daemon import __version__
from xtouch_daemon.voip.protocol import (
    PROTOCOL,
    Greeting,
    Message,
    MuteChange,
    PluginState,
    Refusal,
    SetMuted,
    SetVolume,
    VolumeChange,
    encode,
)
from xtouch_daemon.voip.provider import Capability, Client, Participant, VoipProvider

__all__ = ["LINE_LIMIT", "PROTOCOL", "BridgeProvider", "ProtocolError", "parse_state"]

_LOGGER = logging.getLogger(__name__)

LINE_LIMIT = 1024 * 1024
"""The longest line a plugin may send (about 5000 participants)."""


class ProtocolError(ValueError):
    """A line of the plugin that is not what the protocol says."""


def parse_state(line: bytes) -> PluginState:
    """The state in a line of the plugin (`ProtocolError` for one that is not, see `protocol.PluginState`)."""
    try:
        data = json.loads(line)
    except ValueError as e:
        raise ProtocolError(f"no JSON: {e}") from e
    if not isinstance(data, dict):
        raise ProtocolError("no object with participants")
    state: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]: JSON
    # before the rest: the lines of another version may look different altogether
    protocol = state.get("protocol", PROTOCOL)
    if protocol != PROTOCOL and isinstance(state.get("participants"), list):
        raise ProtocolError(f"protocol {protocol!r}, this daemon speaks {PROTOCOL}: update the plugin or the daemon")
    try:
        return PluginState.model_validate(state)
    except ValidationError as e:
        raise ProtocolError(_problem(e, state)) from e


def _problem(error: ValidationError, state: dict[str, Any]) -> str:
    """What is wrong with a line, the first problem in the order of its keys."""
    errors = error.errors()
    if any(each["loc"] == ("participants",) for each in errors):
        return "no object with participants"
    first = errors[0]
    match first["loc"]:
        case ("participants", int(index), *rest):
            item = state["participants"][index]
            if not rest or rest[0] in ("id", "name"):
                return f"a participant without id or name: {item!r}"
            cause = first.get("ctx", {}).get("error", first["msg"])
            return f"the volume or level of {item['name']}: {cause}"
        case (key, *_):
            return f"{key}: {first['msg']}"
        case _:  # pragma: no cover: a model has keys
            return first["msg"]


@dataclass(eq=False)
class _Plugin:
    """A connection of a plugin: what it sent last, with the ids of the client."""

    writer: asyncio.StreamWriter
    client: str | None = None
    """The type of the client, from the first state line (`a client` if it tells none); None before it."""
    channel: str | None = None
    capabilities: frozenset[Capability] = frozenset()
    participants: tuple[Participant, ...] = ()


class BridgeProvider(VoipProvider):
    """
    The participants of the plugins of voice chat clients, one plugin per client (see the module): the ids of the
    participants have their client in front, e.g. `mumble:12`.
    """

    name = "bridge"

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self._connections: set[_Plugin] = set()
        """Every connection, also those that sent no state yet."""
        self._plugins: list[_Plugin] = []
        """The plugins that sent their state, one per client, in the order they came."""
        self._routes: dict[str, tuple[_Plugin, str]] = {}
        """The plugin of each participant and their id there, by their id in the daemon."""
        self._refused: set[str] = set()
        """The clients of which another plugin was refused: said once, not at every try."""

    async def run(self) -> None:
        """Serves until cancelled. A socket that can't be made is logged: the daemon works without it."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.unlink(missing_ok=True)
            server = await asyncio.start_unix_server(self._serve, self.path, limit=LINE_LIMIT)
            self.path.chmod(0o600)
        except OSError as e:
            _LOGGER.error(f"No voice chat participants, can't serve {self.path}: {e}")
            return
        _LOGGER.info(f"Waiting for a voice chat plugin on {self.path}")
        try:
            await asyncio.Future[None]()
        finally:
            server.close()
            for plugin in self._connections:
                plugin.writer.close()
            self.path.unlink(missing_ok=True)

    @property
    def clients(self) -> tuple[Client, ...]:
        return tuple(Client(plugin.client or "", plugin.channel, plugin.capabilities) for plugin in self._plugins)

    def capabilities_of(self, participant_id: str) -> frozenset[Capability]:
        route = self._routes.get(participant_id)
        return frozenset() if route is None else route[0].capabilities

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        plugin = _Plugin(writer)
        self._connections.add(plugin)
        writer.write(encode(Greeting(daemon="xtouch-daemon", version=__version__, protocol=PROTOCOL)))
        try:
            with contextlib.suppress(ConnectionError, ValueError):
                while line := await reader.readline():
                    if not self._receive(plugin, line):
                        break
        finally:
            writer.close()
            self._connections.discard(plugin)
            if plugin in self._plugins:
                self._plugins.remove(plugin)
                self._refused.discard(plugin.client or "")
                self._publish()
                _LOGGER.info(f"The voice chat plugin of {plugin.client} is gone")

    def _receive(self, plugin: _Plugin, line: bytes) -> bool:
        """Takes a line of a plugin; False if the plugin is refused."""
        if not line.strip():
            return True
        try:
            state = parse_state(line)
        except ProtocolError as e:
            _LOGGER.warning(f"Ignoring a line of the voice chat plugin: {e}")
            return True
        if plugin.client is None:
            client = state.client or "a client"
            if any(other.client == client for other in self._plugins):
                self._refuse(plugin, client)
                return False
            plugin.client = client
            self._plugins.append(plugin)
            _LOGGER.info(f"Voice chat plugin connected ({client})")
        plugin.channel = state.channel
        plugin.capabilities = frozenset(state.capabilities)
        plugin.participants = tuple(each.participant() for each in state.participants)
        self._publish()
        return True

    def _refuse(self, plugin: _Plugin, client: str) -> None:
        # the one that is there stays: two clients with the plugin would take the socket from each other forever
        if client not in self._refused:
            _LOGGER.warning(
                f"Refusing another voice chat plugin of {client} while one is connected: is the plugin enabled in "
                "two of them?"
            )
            self._refused.add(client)
        error = "another plugin is connected" if client == "a client" else f"another {client} plugin is connected"
        with contextlib.suppress(ConnectionError):
            plugin.writer.write(encode(Refusal(error=error)))

    def _publish(self) -> None:
        """The participants of all plugins, with their client in front of their ids."""
        plugins = self._plugins
        self._routes = {
            f"{plugin.client}:{each.id}": (plugin, each.id) for plugin in plugins for each in plugin.participants
        }
        self.client = ", ".join(plugin.client or "" for plugin in plugins) or None
        self.channel = next((plugin.channel for plugin in plugins if plugin.channel), None)
        self.capabilities = frozenset(capability for plugin in plugins for capability in plugin.capabilities)
        self.update(
            tuple(
                dataclasses.replace(each, id=f"{plugin.client}:{each.id}")
                for plugin in plugins
                for each in plugin.participants
            ),
            connected=bool(plugins),
        )

    def _send(self, participant_id: str, message: Callable[[str], Message]) -> None:
        """Sends a command for a participant to their plugin, with their id there; none for someone unknown."""
        route = self._routes.get(participant_id)
        if route is not None:
            plugin, bare_id = route
            plugin.writer.write(encode(message(bare_id)))

    async def set_volume(self, participant_id: str, volume: int) -> None:
        self._send(participant_id, lambda id: SetVolume(set_volume=VolumeChange(id=id, volume=volume)))

    async def set_muted(self, participant_id: str, muted: bool) -> None:
        self._send(participant_id, lambda id: SetMuted(set_muted=MuteChange(id=id, muted=muted)))
