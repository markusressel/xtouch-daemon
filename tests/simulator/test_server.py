"""
The virtual device on its socket, with a real `Surface` as the host: what the host sets reaches the device, a hand on
it reaches the host, unplugging, switching off and on, and one host at a time.
"""

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.support.waiting import until
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware import surface as surface_module
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.hardware.transport import SocketPort
from xtouch_daemon.simulator.device import SimulatedDevice
from xtouch_daemon.simulator.server import AlreadyServed, VirtualDevice


@contextlib.asynccontextmanager
async def serving(path: Path, changes: list[None] | None = None) -> AsyncIterator[VirtualDevice]:
    """The virtual device, plugged in at `path`, while the block runs."""
    server = VirtualDevice(
        SimulatedDevice(), path, on_change=lambda: changes.append(None) if changes is not None else None
    )
    task = asyncio.create_task(server.run())
    await until(lambda: server.plugged)
    yield server
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not path.exists()


@contextlib.asynccontextmanager
async def daemon(path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Surface]:
    """A surface that drives the virtual device at `path`, like `run --virtual-device`."""
    monkeypatch.setattr(surface_module, "SCAN_INTERVAL", 0.01)
    surface = Surface(port=SocketPort(path))
    task = asyncio.create_task(surface.run())
    yield surface
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_the_daemon_drives_the_virtual_device(socket_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = socket_dir / "virtual-device.sock"
    changes: list[None] = []
    async with serving(path, changes) as server, daemon(path, monkeypatch) as surface:
        events: list[protocol.StripEvent] = []
        surface.on_event = events.append
        surface.strips[2].set_text(0, "Speaker")
        await until(lambda: server.host is not None)
        await until(lambda: server.device.text(2)[0] == "Speaker")
        assert changes

        # a hand on the device
        server.send(server.device.touch(2, True))
        await until(lambda: events == [protocol.FaderTouched(2, True)])


async def test_unplugged_the_daemon_waits_for_it(socket_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = socket_dir / "virtual-device.sock"
    async with serving(path) as server, daemon(path, monkeypatch) as surface:
        connections: list[bool] = []
        surface.on_connection = connections.append
        await until(lambda: server.host is not None)

        server.unplug()
        server.unplug()
        await until(lambda: connections == [True, False])
        assert not path.exists()
        await server.plug()
        await server.plug()
        await until(lambda: connections == [True, False, True])


async def test_switched_off_and_on_the_device_starts_again(socket_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = socket_dir / "virtual-device.sock"
    async with serving(path) as server, daemon(path, monkeypatch) as surface:
        surface.strips[0].set_text(0, "Mic")
        await until(lambda: server.device.text(0)[0] == "Mic    ")
        connections: list[bool] = []
        surface.on_connection = connections.append

        await server.power_cycle()

        await until(lambda: connections == [False, True])
        # dark at first, then the daemon shows everything again
        await until(lambda: server.device.text(0)[0] == "Mic    ")


async def test_one_host_at_a_time(socket_dir: Path) -> None:
    path = socket_dir / "virtual-device.sock"
    async with serving(path) as server:
        first = SocketPort(path).open(lambda data: None, lambda: None)[0]
        await until(lambda: server.host is not None)
        closed: list[None] = []
        second = SocketPort(path).open(lambda data: None, lambda: closed.append(None))[0]
        await until(lambda: bool(closed))
        second.close()

        # the first one still has it; when it goes, the device waits for the next
        assert server.host is not None
        first.close()
        await until(lambda: server.host is None)


async def test_a_second_virtual_device_is_refused(socket_dir: Path) -> None:
    path = socket_dir / "virtual-device.sock"
    async with serving(path):
        with pytest.raises(AlreadyServed):
            await VirtualDevice(SimulatedDevice(), path).plug()


async def test_a_socket_left_behind_is_replaced(socket_dir: Path) -> None:
    path = socket_dir / "virtual-device.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as left:
        left.bind(str(path))
    async with serving(path) as server:
        assert server.plugged


async def test_a_hand_without_a_host_moves_only_the_device(socket_dir: Path) -> None:
    async with serving(socket_dir / "virtual-device.sock") as server:
        server.send(server.device.touch(0, True))
        assert server.device.strips[0].touched


async def test_a_host_that_leaves_without_reading_is_gone(socket_dir: Path) -> None:
    path = socket_dir / "virtual-device.sock"
    async with serving(path) as server:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as host:
            host.connect(str(path))
            await until(lambda: server.host is not None)
            server.send(server.device.touch(0, True))
            await asyncio.sleep(0.05)
        # what it didn't read resets the connection
        await until(lambda: server.host is None)


async def test_the_daemon_finds_the_virtual_device_at_once(socket_dir: Path) -> None:
    # the GUI opens it to play with it: the daemon looks for it more often than for a sound card
    path = socket_dir / "virtual-device.sock"
    surface = Surface(port=SocketPort(path))
    task = asyncio.create_task(surface.run())
    await asyncio.sleep(0.05)
    async with serving(path) as server:
        loop = asyncio.get_running_loop()
        plugged = loop.time()
        await until(lambda: server.host is not None)
        assert loop.time() - plugged <= 0.2
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
