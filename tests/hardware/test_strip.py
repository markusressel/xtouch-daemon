"""
A strip of the device: what it shows, and the motor of its fader.
"""

import asyncio

import pytest

from tests.support.hardware import RecordingSurface
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware import strip as strip_module
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.hardware.strip import FADER_SMOOTH_TIME, FADER_TICK, Strip, VirtualStrip, smooth_damp


def test_unchanged_leds_texts_rings_and_colors_are_not_sent_again(surface: RecordingSurface) -> None:
    strip = surface.strips[0]

    for _ in range(2):
        strip.set_led(Button.MUTE, Led.ON)
        strip.set_text(1, "50%")
        strip.set_ring(3, RingMode.WRAP)
        strip.set_color(Color.RED)

    assert surface.sent == [
        protocol.led(0, Button.MUTE, Led.ON),
        protocol.lcd_text(0, 1, "50%"),
        protocol.ring(0, 3, RingMode.WRAP),
        protocol.lcd_colors([Color.RED, *[Color.BLACK] * 7]),
    ]


def test_texts_are_cut_to_what_fits_on_the_lcd(surface: RecordingSurface) -> None:
    surface.strips[2].set_text(0, "Browsers")

    assert surface.strips[2].text[0] == "Browser"
    assert surface.sent == [protocol.lcd_text(2, 0, "Browser")]


def test_meters_are_sent_every_time(surface: RecordingSurface) -> None:
    surface.strips[3].set_meter(5)
    surface.strips[3].set_meter(5)

    assert surface.meters(3) == [5, 5]


async def test_a_reset_strip_is_dark_and_its_fader_goes_down(surface: RecordingSurface) -> None:
    strip = surface.strips[1]
    strip.set_color(Color.GREEN)
    strip.set_text(0, "Buds")
    strip.set_led(Button.SELECT, Led.ON)
    strip.set_fader(0.5)
    await surface.settled()

    strip.reset()
    await surface.settled()

    assert strip.color == Color.BLACK
    assert strip.text == ["", ""]
    assert strip.leds[Button.SELECT] == Led.OFF
    assert strip.ring == (0, RingMode.DOT)
    assert surface.faders(1)[-1] == 0


async def test_a_touched_fader_moves_only_when_it_is_let_go(surface: RecordingSurface) -> None:
    strip = surface.strips[0]

    surface._on_data(bytes([0x90, 0x68, 0x7F]))
    strip.set_fader(0.5)
    await surface.settled()
    assert surface.faders(0) == []

    surface._on_data(bytes([0x90, 0x68, 0x00]))
    await surface.settled()
    assert surface.faders(0)[-1] == protocol.fader_value(0.5)


async def test_a_fader_let_go_at_its_target_gets_it_again(surface: RecordingSurface) -> None:
    strip = surface.strips[0]
    strip.set_fader(1.0)
    await surface.settled()
    surface.sent.clear()

    # moved to the bottom by hand, and the handler follows it there: the device would move the fader back to the
    # top, the value it got last, unless it gets the bottom
    surface._on_data(bytes([0x90, 0x68, 0x7F, 0xE0, 0x00, 0x00]))
    strip.set_fader(0.0)
    surface._on_data(bytes([0x90, 0x68, 0x00]))
    await surface.settled()

    assert surface.faders(0) == [0, 0, 0]


async def test_a_fader_glides_from_where_the_hand_left_it(surface: RecordingSurface) -> None:
    strip = surface.strips[0]
    strip.set_fader(0.0)
    await surface.settled()
    surface.sent.clear()

    # moved to the top by hand, then the fader should be at 0
    surface._on_data(bytes([0x90, 0x68, 0x7F, 0xE0, 0x7F, 0x7F, 0x90, 0x68, 0x00]))
    strip.set_fader(0.0)
    await surface.settled()

    values = surface.faders(0)
    assert len(values) > 5
    assert values == sorted(values, reverse=True)
    assert values[0] < protocol.FADER_MAX
    assert values[-1] == 0


async def test_a_fader_whose_position_is_unknown_glides_from_the_bottom(surface: RecordingSurface) -> None:
    surface.strips[4].set_fader(0.25)
    await surface.settled()

    values = surface.faders(4)
    assert len(values) > 5
    assert values == sorted(values)
    assert values[0] < protocol.fader_value(0.05)
    assert values[-3:] == [protocol.fader_value(0.25)] * 3


async def arrival(strip: Strip) -> None:
    for _ in range(1000):
        if strip._position == strip.fader:
            return
        await asyncio.sleep(0.001)
    raise AssertionError("the fader never arrived")


async def test_an_arrived_fader_gets_its_target_again_later(
    surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(strip_module, "FADER_CONFIRM_DELAYS", (0.02, 0.05))
    strip = surface.strips[0]
    loop = asyncio.get_running_loop()
    strip.set_fader(0.5)
    await arrival(strip)
    arrived = loop.time()
    count = len(surface.faders(0))

    await surface.settled()

    # the motor of the device may have stopped short of it: the target again, twice
    assert surface.faders(0)[count:] == [protocol.fader_value(0.5)] * 2
    # after the last delay (`arrival()` sees the arrival up to a millisecond late)
    assert loop.time() - arrived == pytest.approx(0.05, abs=0.001)


async def test_a_touched_fader_gets_no_target_again(surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(strip_module, "FADER_CONFIRM_DELAYS", (0.05,))
    strip = surface.strips[0]
    strip.set_fader(0.5)
    await arrival(strip)
    count = len(surface.faders(0))

    surface._on_data(bytes([0x90, 0x68, 0x7F]))
    await surface.settled()

    assert len(surface.faders(0)) == count


async def test_a_fader_at_its_target_does_not_move(surface: RecordingSurface) -> None:
    strip = surface.strips[0]
    strip.set_fader(0.5)
    await surface.settled()
    surface.sent.clear()

    strip.set_fader(0.5)
    await surface.settled()

    assert surface.faders(0) == []


def test_a_fader_moves_through_steps_at_an_even_speed() -> None:
    # a volume dragged elsewhere: +2 % every 50 ms
    position = velocity = target = 0.0
    speeds = []
    for tick in range(200):
        if tick % 5 == 0:
            target += 0.02 * protocol.FADER_MAX
        position, velocity = smooth_damp(position, velocity, target, FADER_SMOOTH_TIME, FADER_TICK)
        if tick > 100:
            speeds.append(velocity)

    assert min(speeds) > 0.85 * max(speeds)


def test_the_spring_does_not_overshoot() -> None:
    position, velocity = 0.0, 0.0
    for _ in range(100):
        position, velocity = smooth_damp(position, velocity, 1000.0, FADER_SMOOTH_TIME, FADER_TICK)
        assert position <= 1000.0


async def test_a_virtual_strip_leaves_the_parts_a_claim_shows_alone() -> None:
    surface = RecordingSurface()
    device = surface.strips[0]
    view = VirtualStrip(surface, 9)
    view.set_led(Button.SELECT, Led.ON)
    view.set_led(Button.MUTE, Led.ON)
    view.set_ring(5, RingMode.WRAP)
    view.set_fader(0.5)
    view.mask(frozenset({"select", "encoder", "fader"}))
    device.set_ring(2)
    view.bind(device)
    assert device.leds[Button.SELECT] == Led.OFF
    assert device.leds[Button.MUTE] == Led.ON
    assert device.ring == (2, RingMode.DOT)
    assert device.fader is None
    view.set_led(Button.SELECT, Led.FLASH)
    view.set_ring(7, RingMode.WRAP)
    view.set_fader(0.75)
    assert device.leds[Button.SELECT] == Led.OFF
    assert device.ring == (2, RingMode.DOT)
    # the claim gives the parts back: they show what the strip shows
    view.mask(frozenset({"select"}))
    assert device.ring == (7, RingMode.WRAP)
    assert device.fader == protocol.fader_value(0.75)
    assert device.leds[Button.SELECT] == Led.OFF
    view.mask(frozenset())
    assert device.leds[Button.SELECT] == Led.FLASH
    # off the device: nothing to give back
    view.bind(None)
    view.mask(frozenset({"fader"}))
    view.mask(frozenset())
