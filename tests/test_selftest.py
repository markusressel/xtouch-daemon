import asyncio

import pytest

from tests.conftest import RecordingSurface
from xtouch_daemon import protocol
from xtouch_daemon.protocol import Button, Color
from xtouch_daemon.selftest import describe, run_selftest


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
        if lines and lines[-1].startswith("Now use the device"):
            break
        await asyncio.sleep(0.01)
    surface.on_event(protocol.ButtonPressed(0, Button.MUTE, True))
    surface.on_unknown(bytes([0x90, 0x70, 0x7F]))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert lines[-2:] == ["strip 1: mute pressed", "unknown message: 90 70 7f"]
    assert surface.closed
