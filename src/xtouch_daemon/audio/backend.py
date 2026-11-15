"""What the strips need from the sound server. `PulseBackend` is the real one, the tests use a fake."""

from collections.abc import Callable
from typing import Protocol

from xtouch_daemon.audio.model import AudioState, Direction


class AudioBackend(Protocol):
    async def run(self, on_state: Callable[[AudioState], None]) -> None:
        """
        Calls `on_state` with the current state, and again after every change, for as long as it runs (forever). A
        lost connection to the sound server is reported as `DISCONNECTED` and made again.
        """
        ...

    async def set_device_volume(self, direction: Direction, name: str, percent: int) -> None: ...

    async def set_device_mute(self, direction: Direction, name: str, muted: bool) -> None: ...

    async def set_default(self, direction: Direction, name: str) -> None:
        """Makes the device the default. The streams follow it."""
        ...

    async def set_stream_volume(self, index: int, percent: int) -> None: ...

    async def set_stream_mute(self, index: int, muted: bool) -> None: ...


class AudioCommandError(Exception):
    """A command the sound server did not carry out, e.g. because the device went away meanwhile."""
