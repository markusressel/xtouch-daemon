"""
The participants from a plugin inside the voice chat client: the daemon serves a Unix socket
(`$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock`, mode 0600), a plugin connects and sends what it knows, one JSON object
per line, and gets the commands back the same way. The protocol is the same for every client, so the daemon needs no
library of any of them.

From the plugin, the whole state each time (like the live view: a plugin that sends 20 times a second while someone
talks needs nothing else):

    {"client": "mumble", "capabilities": ["volume", "mute", "levels"],
     "participants": [{"id": "12", "name": "Alice", "talking": true, "muted": false, "volume": 100, "level": 0.4}]}

`id` and `name` are needed, the rest is optional. To the plugin:

    {"set_volume": {"id": "12", "volume": 80}}
    {"set_muted": {"id": "12", "muted": true}}

One plugin at a time: a new connection replaces the one before. When the plugin goes, so do the participants.
"""

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Any

from xtouch_daemon.voip.provider import VOLUME_LIMIT, Capability, Participant, VoipProvider

_LOGGER = logging.getLogger(__name__)

LINE_LIMIT = 1024 * 1024
"""The longest line a plugin may send (about 5000 participants)."""


class ProtocolError(ValueError):
    """A line of the plugin that is not what the protocol says."""


def parse_state(line: bytes) -> tuple[tuple[Participant, ...], frozenset[Capability]]:
    """The participants and capabilities of a line of the plugin (`ProtocolError` for one that is not)."""
    try:
        data = json.loads(line)
    except ValueError as e:
        raise ProtocolError(f"no JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("participants"), list):
        raise ProtocolError("no object with participants")
    state: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]: JSON
    try:
        capabilities = frozenset(Capability(name) for name in state.get("capabilities", ()))
    except ValueError as e:
        raise ProtocolError(f"capabilities: {e}") from e
    participants: list[Participant] = []
    for item in state["participants"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str | int)
            or not isinstance(item.get("name"), str)
        ):
            raise ProtocolError(f"a participant without id or name: {item!r}")
        entry: dict[str, Any] = item  # pyright: ignore[reportUnknownVariableType]: JSON
        level = entry.get("level")
        try:
            volume = max(0, min(VOLUME_LIMIT, round(float(entry.get("volume", 100)))))
            level = None if level is None else max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError, OverflowError) as e:
            raise ProtocolError(f"the volume or level of {entry['name']}: {e}") from e
        participants.append(
            Participant(
                id=str(entry["id"]),
                name=entry["name"],
                talking=bool(entry.get("talking", False)),
                muted=bool(entry.get("muted", False)),
                volume=volume,
                level=level,
            )
        )
    return tuple(participants), capabilities


class BridgeProvider(VoipProvider):
    name = "bridge"

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.client: str | None = None
        """What the plugin calls its voice chat client, e.g. "mumble"."""
        self._writer: asyncio.StreamWriter | None = None

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
            _LOGGER.info("Another voice chat plugin connected, dropping the one before")
            self._writer.close()
        self._writer = writer
        try:
            with contextlib.suppress(ConnectionError, ValueError):
                while line := await reader.readline():
                    if writer is not self._writer:
                        break
                    self._receive(line)
        finally:
            writer.close()
            if writer is self._writer:
                self._writer = None
                self.client = None
                self.capabilities = frozenset()
                self.update((), connected=False)
                _LOGGER.info("The voice chat plugin is gone")

    def _receive(self, line: bytes) -> None:
        if not line.strip():
            return
        try:
            participants, capabilities = parse_state(line)
        except ProtocolError as e:
            _LOGGER.warning(f"Ignoring a line of the voice chat plugin: {e}")
            return
        if not self.connected:
            self.client = str(json.loads(line).get("client") or "a client")
            _LOGGER.info(f"Voice chat plugin connected ({self.client})")
        self.capabilities = capabilities
        self.update(participants)

    def _send(self, message: dict[str, Any]) -> None:
        if self._writer is not None:
            self._writer.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")

    async def set_volume(self, participant_id: str, volume: int) -> None:
        self._send({"set_volume": {"id": participant_id, "volume": volume}})

    async def set_muted(self, participant_id: str, muted: bool) -> None:
        self._send({"set_muted": {"id": participant_id, "muted": muted}})
