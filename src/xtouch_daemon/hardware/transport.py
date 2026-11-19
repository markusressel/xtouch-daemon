"""
How the `Surface` reaches the device: a `Port` finds and opens it (LookupError while it is not there) and gives a
`Transport` to write to, which calls back with what the device sent and when it is gone. The real device is the raw
ALSA MIDI device of its sound card (`AlsaPort`); the virtual one (see docs/development/design/device-simulator.md) is a
Unix socket (`SocketPort`), which speaks the same bytes.
"""

import socket
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from xtouch_daemon.hardware import midi
from xtouch_daemon.hardware.midi import RawMidi, find_card

VIRTUAL_NAME = "the virtual X-Touch-Ext"
"""What the log calls the virtual device."""


class Transport(Protocol):
    @property
    def is_open(self) -> bool: ...

    def write(self, data: bytes) -> None: ...

    async def drain(self, max_wait: float = 1.0) -> None: ...

    def close(self) -> None: ...


class Port(Protocol):
    name: str
    """What the log calls the device."""

    def open(self, on_data: Callable[[bytes], None], on_closed: Callable[[], None]) -> tuple[Transport, str]:
        """The open device and where it is; LookupError while it is not there, OSError if it can't be opened."""
        ...


class AlsaPort:
    """The device found by the name of its sound card (`/proc/asound/cards`), at `/dev/snd/midiC<card>D0`."""

    def __init__(self, name: str, proc_asound_cards: Path | None = None, dev_snd: Path | None = None):
        self.name = name
        self.proc_asound_cards = proc_asound_cards or midi.PROC_ASOUND_CARDS
        self.dev_snd = dev_snd or midi.DEV_SND

    def open(self, on_data: Callable[[bytes], None], on_closed: Callable[[], None]) -> tuple[Transport, str]:
        card = find_card(self.proc_asound_cards.read_text(), self.name)
        if card is None:
            raise LookupError(f"{self.name} is not connected")
        path = self.dev_snd / f"midiC{card}D0"
        return RawMidi(path, on_data=on_data, on_closed=on_closed), str(path)


class SocketPort:
    """The virtual device, served on a Unix socket (`xtouch-daemon virtual-device`, or the GUI)."""

    def __init__(self, path: Path, name: str = VIRTUAL_NAME):
        self.path = path
        self.name = name

    def open(self, on_data: Callable[[bytes], None], on_closed: Callable[[], None]) -> tuple[Transport, str]:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(self.path))
        except (FileNotFoundError, ConnectionRefusedError) as e:
            sock.close()
            raise LookupError(f"{self.name} does not run") from e
        except OSError:
            sock.close()
            raise
        sock.setblocking(False)
        return RawMidi(self.path, on_data=on_data, on_closed=on_closed, fd=sock.detach()), str(self.path)


class NoPort:
    """A device that is never there: a `Surface` on it shows everything in its mirror only (the virtual twin)."""

    def __init__(self, name: str = "the virtual twin"):
        self.name = name

    def open(self, on_data: Callable[[bytes], None], on_closed: Callable[[], None]) -> tuple[Transport, str]:
        raise LookupError(f"{self.name} has no device")
