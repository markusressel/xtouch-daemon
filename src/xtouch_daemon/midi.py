"""The raw ALSA MIDI device of a USB MIDI device, found by its name and read and written without blocking."""

import asyncio
import contextlib
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

PROC_ASOUND_CARDS = Path("/proc/asound/cards")
DEV_SND = Path("/dev/snd")

_LOGGER = logging.getLogger(__name__)


def find_card(proc_asound_cards: str, name: str) -> int | None:
    """
    The number of the sound card whose id or description contains `name`, from the content of /proc/asound/cards:

        0 [XTouchExt      ]: USB-Audio - X-Touch-Ext
                             BEHRINGER X-Touch-Ext at usb-0000:11:00.3-3.3, full speed
    """
    for match in re.finditer(r"^\s*(\d+) \[([^\]]*)\]: (.*)$", proc_asound_cards, re.MULTILINE):
        if name in match.group(2) or name in match.group(3):
            return int(match.group(1))
    return None


class RawMidi:
    """
    An open raw MIDI device (/dev/snd/midiC<card>D0). Calls `on_data` with every chunk that was read, and
    `on_closed` once when the device is gone (e.g. unplugged).
    """

    def __init__(self, path: Path, on_data: Callable[[bytes], None], on_closed: Callable[[], None]):
        self.path = path
        self._on_data = on_data
        self._on_closed = on_closed
        self._fd: int | None = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        self._pending = bytearray()
        self._drained = asyncio.Event()
        self._drained.set()
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(self._fd, self._read)

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def write(self, data: bytes) -> None:
        """Sends the bytes, after the ones that could not be sent yet."""
        if self._fd is None:
            return
        waiting = bool(self._pending)
        self._pending += data
        self._drained.clear()
        if not waiting:
            self._flush()

    def _flush(self) -> None:
        if self._fd is None:
            return
        try:
            written = os.write(self._fd, self._pending)
        except BlockingIOError:
            written = 0
        except OSError as e:
            _LOGGER.info(f"Writing to {self.path} failed: {e}")
            self.close()
            return
        del self._pending[:written]
        if self._pending:
            self._loop.add_writer(self._fd, self._flush_when_writable)
        else:
            self._drained.set()

    def _flush_when_writable(self) -> None:
        if self._fd is not None:
            self._loop.remove_writer(self._fd)
        self._flush()

    def _read(self) -> None:
        if self._fd is None:
            return
        try:
            data = os.read(self._fd, 4096)
        except BlockingIOError:
            return
        except OSError as e:
            _LOGGER.info(f"Reading from {self.path} failed: {e}")
            self.close()
            return
        if not data:
            self.close()
            return
        self._on_data(data)

    async def drain(self, max_wait: float = 1.0) -> None:
        """Waits until everything written was sent (or the device is gone), at most `max_wait` seconds."""
        if self._fd is None:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._drained.wait(), max_wait)

    def close(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        self._loop.remove_reader(fd)
        self._loop.remove_writer(fd)
        os.close(fd)
        self._pending.clear()
        self._drained.set()
        self._on_closed()
