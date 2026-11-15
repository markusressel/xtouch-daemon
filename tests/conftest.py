"""Fakes with the shape of the real thing: a backend that records commands, and a surface without device."""

import asyncio
from collections.abc import Callable

import pytest

from xtouch_daemon import protocol
from xtouch_daemon import surface as surface_module
from xtouch_daemon.audio.backend import AudioCommandError
from xtouch_daemon.audio.model import AudioState, Device, Direction, Stream
from xtouch_daemon.config import BehaviorConfig
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.surface import Surface


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

    async def set_default(self, direction: Direction, name: str) -> None:
        await self._command("set_default", direction, name)

    async def set_stream_volume(self, index: int, percent: int) -> None:
        await self._command("set_stream_volume", index, percent)

    async def set_stream_mute(self, index: int, muted: bool) -> None:
        await self._command("set_stream_mute", index, muted)


class RecordingSurface(Surface):
    """A surface whose messages are recorded instead of sent to a device."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[bytes] = []

    def send(self, message: bytes) -> None:
        self.sent.append(message)

    async def run(self) -> None:
        # never looks for the real device, which may be plugged in where the tests run
        await asyncio.Event().wait()

    def faders(self, strip: int) -> list[int]:
        return [m[1] | m[2] << 7 for m in self.sent if m[0] == 0xE0 | strip]

    def meters(self, strip: int) -> list[int]:
        return [m[1] & 0x0F for m in self.sent if m[0] == 0xD0 and m[1] >> 4 == strip]


@pytest.fixture(autouse=True)
def quick_faders(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The faders send their targets again at once, their slow moves are as fast as the others, and the startup and
    shutdown sequences are not staggered: waiting for that adds
    nothing to most tests.
    """
    monkeypatch.setattr(surface_module, "FADER_CONFIRM_DELAYS", (0.0, 0.0))
    monkeypatch.setattr(surface_module, "FADER_SLOW_SMOOTH_TIME", surface_module.FADER_SMOOTH_TIME)
    monkeypatch.setattr(surface_module, "SEQUENCE_STAGGER", 0.0)


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def surface() -> RecordingSurface:
    return RecordingSurface()


@pytest.fixture
def env(backend: FakeBackend) -> StripEnv:
    return StripEnv(backend, BehaviorConfig())


async def finish_tasks() -> None:
    """
    Cancels the tasks a test left and waits for them, like `asyncio.run()` does at its end: meter captures still have
    to end their process.
    """
    current = asyncio.current_task()
    tasks = [task for task in asyncio.all_tasks() if task is not current]
    for task in tasks:
        task.cancel()
    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)


async def settle() -> None:
    """Lets the tasks the strips started run (commands, the fader motors)."""
    for _ in range(5):
        await asyncio.sleep(0)


def output(name: str = "speaker", volume: int = 50, muted: bool = False, running: bool = False) -> Device:
    return Device(name, f"{name} description", Direction.OUTPUT, volume, muted, running)


def source(name: str = "mic", volume: int = 80, muted: bool = False, running: bool = False) -> Device:
    return Device(name, f"{name} description", Direction.INPUT, volume, muted, running)


def stream(
    index: int, app: str = "Brave", binary: str = "brave", volume: int = 100, muted: bool = False, corked: bool = False
) -> Stream:
    return Stream(index, app, binary, volume, muted, corked)


def fader_value(fraction: float) -> int:
    return protocol.fader_value(fraction)
