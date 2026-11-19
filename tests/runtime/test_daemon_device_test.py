"""
The test of the device in the daemon (`StartTest`): the device answers its inputs, the slots go on without showing on
it, and they show again when the test ends.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.support.audio import FakeBackend
from tests.support.daemon import QUIET, SPEAKER, STATE
from tests.support.simulator import MemoryPort
from tests.support.waiting import until
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware import surface as surface_module
from xtouch_daemon.hardware.protocol import Button, Color, Led
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.live.messages import EndTest, KeepTest, Play, Reply, StartPreview, StartTest
from xtouch_daemon.runtime import daemon as daemon_module
from xtouch_daemon.runtime.daemon import Daemon

BOXES = SPEAKER.replace('"Speaker"', '"Boxes"')


class Told(list[tuple[object, Reply]]):
    def to(self, client: object) -> list[Reply]:
        return [reply for to, reply in self if to is client]


@contextlib.asynccontextmanager
async def running(
    config_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[Daemon, MemoryPort, Told]]:
    """A daemon that runs with the simulated device, strip 1 showing the speaker; what it tells clients is recorded."""
    monkeypatch.setattr(surface_module, "SCAN_INTERVAL", 0.01)
    port = MemoryPort()
    daemon = Daemon(
        parse_config(config_path.read_text()),
        FakeBackend((STATE,)),
        Surface(port=port),
        config_path,
        capture_command=QUIET,
        live_socket=socket_dir / "live.sock",
    )
    told = Told()
    assert daemon.live is not None
    monkeypatch.setattr(daemon.live, "tell", lambda client, reply: told.append((client, reply)))
    task = asyncio.create_task(daemon.run())
    await until(lambda: port.device.text(0)[0].strip() == "Speaker")
    yield daemon, port, told
    daemon.stop()
    await task


async def start_the_test(daemon: Daemon, port: MemoryPort, client: object) -> None:
    """Starts the test and waits until the sweep is through."""
    assert daemon.on_request(client, StartTest()) == Reply("test", True)
    await until(lambda: port.device.text(0) == ("strip 1", "ring 6 "), seconds=10)


async def test_the_device_answers_its_inputs_and_shows_the_slots_again_after_it(
    config_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with running(config_path, socket_dir, monkeypatch) as (daemon, port, told):
        gui = object()
        await start_the_test(daemon, port, gui)
        assert daemon.snapshot().test
        device = port.device

        # the device, and a hand on its drawing
        port.send(device.press(0, Button.MUTE, True))
        await until(lambda: device.strips[0].leds[Button.MUTE] == Led.ON)
        daemon.on_request(gui, Play(protocol.ButtonPressed(0, Button.MUTE, True)))
        await until(lambda: device.strips[0].leds[Button.MUTE] == Led.FLASH)
        assert daemon.snapshot().strips[0].leds["mute"] == "flash"

        # the slots go on, but don't show
        config_path.write_text(BOXES)
        assert daemon.reload()
        await asyncio.sleep(0.5)
        assert device.text(0)[0] == "strip 1"

        daemon.on_request(gui, EndTest())

        await until(lambda: device.text(0)[0].strip() == "Boxes")
        assert device.strips[0].leds[Button.MUTE] == Led.OFF
        assert device.strips[0].color == Color.CYAN
        assert not daemon.snapshot().test
        # it asked for the end itself
        assert told.to(gui) == []


async def test_the_test_ends_without_word_from_its_gui(
    config_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_module, "TEST_TIMEOUT", 3.0)
    async with running(config_path, socket_dir, monkeypatch) as (daemon, port, told):
        gui = object()
        await start_the_test(daemon, port, gui)
        for _ in range(4):
            await asyncio.sleep(1)
            daemon.on_request(gui, KeepTest())
        assert daemon.testing

        await until(lambda: not daemon.testing, seconds=10)
        assert told.to(gui) == [Reply("test_ended", True, "no word from the GUI for 3 s")]
        await until(lambda: port.device.text(0)[0].strip() == "Speaker")


async def test_a_gui_that_goes_away_or_a_preview_on_the_device_ends_it(
    config_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with running(config_path, socket_dir, monkeypatch) as (daemon, port, told):
        gui, other = object(), object()
        await start_the_test(daemon, port, gui)
        # another window takes it over
        assert daemon.on_request(other, StartTest()) == Reply("test", True)
        assert told.to(gui) == [Reply("test_ended", True, "another window tests the device now")]
        daemon.on_client_closed(gui)
        assert daemon.testing
        daemon.on_client_closed(other)
        assert not daemon.testing

        await start_the_test(daemon, port, gui)
        assert daemon.on_request(other, StartPreview(BOXES)) == Reply("preview", True)
        assert not daemon.testing
        assert told.to(gui)[-1] == Reply("test_ended", True, "a preview on the device took it")
        await until(lambda: port.device.text(0)[0].strip() == "Boxes")

        # and the test ends the preview on the device
        await start_the_test(daemon, port, gui)
        assert not daemon.previewing
        assert told.to(other)[-1] == Reply("ended", True, "the device is tested now")


async def test_the_test_ends_when_the_device_goes_away(
    config_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with running(config_path, socket_dir, monkeypatch) as (daemon, port, told):
        gui = object()
        await start_the_test(daemon, port, gui)
        port.unplug()
        await until(lambda: not daemon.testing)
        assert told.to(gui) == [Reply("test_ended", True, "the device went away")]
        assert daemon.on_request(gui, StartTest()) == Reply("test", False, "The device is not connected.")

        port.plug()
        await until(lambda: port.device.text(0)[0].strip() == "Speaker", seconds=10)
