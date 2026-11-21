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

One plugin at a time: while one is connected, another one gets `{"error":"another plugin is connected"}` (`Refusal`)
and is closed (two clients with the plugin enabled would otherwise take the socket from each other). When the plugin
goes, so do the participants.
"""

import asyncio
import contextlib
import json
import logging
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
from xtouch_daemon.voip.provider import VoipProvider

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


class BridgeProvider(VoipProvider):
    name = "bridge"

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self._writer: asyncio.StreamWriter | None = None
        self._refused = False
        """Whether a second plugin was refused while this one is connected: said once, not at every try."""

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
            if self._writer is not None:
                self._writer.close()
            self.path.unlink(missing_ok=True)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._writer is not None:
            # the one that is there stays: two clients with the plugin would take the socket from each other forever
            if not self._refused:
                _LOGGER.warning(
                    "Refusing another voice chat plugin while one is connected: is the plugin enabled in two clients?"
                )
                self._refused = True
            with contextlib.suppress(ConnectionError):
                writer.write(encode(Refusal(error="another plugin is connected")))
            writer.close()
            return
        self._writer = writer
        self._send(Greeting(daemon="xtouch-daemon", version=__version__, protocol=PROTOCOL))
        try:
            with contextlib.suppress(ConnectionError, ValueError):
                while line := await reader.readline():
                    self._receive(line)
        finally:
            writer.close()
            self._writer = None
            self._refused = False
            self.client = None
            self.channel = None
            self.capabilities = frozenset()
            self.update((), connected=False)
            _LOGGER.info("The voice chat plugin is gone")

    def _receive(self, line: bytes) -> None:
        if not line.strip():
            return
        try:
            state = parse_state(line)
        except ProtocolError as e:
            _LOGGER.warning(f"Ignoring a line of the voice chat plugin: {e}")
            return
        if not self.connected:
            self.client = state.client or "a client"
            _LOGGER.info(f"Voice chat plugin connected ({self.client})")
        self.channel = state.channel
        self.capabilities = frozenset(state.capabilities)
        self.update(tuple(each.participant() for each in state.participants))

    def _send(self, message: Message) -> None:
        if self._writer is not None:
            self._writer.write(encode(message))

    async def set_volume(self, participant_id: str, volume: int) -> None:
        self._send(SetVolume(set_volume=VolumeChange(id=participant_id, volume=volume)))

    async def set_muted(self, participant_id: str, muted: bool) -> None:
        self._send(SetMuted(set_muted=MuteChange(id=participant_id, muted=muted)))
