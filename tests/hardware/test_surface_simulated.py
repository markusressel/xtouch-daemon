"""
The `Surface` against the simulated device, end to end: what the device shows after a connect, hands on its faders
(with and without a working touch sensor), and a device that is switched off and on again.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator

import pytest

from tests.support.simulator import MemoryPort, until
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware import surface as surface_module
from xtouch_daemon.hardware.protocol import Button, Color, Led
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.simulator.device import SimulatedDevice

HALF = protocol.fader_value(0.5)
QUARTER = protocol.fader_value(0.25)


@pytest.fixture
def port(monkeypatch: pytest.MonkeyPatch) -> MemoryPort:
    monkeypatch.setattr(surface_module, "SCAN_INTERVAL", 0.01)
    # the device reports the touch of a quick hand late, like the real one
    monkeypatch.setattr(surface_module, "TOUCH_GRACE", 0.3)
    return MemoryPort()


@contextlib.asynccontextmanager
async def running(port: MemoryPort) -> AsyncIterator[Surface]:
    """
    A surface that runs with the simulated device, strip 2 showing something. Not a fixture: async fixtures don't run
    on the fake clock of the test (looptime), which the device's time follows.
    """
    surface = Surface(port=port)
    surface.strips[1].set_text(0, "Buds")
    surface.strips[1].set_color(Color.GREEN)
    surface.strips[1].set_led(Button.MUTE, Led.ON)
    surface.strips[1].set_fader(0.5)
    task = asyncio.create_task(surface.run())
    await until(lambda: surface.connected)
    await surface.settled()
    await until(lambda: fader(port.device, 1) == HALF)
    yield surface
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def fader(device: SimulatedDevice, strip: int) -> int:
    return round(device.strips[strip].fader)


async def test_after_a_connect_the_device_shows_what_the_strips_show(port: MemoryPort) -> None:
    async with running(port):
        device = port.device
        assert device.text(1)[0] == "Buds".ljust(protocol.LCD_CELL_WIDTH)
        assert device.strips[1].color == Color.GREEN
        assert device.strips[1].leds[Button.MUTE] == Led.ON
        assert device.strips[0].color == Color.BLACK


async def test_a_hand_on_a_fader_arrives_and_the_motor_goes_back_when_it_lets_go(port: MemoryPort) -> None:
    async with running(port) as surface:
        events: list[protocol.StripEvent] = []
        surface.on_event = events.append
        device = port.device

        port.send(device.touch(1, True))
        port.send(device.move(1, 0.25))
        assert events == [protocol.FaderTouched(1, True), protocol.FaderMoved(1, QUARTER)]
        port.send(device.touch(1, False))

        # nothing took the move: the fader goes back to its value
        await until(lambda: fader(device, 1) == HALF)
        assert events[-1] == protocol.FaderTouched(1, False)


async def test_the_moves_of_a_quick_hand_count_once_its_touch_arrives(port: MemoryPort) -> None:
    async with running(port) as surface:
        events: list[protocol.StripEvent] = []
        surface.on_event = events.append

        port.send(port.device.move(1, 0.25))
        assert events == []

        await until(lambda: bool(events))
        assert events == [protocol.FaderTouched(1, True), protocol.FaderMoved(1, QUARTER)]


async def test_a_fader_without_a_touch_sensor_takes_moves_as_touches(
    port: MemoryPort, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface_module, "TOUCHLESS_STARTUP", 0.0)
    monkeypatch.setattr(surface_module, "TOUCHLESS_LET_GO", 0.05)
    port.device.broken_touch = {1}
    async with running(port) as surface:
        surface.touchless = frozenset({1})
        events: list[protocol.StripEvent] = []
        surface.on_event = events.append

        port.send(port.device.move(1, 0.25))
        assert events == [protocol.FaderTouched(1, True), protocol.FaderMoved(1, QUARTER)]

        await until(lambda: events[-1] == protocol.FaderTouched(1, False))
        await until(lambda: fader(port.device, 1) == HALF)


async def test_a_device_switched_off_and_on_shows_everything_again(port: MemoryPort) -> None:
    async with running(port) as surface:
        events: list[protocol.StripEvent] = []
        connections: list[bool] = []
        surface.on_event = events.append
        surface.on_connection = connections.append
        device = port.device

        port.unplug()
        assert connections == [False]
        port.plug()
        await until(lambda: connections == [False, True])
        await surface.settled()

        # it went dark and its faders went down by themselves: no hand did that, so they come back
        await until(lambda: fader(device, 1) == HALF and not device.strips[1].moving)
        assert device.text(1)[0] == "Buds".ljust(protocol.LCD_CELL_WIDTH)
        assert device.strips[1].color == Color.GREEN
        assert events == []
