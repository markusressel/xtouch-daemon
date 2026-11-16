"""
A sound server for the tests: a backend that records commands, and the devices and streams of its states.
"""

import asyncio
from collections.abc import Callable

from xtouch_daemon.audio.backend import AudioCommandError
from xtouch_daemon.audio.model import AudioState, Device, Direction, Stream


class FakeBackend:
    """Records every command. Names in `failing` raise AudioCommandError; `gate` holds commands until it is set."""

    def __init__(self, states: tuple[AudioState, ...] = ()):
        self.calls: list[tuple[object, ...]] = []
        self.failing: set[str] = set()
        self.gate: asyncio.Event | None = None
        self.on_state: Callable[[AudioState], None] | None = None
        self._states = states

    async def run(self, on_state: Callable[[AudioState], None]) -> None:
        self.on_state = on_state
        for state in self._states:
            on_state(state)
        await asyncio.Event().wait()

    async def _command(self, name: str, *args: object) -> None:
        self.calls.append((name, *args))
        if self.gate is not None:
            await self.gate.wait()
        if name in self.failing:
            raise AudioCommandError(f"{name} failed")

    async def set_device_volume(self, direction: Direction, name: str, percent: int) -> None:
        await self._command("set_device_volume", direction, name, percent)

    async def set_device_mute(self, direction: Direction, name: str, muted: bool) -> None:
        await self._command("set_device_mute", direction, name, muted)

    async def set_device_balance(self, direction: Direction, name: str, balance: float) -> None:
        await self._command("set_device_balance", direction, name, balance)

    async def set_default(self, direction: Direction, name: str) -> None:
        await self._command("set_default", direction, name)

    async def set_stream_balance(self, index: int, balance: float) -> None:
        await self._command("set_stream_balance", index, balance)

    async def set_card_profile(self, card: str, profile: str) -> None:
        await self._command("set_card_profile", card, profile)

    async def set_stream_volume(self, index: int, percent: int) -> None:
        await self._command("set_stream_volume", index, percent)

    async def set_stream_mute(self, index: int, muted: bool) -> None:
        await self._command("set_stream_mute", index, muted)


def output(
    name: str = "speaker",
    volume: int = 50,
    muted: bool = False,
    running: bool = False,
    card: str | None = None,
    balance: float | None = 0.0,
) -> Device:
    return Device(name, f"{name} description", Direction.OUTPUT, volume, muted, running, card, balance)


def source(
    name: str = "mic", volume: int = 80, muted: bool = False, running: bool = False, balance: float | None = None
) -> Device:
    return Device(name, f"{name} description", Direction.INPUT, volume, muted, running, balance=balance)


def stream(
    index: int,
    app: str = "Brave",
    binary: str = "brave",
    volume: int = 100,
    muted: bool = False,
    corked: bool = False,
    balance: float | None = 0.0,
    pid: int | None = None,
) -> Stream:
    return Stream(index, app, binary, volume, muted, corked, balance, pid)
