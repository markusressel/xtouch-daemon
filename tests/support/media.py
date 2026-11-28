"""A fake of the media players of the session (`MediaPlayers`), for the tests of the knob and the slots."""

import asyncio
from collections.abc import Callable

from xtouch_daemon.audio.media import MediaCommandError, Player


class FakePlayers:
    def __init__(self, *players: Player) -> None:
        self.players = players
        self.paused: frozenset[Player] = frozenset()
        self.on_change: Callable[[], None] | None = None
        self.calls: list[tuple[str, object]] = []
        self.progresses: dict[str, float | None] = {}
        self.failing = False
        self.positions: list[float | None] = []
        self.playback = "Playing"
        self.silent = False
        """Whether the player does not tell its status."""
        self.gate: asyncio.Event | None = None

    async def run(self) -> None:
        await asyncio.Event().wait()

    async def play_pause(self, player: Player) -> None:
        self.calls.append(("play_pause", player.name))
        self.playback = "Paused" if self.playback == "Playing" else "Playing"

    async def seek(self, player: Player, seconds: float) -> None:
        self.calls.append(("seek", seconds))
        if self.gate is not None:
            await self.gate.wait()

    async def position(self, player: Player) -> float | None:
        return self.positions.pop(0) if self.positions else None

    async def status(self, player: Player) -> str:
        if self.silent:
            raise MediaCommandError("gone")
        return self.playback

    async def progress(self, player: Player) -> float | None:
        if self.failing:
            raise MediaCommandError("gone")
        return self.progresses.get(player.name)
