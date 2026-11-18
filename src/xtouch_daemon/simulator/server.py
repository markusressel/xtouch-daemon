"""
The virtual device: a `SimulatedDevice` served on a Unix socket, where the daemon finds it (`SocketPort`) and speaks
the bytes of the real device. One host at a time, like the device a program has open; the device stays when the host
goes, so a daemon that connects again finds the faders where they were. A tick moves the motors and lets the touches
of quick hands arrive.
"""

import asyncio
import contextlib
import logging
import socket
from collections.abc import Callable
from pathlib import Path

from xtouch_daemon.simulator.device import SimulatedDevice

_LOGGER = logging.getLogger(__name__)

TICK = 0.01
"""How often the device's time advances."""


class AlreadyServed(Exception):
    """Another virtual device runs at the socket."""


class VirtualDevice:
    """`device` at `path` while `run()` runs; `send()` is what a hand does on it."""

    def __init__(self, device: SimulatedDevice, path: Path, on_change: Callable[[], None] = lambda: None):
        self.device = device
        self.path = path
        self.on_change = on_change
        """Called when what the device shows changed, or the host came or went (for frontends to paint again)."""
        self.host: asyncio.StreamWriter | None = None
        """The connection of the host (the daemon), None while there is none."""
        self._server: asyncio.Server | None = None
        self._version = -1

    @property
    def plugged(self) -> bool:
        return self._server is not None

    async def run(self) -> None:
        """Serves the device (plugged in) until cancelled."""
        await self.plug()
        loop = asyncio.get_running_loop()
        try:
            while True:
                self.send(self.device.advance(loop.time()))
                if self.device.version != self._version:
                    self._version = self.device.version
                    self.on_change()
                await asyncio.sleep(TICK)
        finally:
            self.unplug()

    async def plug(self) -> None:
        """Plugged in: the socket takes a host. AlreadyServed if another virtual device has it."""
        if self._server is not None:
            return
        if listening(self.path):
            raise AlreadyServed(f"a virtual device already runs at {self.path}")
        self.path.unlink(missing_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._server = await asyncio.start_unix_server(self._serve, path=self.path)
        _LOGGER.info(f"The virtual device waits for the daemon at {self.path}")

    def unplug(self) -> None:
        """Unplugged: the host loses it, and finds nothing until it is plugged in again."""
        if self._server is None:
            return
        self._server.close()
        self._server = None
        self.path.unlink(missing_ok=True)
        if self.host is not None:
            self.host.close()
            self.host = None
        self.on_change()

    async def power_cycle(self) -> None:
        """Switched off and on: the host loses it, and it starts like the real device (see `SimulatedDevice`)."""
        self.unplug()
        # its query goes nowhere: it comes before a host can connect
        self.device.power_cycle()
        await self.plug()

    def send(self, data: bytes) -> None:
        """What the device sends to the host (a hand on it); lost while there is none."""
        if data and self.host is not None:
            self.host.write(data)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.host is not None or not self.plugged:
            # the device is open already (or was unplugged as the host came)
            _LOGGER.warning("A second host was refused")
            writer.close()
            return
        self.host = writer
        _LOGGER.info("The daemon connected")
        self.on_change()
        loop = asyncio.get_running_loop()
        try:
            while data := await reader.read(4096):
                _LOGGER.debug(f"From the host: {data.hex(' ')}")
                self.device.receive(data, loop.time())
        except ConnectionError:
            pass
        finally:
            if self.host is writer:
                self.host = None
                _LOGGER.info("The daemon disconnected")
                self.on_change()
            writer.close()


def listening(path: Path) -> bool:
    """Whether something accepts connections at the Unix socket `path`."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe, contextlib.suppress(OSError):
        probe.connect(str(path))
        return True
    return False
