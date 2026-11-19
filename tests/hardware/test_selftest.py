import asyncio
import contextlib
from collections.abc import AsyncIterator

import pytest

from tests.support.hardware import RecordingSurface
from tests.support.simulator import MemoryPort
from tests.support.waiting import until
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware import selftest as selftest_module
from xtouch_daemon.hardware import surface as surface_module
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.hardware.selftest import TestBench, describe, run_selftest
from xtouch_daemon.hardware.surface import Surface


class TestSurface(RecordingSurface):
    __test__ = False

    def __init__(self) -> None:
        super().__init__()
        self.opened = self.closed = False

    def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("event", "text"),
    [
        (protocol.FaderMoved(0, protocol.FADER_MAX), "strip 1: fader at 100%"),
        (protocol.FaderTouched(1, True), "strip 2: fader touched"),
        (protocol.FaderTouched(1, False), "strip 2: fader released"),
        (protocol.ButtonPressed(2, Button.MUTE, True), "strip 3: mute pressed"),
        (protocol.ButtonPressed(2, Button.SELECT, False), "strip 3: select released"),
        (protocol.EncoderTurned(3, -2), "strip 4: encoder -2"),
        (protocol.EncoderTurned(3, 1), "strip 4: encoder +1"),
        (protocol.EncoderPressed(7, True), "strip 8: encoder pressed"),
        (protocol.EncoderPressed(7, False), "strip 8: encoder released"),
    ],
)
def test_events_are_described(event: protocol.StripEvent, text: str) -> None:
    assert describe(event) == text


async def test_the_test_lights_everything_moves_the_faders_and_leaves_the_device_dark() -> None:
    surface = TestSurface()
    lines: list[str] = []

    await run_selftest("X-Touch-Ext", lines.append, show_events=False, surface=surface, step=0)

    assert surface.opened
    assert surface.closed
    assert lines[0].startswith("Connected to X-Touch-Ext.")
    assert lines[-1].startswith("Done:")
    for strip in surface.strips:
        assert protocol.lcd_text(strip.index, 0, "X-Touch") in surface.sent
        assert protocol.led(strip.index, Button.REC, protocol.Led.ON) in surface.sent
        assert surface.meters(strip.index)[-1] == protocol.METER_MAX
        assert protocol.FADER_MAX in surface.faders(strip.index)
        assert surface.faders(strip.index)[-1] == 0
        assert strip.color == Color.BLACK
        assert strip.text == ["", ""]


async def test_after_the_test_events_are_shown_until_it_is_stopped() -> None:
    surface = TestSurface()
    lines: list[str] = []

    task = asyncio.create_task(run_selftest("X-Touch-Ext", lines.append, surface=surface, step=0))
    for _ in range(100):
        if lines and lines[-1].startswith("Now every strip answers"):
            break
        await asyncio.sleep(0.01)
    surface.on_event(protocol.ButtonPressed(0, Button.MUTE, True))
    surface.on_unknown(bytes([0x90, 0x70, 0x7F]))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert lines[-2:] == ["strip 1: mute pressed: mute on", "unknown message: 90 70 7f"]
    assert surface.closed


@contextlib.asynccontextmanager
async def bench_on(port: MemoryPort, lines: list[str]) -> AsyncIterator[TestBench]:
    """The test bench on a surface that runs with the simulated device."""
    surface = Surface(port=port)
    task = asyncio.create_task(surface.run())
    await until(lambda: surface.connected)
    await surface.settled()
    bench = TestBench(surface, lines.append)
    bench.start()
    surface.on_event = bench.handle
    yield bench
    bench.close()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.fixture
def port(monkeypatch: pytest.MonkeyPatch) -> MemoryPort:
    monkeypatch.setattr(surface_module, "SCAN_INTERVAL", 0.01)
    return MemoryPort()


async def test_every_strip_starts_in_its_color_and_names_itself(port: MemoryPort) -> None:
    async with bench_on(port, []):
        await until(lambda: port.device.text(2) == ("strip 3", "ring 6 "))
        assert [strip.color for strip in port.device.strips] == [Color(index % 7 + 1) for index in range(8)]
        assert port.device.strips[0].ring == (6, RingMode.DOT, False)


async def test_a_button_steps_its_led_and_the_lcd_says_so_for_a_moment(port: MemoryPort) -> None:
    lines: list[str] = []
    async with bench_on(port, lines):
        device = port.device
        for expected in (Led.ON, Led.FLASH, Led.OFF):
            port.send(device.press(2, Button.MUTE, True))
            port.send(device.press(2, Button.MUTE, False))
            await until(lambda expected=expected: device.strips[2].leds[Button.MUTE] == expected)
        assert device.text(2)[1] == "mute of"
        await until(lambda: device.text(2)[1] == "ring 6 ", seconds=selftest_module.INPUT_SECONDS + 1)
        assert lines[:2] == ["strip 3: mute pressed: mute on", "strip 3: mute released"]


async def test_the_encoder_edits_the_ring_its_mode_the_color_and_the_fader(port: MemoryPort) -> None:
    lines: list[str] = []
    async with bench_on(port, lines):
        device = port.device
        strip = device.strips[0]
        # the ring, wrapping around below 0
        port.send(device.turn(0, 2))
        await until(lambda: strip.ring == (8, RingMode.DOT, False))
        assert device.text(0)[1] == "ring 8 "
        port.send(device.turn(0, -9))
        await until(lambda: strip.ring == (11, RingMode.DOT, False))

        # its mode: each of the 4 without and with the LED below the ring
        port.send(device.push(0, True))
        port.send(device.push(0, False))
        await until(lambda: device.text(0)[1] == "> mode ")
        port.send(device.turn(0, 3))
        await until(lambda: strip.ring == (11, RingMode.BOOST_CUT, True))
        assert device.text(0)[1] == "boost+c"
        port.send(device.turn(0, 4))
        await until(lambda: strip.ring == (11, RingMode.SPREAD, True))
        assert device.text(0)[1] == "sprd+c "

        # the color of the LCD
        port.send(device.push(0, True))
        port.send(device.turn(0, 1))
        await until(lambda: strip.color == Color.GREEN)
        assert device.text(0)[1] == "green  "

        # the motor, and the meter follows
        port.send(device.push(0, True))
        port.send(device.turn(0, 6))
        await until(lambda: round(strip.fader) == protocol.fader_value(0.6))
        assert device.text(0)[1] == "fad 60%"
        assert device.meter(0) == round(0.6 * protocol.METER_MAX)
        # held up: the device lets a meter fall by itself
        await asyncio.sleep(2)
        assert device.meter(0) == round(0.6 * protocol.METER_MAX)

        # back to the ring
        port.send(device.push(0, True))
        await until(lambda: device.text(0)[1] == "> ring ")
        assert "strip 1: encoder +6: fad 60%" in lines


async def test_a_hand_on_a_fader_moves_the_meter_and_the_fader_stays(port: MemoryPort) -> None:
    lines: list[str] = []
    async with bench_on(port, lines):
        device = port.device
        port.send(device.touch(4, True))
        await until(lambda: device.text(4)[1] == "touch  ")
        port.send(device.move(4, 0.5))
        await until(lambda: device.meter(4) == round(0.5 * protocol.METER_MAX))
        port.send(device.touch(4, False))
        await until(lambda: device.text(4)[1] == "let go ")
        await asyncio.sleep(1)

        assert round(device.strips[4].fader) == protocol.fader_value(0.5)
        assert "strip 5: fader touched: touch" in lines
