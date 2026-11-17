"""
The simulated device in memory, for end-to-end tests of the `Surface` (and what is built on it): a `MemoryPort` that
connects a `Surface` to a `SimulatedDevice`, with the device's time running on the event loop's clock.
"""

import asyncio
from collections.abc import Callable

from xtouch_daemon.simulator.device import SimulatedDevice

TICK = 0.005
"""How often the device's time advances: its motors move, touches of quick hands arrive."""


class MemoryTransport:
    def __init__(self, port: MemoryPort, on_data: Callable[[bytes], None], on_closed: Callable[[], None]):
        self.port = port
        self.on_data = on_data
        self.on_closed = on_closed
        self.is_open = True
        self.ticker = asyncio.create_task(self._tick(), name="simulated device")

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(TICK)
            self.port.send(self.port.device.advance(now()))

    def write(self, data: bytes) -> None:
        self.port.device.receive(data, now())

    async def drain(self, max_wait: float = 1.0) -> None:
        pass

    def close(self) -> None:
        self.is_open = False
        self.ticker.cancel()
        if self.port.transport is self:
            self.port.transport = None


class MemoryPort:
    """The simulated device, plugged in (or not: `unplug()`, `plug()`)."""

    def __init__(self, device: SimulatedDevice | None = None):
        self.name = "the simulated X-Touch-Ext"
        self.device = device or SimulatedDevice()
        self.plugged = True
        self.transport: MemoryTransport | None = None
        self._fresh = False
        """Plugged in again: the device starts like after switching it on."""

    def open(self, on_data: Callable[[bytes], None], on_closed: Callable[[], None]) -> tuple[MemoryTransport, str]:
        if not self.plugged:
            raise LookupError(f"{self.name} is not connected")
        self.transport = MemoryTransport(self, on_data, on_closed)
        hello = self.device.power_cycle() if self._fresh else self.device.hello()
        self._fresh = False
        asyncio.get_running_loop().call_soon(self.send, hello)
        return self.transport, "memory"

    def send(self, data: bytes) -> None:
        """What the device sends to the host."""
        if data and self.transport is not None:
            self.transport.on_data(data)

    def unplug(self) -> None:
        self.plugged = False
        transport = self.transport
        if transport is not None:
            transport.close()
            transport.on_closed()

    def plug(self) -> None:
        self.plugged = True
        self._fresh = True


def now() -> float:
    return asyncio.get_running_loop().time()


async def until(condition: Callable[[], bool], seconds: float = 2.0) -> None:
    """Waits until `condition` holds; AssertionError if it doesn't within `seconds`."""
    for _ in range(round(seconds / TICK)):
        if condition():
            return
        await asyncio.sleep(TICK)
    raise AssertionError("waited in vain")
