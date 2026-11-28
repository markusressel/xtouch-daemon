"""
The media players of the session (MPRIS over D-Bus: Spotify, browsers, mpv with mpv-mpris, ...): which application plays
through which player, and play/pause, seek and the position of the track, for `encoder = "media"`.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from dbus_fast import BusType, DBusError, Message, MessageType
from dbus_fast.aio import MessageBus

from xtouch_daemon.audio.backend import AudioCommandError
from xtouch_daemon.audio.model import Stream

_LOGGER = logging.getLogger(__name__)

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
DBUS = {"destination": "org.freedesktop.DBus", "path": "/org/freedesktop/DBus", "interface": "org.freedesktop.DBus"}
LIST_INTERVAL = 2.0
"""How often the list of players is read again (they come and go with their applications)."""
RECONNECT_DELAY = 5.0


class MediaCommandError(AudioCommandError):
    """A command a player did not carry out, e.g. because it ended meanwhile."""


@dataclass(frozen=True)
class Player:
    bus_name: str
    """E.g. `org.mpris.MediaPlayer2.brave.instance2197156`."""
    pid: int | None
    """The process that owns the name, None if the bus does not tell."""

    @property
    def name(self) -> str:
        """The name of the player, e.g. `brave` (without the instance)."""
        return self.bus_name.removeprefix(MPRIS_PREFIX).split(".instance")[0].lower()


def parent_pid(pid: int) -> int | None:
    """The parent of a process, None if it is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # the name in parentheses may contain anything: the fields after it are fixed
    return int(stat.rsplit(")", 1)[1].split()[1])


def ancestors(pid: int, parent: Callable[[int], int | None] = parent_pid) -> list[int]:
    """The process and its parents, up to the first one."""
    chain = [pid]
    while (pid := parent(pid) or 0) > 1 and pid not in chain:
        chain.append(pid)
    return chain


def player_of(
    players: Iterable[Player], streams: Iterable[Stream], parent: Callable[[int], int | None] = parent_pid
) -> Player | None:
    """
    The player of the streams: the one of a process that plays them or one of its parents (browsers play from a
    child process), else one named like the application. Playing streams first.
    """
    players = list(players)
    ordered = sorted(streams, key=lambda stream: not stream.playing)
    for stream in ordered:
        if stream.pid is not None:
            chain = ancestors(stream.pid, parent)
            for player in players:
                if player.pid in chain:
                    return player
    for stream in ordered:
        names = {stream.app.lower(), stream.binary.lower()}
        for player in players:
            if player.name in names:
                return player
    return None


class MediaPlayers(Protocol):
    """The players of the session. `MprisPlayers` is the real one, the tests use a fake."""

    players: tuple[Player, ...]
    paused: frozenset[Player]
    """The players that are paused, as of the last time the players were listed."""
    on_change: Callable[[], None] | None
    """Called when `players` or `paused` changed, e.g. to step the slots."""

    async def run(self) -> None: ...

    async def play_pause(self, player: Player) -> None: ...

    async def seek(self, player: Player, seconds: float) -> None: ...

    async def progress(self, player: Player) -> float | None:
        """How far the track is, 0..1; None without a position or a length (e.g. a live stream)."""
        ...

    async def position(self, player: Player) -> float | None:
        """Where the track is, in seconds; None if the player does not tell."""
        ...

    async def status(self, player: Player) -> str:
        """`Playing`, `Paused` or `Stopped`."""
        ...


type BusFactory = Callable[[], Awaitable[Any]]


async def _session_bus() -> MessageBus:
    return await MessageBus(bus_type=BusType.SESSION).connect()


class MprisPlayers:
    def __init__(self, connect: BusFactory = _session_bus, interval: float = LIST_INTERVAL):
        self._connect = connect
        self._interval = interval
        self._bus: Any = None
        self.players: tuple[Player, ...] = ()
        self.paused: frozenset[Player] = frozenset()
        self.on_change: Callable[[], None] | None = None

    def _show(self, players: tuple[Player, ...], paused: frozenset[Player]) -> None:
        if (players, paused) != (self.players, self.paused):
            self.players, self.paused = players, paused
            if self.on_change is not None:
                self.on_change()

    async def run(self) -> None:
        """Keeps `players` up to date, connecting again after a lost connection."""
        reported = False
        while True:
            try:
                self._bus = await self._connect()
                reported = False
                while True:
                    players = await self._list()
                    self._show(players, await self._paused(players))
                    await asyncio.sleep(self._interval)
            except (DBusError, OSError, EOFError) as e:
                if not reported:
                    _LOGGER.warning(f"No media players: the session bus is not reachable ({e})")
                    reported = True
            finally:
                if self._bus is not None:
                    self._bus.disconnect()
                self._bus = None
                self._show((), frozenset())
            await asyncio.sleep(RECONNECT_DELAY)

    async def _call(self, **message: Any) -> list[Any]:
        if self._bus is None:
            raise MediaCommandError("not connected to the session bus")
        reply = await self._bus.call(Message(**message))
        if reply.message_type == MessageType.ERROR:
            raise MediaCommandError(f"{message['member']}: {reply.error_name} {' '.join(map(str, reply.body))}")
        return reply.body

    async def _list(self) -> tuple[Player, ...]:
        (names,) = await self._call(**DBUS, member="ListNames")
        players: list[Player] = []
        for name in sorted(name for name in names if name.startswith(MPRIS_PREFIX)):
            try:
                (pid,) = await self._call(**DBUS, member="GetConnectionUnixProcessID", signature="s", body=[name])
            except MediaCommandError:
                # gone meanwhile, or the bus does not know
                pid = None
            players.append(Player(name, pid))
        return tuple(players)

    async def _paused(self, players: tuple[Player, ...]) -> frozenset[Player]:
        paused: set[Player] = set()
        for player in players:
            try:
                if await self.status(player) == "Paused":
                    paused.add(player)
            except MediaCommandError:
                # gone meanwhile, or it does not tell
                pass
        return frozenset(paused)

    def _player_call(self, player: Player, member: str, signature: str = "", body: list[Any] | None = None) -> Any:
        return self._call(
            destination=player.bus_name,
            path=MPRIS_PATH,
            interface=PLAYER_INTERFACE,
            member=member,
            signature=signature,
            body=body or [],
        )

    async def _property(self, player: Player, name: str) -> Any:
        (value,) = await self._call(
            destination=player.bus_name,
            path=MPRIS_PATH,
            interface="org.freedesktop.DBus.Properties",
            member="Get",
            signature="ss",
            body=[PLAYER_INTERFACE, name],
        )
        return value.value

    async def play_pause(self, player: Player) -> None:
        await self._player_call(player, "PlayPause")

    async def seek(self, player: Player, seconds: float) -> None:
        await self._player_call(player, "Seek", "x", [round(seconds * 1_000_000)])

    async def progress(self, player: Player) -> float | None:
        metadata = await self._property(player, "Metadata")
        length = metadata.get("mpris:length")
        if length is None or not length.value:
            return None
        position = await self._property(player, "Position")
        return max(0.0, min(1.0, position / length.value))

    async def position(self, player: Player) -> float | None:
        try:
            microseconds = await self._property(player, "Position")
        except MediaCommandError:
            # players without a position answer with an error
            return None
        return max(0.0, microseconds / 1_000_000)

    async def status(self, player: Player) -> str:
        return str(await self._property(player, "PlaybackStatus"))
