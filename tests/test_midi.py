import asyncio
import contextlib
import os
import tty
from collections.abc import Iterator
from pathlib import Path

import pytest

from xtouch_daemon import midi
from xtouch_daemon.midi import RawMidi, find_card

PROC_ASOUND_CARDS = """\
 0 [XTouchExt      ]: USB-Audio - X-Touch-Ext
                      BEHRINGER X-Touch-Ext at usb-0000:11:00.3-3.3, full speed
 1 [HDMI           ]: HDA-Intel - HDA ATI HDMI
                      HDA ATI HDMI at 0xed220000 irq 162
"""


def test_finds_the_card_by_name():
    assert find_card(PROC_ASOUND_CARDS, "X-Touch-Ext") == 0
    assert find_card(PROC_ASOUND_CARDS, "XTouchExt") == 0
    assert find_card(PROC_ASOUND_CARDS, "HDMI") == 1
    assert find_card(PROC_ASOUND_CARDS, "Nothing") is None
    assert find_card("", "X-Touch-Ext") is None


class Pty:
    """A pseudo terminal in raw mode: the daemon opens the slave like a MIDI device, the test is the device."""

    def __init__(self) -> None:
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        self.path = Path(os.ttyname(self.slave))
        os.set_blocking(self.master, False)

    def read(self) -> bytes:
        try:
            return os.read(self.master, 4096)
        except BlockingIOError:
            return b""

    def close(self) -> None:
        for fd in (self.master, self.slave):
            # the test may have closed it already
            with contextlib.suppress(OSError):
                os.close(fd)


@pytest.fixture
def device() -> Iterator[Pty]:
    pty = Pty()
    yield pty
    pty.close()


class Recorder:
    def __init__(self) -> None:
        self.data: list[bytes] = []
        self.closed = 0
        self.received = asyncio.Event()

    def on_data(self, data: bytes) -> None:
        self.data.append(data)
        self.received.set()

    def on_closed(self) -> None:
        self.closed += 1


async def test_reads_what_the_device_sends(device: Pty):
    recorder = Recorder()
    raw = RawMidi(device.path, recorder.on_data, recorder.on_closed)
    os.write(device.master, bytes([0x90, 0x10, 0x7F]))
    await asyncio.wait_for(recorder.received.wait(), 1)
    assert b"".join(recorder.data) == bytes([0x90, 0x10, 0x7F])
    assert raw.is_open
    raw.close()
    assert not raw.is_open
    assert recorder.closed == 1


async def test_writes_to_the_device(device: Pty):
    recorder = Recorder()
    raw = RawMidi(device.path, recorder.on_data, recorder.on_closed)
    raw.write(bytes([0xE0, 0x00, 0x40]))
    await raw.drain()
    assert device.read() == bytes([0xE0, 0x00, 0x40])
    raw.close()


async def test_writes_that_do_not_fit_wait_until_the_device_takes_them(device: Pty, monkeypatch: pytest.MonkeyPatch):
    recorder = Recorder()
    raw = RawMidi(device.path, recorder.on_data, recorder.on_closed)
    real_write = os.write
    calls = 0

    def partial_write(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            # the first two bytes fit, the rest waits
            return real_write(fd, bytes(data[:2]))
        if calls == 2:
            raise BlockingIOError
        return real_write(fd, data)

    monkeypatch.setattr(midi.os, "write", partial_write)
    raw.write(b"\x01\x02\x03")
    # queued behind the bytes that are still waiting
    raw.write(b"\x04")
    await raw.drain()
    assert device.read() == b"\x01\x02\x03\x04"
    assert calls >= 3
    raw.close()


async def test_drain_gives_up_after_its_time(device: Pty, monkeypatch: pytest.MonkeyPatch):
    raw = RawMidi(device.path, lambda data: None, lambda: None)

    def blocked(fd: int, data: bytes) -> int:
        raise BlockingIOError

    monkeypatch.setattr(midi.os, "write", blocked)
    raw.write(b"\x01")
    await raw.drain(max_wait=0.05)
    assert raw.is_open
    raw.close()


async def test_a_failing_write_closes_the_device(device: Pty, monkeypatch: pytest.MonkeyPatch):
    recorder = Recorder()
    raw = RawMidi(device.path, recorder.on_data, recorder.on_closed)

    def broken(fd: int, data: bytes) -> int:
        raise OSError(19, "No such device")

    monkeypatch.setattr(midi.os, "write", broken)
    raw.write(b"\x01")
    assert not raw.is_open
    assert recorder.closed == 1


async def test_a_device_that_goes_away_closes(device: Pty):
    recorder = Recorder()
    raw = RawMidi(device.path, recorder.on_data, recorder.on_closed)
    closed = asyncio.Event()
    raw._on_closed = closed.set
    # the other end goes away: reading fails (EIO), like an unplugged device
    os.close(device.master)
    await asyncio.wait_for(closed.wait(), 1)
    assert not raw.is_open


async def test_an_empty_read_closes_and_a_blocked_read_is_skipped(device: Pty, monkeypatch: pytest.MonkeyPatch):
    recorder = Recorder()
    raw = RawMidi(device.path, recorder.on_data, recorder.on_closed)

    def blocked(fd: int, size: int) -> bytes:
        raise BlockingIOError

    monkeypatch.setattr(midi.os, "read", blocked)
    raw._read()
    assert raw.is_open

    monkeypatch.setattr(midi.os, "read", lambda fd, size: b"")
    raw._read()
    assert not raw.is_open
    assert recorder.closed == 1


async def test_a_closed_device_does_nothing(device: Pty):
    recorder = Recorder()
    raw = RawMidi(device.path, recorder.on_data, recorder.on_closed)
    raw.close()
    raw.close()
    raw.write(b"\x01")
    raw._read()
    raw._flush()
    raw._flush_when_writable()
    await raw.drain()
    assert recorder.closed == 1
    assert device.read() == b""


async def test_opening_a_missing_device_fails(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        RawMidi(tmp_path / "midiC9D0", lambda data: None, lambda: None)


async def test_a_failing_read_closes_the_device(device: Pty, monkeypatch: pytest.MonkeyPatch):
    recorder = Recorder()
    raw = RawMidi(device.path, recorder.on_data, recorder.on_closed)

    def broken(fd: int, size: int) -> bytes:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(midi.os, "read", broken)
    raw._read()
    assert not raw.is_open
    assert recorder.closed == 1
