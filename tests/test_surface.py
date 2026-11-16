import asyncio
import contextlib
import logging
import os
import tty
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.conftest import RecordingSurface
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware import strip as strip_module
from xtouch_daemon.hardware import surface as surface_module
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.hardware.strip import FADER_SMOOTH_TIME, FADER_TICK, Strip, VirtualStrip, smooth_damp
from xtouch_daemon.hardware.surface import Surface, steps

CARDS = """\
 0 [XTouchExt      ]: USB-Audio - X-Touch-Ext
                      BEHRINGER X-Touch-Ext at usb-0000:11:00.3-3.3, full speed
"""


# -- what strips show ---------------------------------------------------------------------------------------------


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


# -- the motor ----------------------------------------------------------------------------------------------------


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


# -- events ---------------------------------------------------------------------------------------------------------


def test_events_of_the_device_go_to_the_handler(surface: RecordingSurface) -> None:
    events: list[protocol.StripEvent] = []
    surface.on_event = events.append

    surface._on_data(bytes([0x90, 0x69, 0x7F, 0xE1, 0x7F, 0x7F, 0x90, 0x11, 0x7F, 0xB0, 0x12, 0x41, 0x90, 0x23, 0x7F]))

    assert events == [
        protocol.FaderTouched(1, True),
        protocol.FaderMoved(1, protocol.FADER_MAX),
        protocol.ButtonPressed(1, Button.MUTE, True),
        protocol.EncoderTurned(2, -1),
        protocol.EncoderPressed(3, True),
    ]


def test_the_host_query_and_unknown_messages_are_ignored(surface: RecordingSurface) -> None:
    events: list[protocol.StripEvent] = []
    surface.on_event = events.append

    surface._on_data(bytes.fromhex("f00000661501") + b"015640E5DD9" + bytes([0xF7, 0xC0, 0x01]))

    assert events == []


def test_a_failing_handler_is_logged_and_the_next_event_still_handled(
    surface: RecordingSurface, caplog: pytest.LogCaptureFixture
) -> None:
    events: list[protocol.StripEvent] = []

    def handler(event: protocol.StripEvent) -> None:
        events.append(event)
        if len(events) == 1:
            raise RuntimeError("broken")

    surface.on_event = handler
    surface._on_data(bytes([0x90, 0x10, 0x7F, 0x90, 0x10, 0x00]))

    assert len(events) == 2
    assert "broken" in caplog.text


async def test_the_motor_follows_the_handler_after_a_release(surface: RecordingSurface) -> None:
    strip = surface.strips[0]

    # the handler decides where the fader goes when it is let go
    surface.on_event = lambda event: strip.set_fader(0.75)
    surface._on_data(bytes([0x90, 0x68, 0x7F, 0x90, 0x68, 0x00]))
    await surface.settled()

    assert surface.faders(0)[-1] == protocol.fader_value(0.75)


# -- the connection -------------------------------------------------------------------------------------------------


@pytest.fixture
def device(tmp_path: Path) -> Iterator[tuple[Path, Path, int]]:
    """
    A fake sound card list and MIDI device: /dev/snd/midiC0D0 is a link to a pseudo terminal in raw mode, whose
    other end (the returned file descriptor) plays the device.
    """
    cards = tmp_path / "cards"
    cards.write_text(CARDS)
    dev = tmp_path / "snd"
    dev.mkdir()
    controller, peer = os.openpty()
    tty.setraw(peer)
    (dev / "midiC0D0").symlink_to(os.ttyname(peer))
    yield cards, dev, controller
    os.close(peer)
    os.close(controller)


def read_all(fd: int) -> bytes:
    os.set_blocking(fd, False)
    data = b""
    with contextlib.suppress(BlockingIOError):
        while chunk := os.read(fd, 65536):
            data += chunk
    return data


async def test_a_connect_shows_everything_the_strips_show(device: tuple[Path, Path, int]) -> None:
    cards, dev, controller = device
    surface = Surface(proc_asound_cards=cards, dev_snd=dev)
    surface.strips[1].set_text(0, "Buds")
    surface.strips[1].set_fader(0.5)
    surface.strips[1].set_color(Color.GREEN)
    connections: list[bool] = []
    surface.on_connection = connections.append

    assert surface.connect()
    assert surface.connected
    assert connections == [True]
    await surface.settled()
    await surface.close()

    data = read_all(controller)
    assert protocol.lcd_text(1, 0, "Buds") in data
    assert protocol.fader(1, protocol.fader_value(0.5)) in data
    assert protocol.lcd_colors([Color.BLACK, Color.GREEN, *[Color.BLACK] * 6]) in data
    # strips whose fader is not known yet don't move
    assert protocol.fader(0, 0) not in data
    # LEDs nothing turned on are turned off: the device may still show them from before
    assert all(protocol.led(index, button, Led.OFF) in data for index in range(protocol.STRIPS) for button in Button)
    assert connections == [True, False]


async def test_what_happens_on_the_device_arrives_as_events(device: tuple[Path, Path, int]) -> None:
    cards, dev, controller = device
    surface = Surface(proc_asound_cards=cards, dev_snd=dev)
    events: list[protocol.StripEvent] = []
    surface.on_event = events.append
    surface.open()

    os.write(controller, bytes([0x90, 0x12, 0x7F]))
    for _ in range(50):
        if events:
            break
        await asyncio.sleep(0.01)
    await surface.close()

    assert events == [protocol.ButtonPressed(2, Button.MUTE, True)]


async def test_a_missing_device_is_waited_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cards = tmp_path / "cards"
    cards.write_text("")
    surface = Surface(proc_asound_cards=cards, dev_snd=tmp_path)
    monkeypatch.setattr(surface_module, "SCAN_INTERVAL", 0.01)

    task = asyncio.create_task(surface.run())
    await asyncio.sleep(0.05)
    assert not surface.connected
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_the_device_is_connected_again_after_it_was_gone(
    device: tuple[Path, Path, int], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    cards, dev, _ = device
    surface = Surface(proc_asound_cards=cards, dev_snd=dev)
    monkeypatch.setattr(surface_module, "SCAN_INTERVAL", 0.01)
    connections: list[bool] = []
    surface.on_connection = connections.append
    caplog.set_level(logging.INFO)

    task = asyncio.create_task(surface.run())
    await asyncio.sleep(0.02)
    assert surface._midi is not None
    surface._midi.close()
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert connections[:3] == [True, False, True]
    assert "is gone" in caplog.text


def test_a_device_that_can_not_be_opened_is_reported(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    cards = tmp_path / "cards"
    cards.write_text(CARDS)
    surface = Surface(proc_asound_cards=cards, dev_snd=tmp_path / "missing")

    assert not surface.connect()
    assert "Can't open X-Touch-Ext" in caplog.text


def test_open_tells_a_missing_device_from_one_that_can_not_be_opened(tmp_path: Path) -> None:
    cards = tmp_path / "cards"
    cards.write_text("")
    with pytest.raises(LookupError):
        Surface(proc_asound_cards=cards, dev_snd=tmp_path).open()


async def test_closing_a_surface_without_device_does_nothing(surface: RecordingSurface) -> None:
    await surface.close()
    assert not surface.connected


def test_without_a_device_nothing_is_sent(tmp_path: Path) -> None:
    surface = Surface(proc_asound_cards=tmp_path / "cards", dev_snd=tmp_path)
    surface.send(b"\x90\x10\x7f")
    assert not surface.connected


async def test_letting_go_of_a_fader_without_target_does_not_move_it(surface: RecordingSurface) -> None:
    surface._on_data(bytes([0x90, 0x68, 0x7F, 0x90, 0x68, 0x00]))
    await surface.settled()

    assert surface.faders(0) == []


def test_a_touched_fader_takes_no_step(surface: RecordingSurface) -> None:
    strip = surface.strips[0]
    strip.fader = 100
    strip.touched = True

    assert not strip.step(0.0)


async def test_a_fader_that_is_put_away_goes_down_slowly(
    surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(strip_module, "FADER_SLOW_SMOOTH_TIME", 0.2)
    # after a fast move the motor stops short of the bottom, a slow one gets there
    for strip in surface.strips[:2]:
        strip.set_fader(1.0)
    await surface.settled()
    surface.sent.clear()

    surface.strips[0].set_fader(0.0)
    surface.strips[1].reset()
    await surface.settled()

    fast, slow = surface.faders(0), surface.faders(1)
    assert fast[-1] == slow[-1] == 0
    assert len(slow) > 1.5 * len(fast)


# -- the startup and shutdown sequences -----------------------------------------------------------------------------


async def test_after_a_connect_the_strips_light_up_one_after_the_other(
    device: tuple[Path, Path, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface_module, "SEQUENCE_STAGGER", 0.02)
    cards, dev, controller = device
    surface = Surface(proc_asound_cards=cards, dev_snd=dev)
    for strip in surface.strips:
        strip.set_text(0, f"S{strip.index}")
        strip.set_color(Color.GREEN)
    assert surface.connect()

    await asyncio.sleep(0.03)
    early = read_all(controller)
    # at first dark, then strip 1 (and maybe 2), not yet the others
    assert early.startswith(protocol.lcd_colors([Color.BLACK] * 8))
    assert protocol.lcd_text(0, 0, "S0") in early
    assert protocol.lcd_text(7, 0, "S7") not in early
    # what a strip shows before its turn waits for it
    surface.strips[7].set_text(1, "later")
    surface.strips[7].set_meter(5)
    assert protocol.lcd_text(7, 1, "later") not in read_all(controller)

    await surface.settled()
    await surface.close()
    late = read_all(controller)
    assert protocol.lcd_text(7, 0, "S7") in late
    assert protocol.lcd_text(7, 1, "later") in late
    assert late.endswith(protocol.lcd_colors([Color.GREEN] * 8)) or protocol.lcd_colors([Color.GREEN] * 8) in late


async def test_a_fader_waits_for_its_turn_and_then_comes_up_slowly(
    surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(strip_module, "FADER_SLOW_SMOOTH_TIME", 0.2)
    fast, slow = surface.strips[0], surface.strips[1]
    fast.set_fader(0.0)
    await surface.settled()
    assert not fast._slow
    surface.sent.clear()
    slow.shown = False

    fast.set_fader(1.0)
    slow.set_fader(1.0)
    await surface.settled()
    assert surface.faders(1) == []

    slow.reveal()
    await surface.settled()
    # its position is not known after a connect: it comes from the bottom, slowly
    assert surface.faders(1)[0] < protocol.fader_value(0.05)
    assert len(surface.faders(1)) > 1.5 * len(surface.faders(0))


async def test_after_a_reconnect_a_fader_comes_up_from_the_bottom_again(surface: RecordingSurface) -> None:
    strip = surface.strips[0]
    strip.set_fader(0.5)
    await surface.settled()
    surface.sent.clear()

    # switched off and on again: the device put its faders down meanwhile, without telling
    strip.connected()
    strip.reveal()
    await surface.settled()

    assert surface.faders(0)[0] < protocol.fader_value(0.05)
    assert surface.faders(0)[-1] == protocol.fader_value(0.5)


async def test_a_slow_move_stays_slow_until_the_fader_arrived(
    surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(strip_module, "FADER_SLOW_SMOOTH_TIME", 0.2)
    for strip in surface.strips[:2]:
        strip.set_fader(1.0)
    await surface.settled()
    surface.sent.clear()

    surface.strips[0].set_fader(0.0)
    surface.strips[1].park()
    # e.g. a state that comes in on the way
    surface.strips[1].set_fader(0.0)
    await surface.settled()

    assert len(surface.faders(1)) > 1.5 * len(surface.faders(0))


async def test_a_hand_on_the_fader_ends_a_slow_move(surface: RecordingSurface) -> None:
    strip = surface.strips[0]
    strip.park()
    surface._on_data(bytes([0x90, 0x68, 0x7F, 0xE0, 0x00, 0x40, 0x90, 0x68, 0x00]))

    assert not strip._slow


async def test_the_shutdown_sequence_goes_from_the_right(surface: RecordingSurface) -> None:
    for strip in surface.strips:
        strip.set_text(0, f"S{strip.index}")
    surface.sent.clear()

    await surface.put_away()

    blanks = [m for m in surface.sent if m.startswith(protocol.SYSEX_HEADER + b"\x12") and m[6] < 0x38]
    assert [m[6] // 7 for m in blanks] == list(reversed(range(8)))
    assert all(strip.text == ["", ""] for strip in surface.strips)


def test_the_sequences_take_the_strips_in_their_order() -> None:
    assert steps("instant", startup=True) == [tuple(range(8))]
    assert steps("sweep", startup=True) == [(0,), (1,), (2,), (3,), (4,), (5,), (6,), (7,)]
    assert steps("show", startup=False) == [(7,), (6,), (5,), (4,), (3,), (2,), (1,), (0,)]
    # a curtain opens from the middle, and closes from the outside
    assert steps("curtain", startup=True) == [(3, 4), (2, 5), (1, 6), (0, 7)]
    assert steps("curtain", startup=False) == [(0, 7), (1, 6), (2, 5), (3, 4)]


def texts_in_order(surface: RecordingSurface, line: int = 0) -> list[int]:
    """The strips whose first line was sent, in the order they were."""
    prefix = protocol.SYSEX_HEADER + b"\x12"
    return [m[6] // 7 for m in surface.sent if m.startswith(prefix) and m[6] < 0x38 and m[6] % 7 == 0]


def hide(surface: RecordingSurface) -> None:
    """Like a connect: the strips wait for their turn in the startup sequence."""
    for strip in surface.strips:
        strip.set_text(0, f"S{strip.index}")
        strip.set_color(Color.GREEN)
        strip.shown = False
    surface.sent.clear()


async def test_a_curtain_opens_from_the_middle_and_closes_from_the_outside(surface: RecordingSurface) -> None:
    surface.startup = surface.shutdown = "curtain"
    hide(surface)
    await surface._reveal()
    assert texts_in_order(surface) == [3, 4, 2, 5, 1, 6, 0, 7]

    surface.sent.clear()
    await surface.put_away()
    assert texts_in_order(surface) == [0, 7, 1, 6, 2, 5, 3, 4]


async def test_instant_sequences_take_all_strips_at_once(
    surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a stagger would show
    monkeypatch.setattr(surface_module, "SEQUENCE_STAGGER", 10.0)
    surface.startup = surface.shutdown = "instant"
    hide(surface)
    await asyncio.wait_for(surface._reveal(), 1)
    assert texts_in_order(surface) == list(range(8))
    await asyncio.wait_for(surface.put_away(), 1)
    assert all(strip.text == ["", ""] for strip in surface.strips)


async def test_the_show_lights_the_strips_up_before_they_show_what_they_are(surface: RecordingSurface) -> None:
    surface.startup = "show"
    hide(surface)
    surface.strips[0].set_fader(0.5)
    surface.sent.clear()

    await surface._reveal()
    await surface.settled()

    sent = surface.sent
    first_text = sent.index(protocol.lcd_text(0, 0, "S0"))
    for index in range(8):
        # the wave of light, before any strip shows what it is
        wave = [
            protocol.meter(index, protocol.METER_MAX),
            *(protocol.led(index, button, Led.ON) for button in Button),
            protocol.ring(index, protocol.RING_MAX, RingMode.WRAP),
        ]
        assert all(sent.index(message) < first_text for message in wave)
        # its LEDs are those of the strip afterwards
        assert sent.index(protocol.led(index, Button.SELECT, Led.OFF)) > sent.index(wave[-1])
    assert protocol.lcd_colors([Color.WHITE] * 8) in sent[:first_text]
    assert surface.faders(0)[-1] == protocol.fader_value(0.5)
    colors = [m for m in sent if m.startswith(protocol.SYSEX_HEADER + b"\x72")]
    assert colors[-1] == protocol.lcd_colors([Color.GREEN] * 8)
    assert texts_in_order(surface) == list(range(8))
    assert not surface._lit


async def test_the_show_ends_with_a_flash_and_rings_that_drain(surface: RecordingSurface) -> None:
    surface.shutdown = "show"
    for strip in surface.strips:
        strip.set_color(Color.BLUE)
        strip.set_fader(1.0)
    await surface.settled()
    surface.sent.clear()

    await surface.put_away()

    rings = [m[2] & 0x0F for m in surface.sent if m[:2] == bytes([0xB0, protocol.V_POT_RING_CC + 7])]
    assert rings == [*range(protocol.RING_MAX, 0, -1), 0]
    assert protocol.lcd_colors([*[Color.BLUE] * 7, Color.WHITE]) in surface.sent
    assert surface.meters(0) == [protocol.METER_MAX]
    assert all(strip.color == Color.BLACK and strip.position == 0 for strip in surface.strips)
    assert not surface._lit


async def test_a_device_that_goes_away_ends_the_startup_sequence(
    device: tuple[Path, Path, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface_module, "SEQUENCE_STAGGER", 1.0)
    cards, dev, _ = device
    surface = Surface(proc_asound_cards=cards, dev_snd=dev)
    assert surface.connect()
    revealer = surface._revealer
    assert revealer is not None
    await asyncio.sleep(0)

    assert surface._midi is not None
    surface._midi.close()
    await asyncio.sleep(0)

    assert revealer.cancelled() or revealer.done()
    assert not surface.strips[7].shown


def test_unknown_messages_are_logged(surface: RecordingSurface, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="xtouch_daemon.hardware.surface")

    surface._on_data(bytes([0x90, 0x70, 0x7F]))

    assert "Unknown message from the device: 90 70 7f" in caplog.text


async def test_a_fader_the_device_moves_by_itself_goes_back_to_its_value(surface: RecordingSurface) -> None:
    events: list[protocol.StripEvent] = []
    surface.on_event = events.append
    strip = surface.strips[0]
    strip.set_fader(0.5)
    await surface.settled()

    # after it was switched on, the device moves its faders down: without a touch, no hand did that
    surface._on_data(bytes([0xE0, 0x00, 0x00]))
    await asyncio.sleep(0.01)
    await surface.settled()

    assert events == []
    assert surface.faders(0)[-1] == protocol.fader_value(0.5)
    assert strip.position == protocol.fader_value(0.5)


async def test_a_fader_without_a_value_stays_where_the_device_moved_it(surface: RecordingSurface) -> None:
    surface._on_data(bytes([0xE0, 0x00, 0x00]))
    await asyncio.sleep(0.01)
    await surface.settled()

    assert surface.strips[0].position == 0
    assert surface.faders(0) == []


async def test_a_touch_that_comes_late_makes_the_moves_before_it_count(
    surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface_module, "TOUCH_GRACE", 10.0)
    events: list[protocol.StripEvent] = []
    surface.on_event = events.append
    strip = surface.strips[0]
    strip.set_fader(0.5)
    await surface.settled()
    surface.sent.clear()

    # a quick hand: the device reports the touch after the first moves
    surface._on_data(bytes([0xE0, 0x00, 0x30, 0xE0, 0x00, 0x20]))
    strip.set_fader(0.6)
    await asyncio.sleep(0.05)
    # the motor kept still meanwhile
    assert surface.faders(0) == []
    assert events == []

    surface._on_data(bytes([0x90, 0x68, 0x7F]))
    assert events == [protocol.FaderTouched(0, True), protocol.FaderMoved(0, 0x1000)]
    assert not strip.held


async def test_a_disconnect_forgets_moves_without_a_touch(
    device: tuple[Path, Path, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface_module, "TOUCH_GRACE", 10.0)
    cards, dev, controller = device
    surface = Surface(proc_asound_cards=cards, dev_snd=dev)
    assert surface.connect()
    os.write(controller, bytes([0xE0, 0x00, 0x30]))
    for _ in range(50):
        if surface.strips[0].held:
            break
        await asyncio.sleep(0.01)
    assert surface.strips[0].held

    assert surface._midi is not None
    surface._midi.close()
    await asyncio.sleep(0)

    assert not surface.strips[0].held
    assert surface._unconfirmed == {}


# -- faders without a touch sensor --------------------------------------------------------------------------------


@pytest.fixture
def touchless(surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch) -> list[protocol.StripEvent]:
    """Fader 1 has no working touch sensor; the events of the surface."""
    monkeypatch.setattr(surface_module, "TOUCHLESS_LET_GO", 0.05)
    surface.touchless = frozenset({0})
    events: list[protocol.StripEvent] = []
    surface.on_event = events.append
    return events


async def test_a_move_of_a_touchless_fader_is_a_touch(
    surface: RecordingSurface, touchless: list[protocol.StripEvent]
) -> None:
    strip = surface.strips[0]
    strip.set_fader(0.5)
    await surface.settled()
    surface.sent.clear()

    surface._on_data(bytes([0xE0, 0x00, 0x30]))
    await asyncio.sleep(0.03)
    surface._on_data(bytes([0xE0, 0x00, 0x20]))
    # the volume follows the hand (rounded): the target moves, the motor keeps still
    strip.set_fader(0.3)
    await asyncio.sleep(0.03)
    assert touchless == [
        protocol.FaderTouched(0, True),
        protocol.FaderMoved(0, 0x1800),
        protocol.FaderMoved(0, 0x1000),
    ]
    assert strip.touched
    assert surface.faders(0) == []

    # a pause: the finger is gone, and the fader goes to its target
    await asyncio.sleep(0.05)
    assert touchless[-1] == protocol.FaderTouched(0, False)
    assert not strip.touched
    await surface.settled()
    assert surface.faders(0)[-1] == protocol.fader_value(0.3)

    # the other faders still need a touch
    surface._on_data(bytes([0xE1, 0x00, 0x30]))
    assert len(touchless) == 4
    assert surface.strips[1].held


async def test_a_touch_sensor_that_works_after_all_takes_over(
    surface: RecordingSurface, touchless: list[protocol.StripEvent]
) -> None:
    surface._on_data(bytes([0xE0, 0x00, 0x30]))
    # the touch comes late: the fader is touched already
    surface._on_data(bytes([0x90, 0x68, 0x7F]))
    await asyncio.sleep(0.1)
    assert touchless == [protocol.FaderTouched(0, True), protocol.FaderMoved(0, 0x1800)]
    assert surface.strips[0].touched

    # its release lets go, once
    surface._on_data(bytes([0x90, 0x68, 0x00]))
    await asyncio.sleep(0.1)
    assert touchless[2:] == [protocol.FaderTouched(0, False)]

    # a release without a touch before it ends the touch of the moves too
    surface._on_data(bytes([0xE0, 0x00, 0x30, 0x90, 0x68, 0x00]))
    await asyncio.sleep(0.1)
    assert touchless[3:] == [
        protocol.FaderTouched(0, True),
        protocol.FaderMoved(0, 0x1800),
        protocol.FaderTouched(0, False),
    ]


async def test_moves_right_after_a_connect_are_the_device_s_own(
    device: tuple[Path, Path, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface_module, "TOUCH_GRACE", 10.0)
    monkeypatch.setattr(surface_module, "TOUCHLESS_LET_GO", 10.0)
    cards, dev, controller = device
    surface = Surface(proc_asound_cards=cards, dev_snd=dev)
    surface.touchless = frozenset({0})
    events: list[protocol.StripEvent] = []
    surface.on_event = events.append
    assert surface.connect()

    # after it was switched on, the device moves its faders down: they wait for a touch like the others
    os.write(controller, bytes([0xE0, 0x00, 0x30]))
    for _ in range(50):
        if surface.strips[0].held:
            break
        await asyncio.sleep(0.01)
    assert surface.strips[0].held
    assert events == []

    # later a move is a touch; a disconnect forgets it
    surface._connected_at -= surface_module.TOUCHLESS_STARTUP
    surface._on_data(bytes([0xE1, 0x00, 0x30, 0xE0, 0x00, 0x20]))
    assert surface._fingers.keys() == {0}
    assert surface._midi is not None
    surface._midi.close()
    await asyncio.sleep(0)
    assert surface._fingers == {}


async def test_a_banner_shows_across_the_lcds_and_goes(surface: RecordingSurface):
    surface.strips[3].set_text(0, "Speaker")
    surface.sent.clear()
    surface.banner("Gaming", "steam", 0.02)
    assert surface.strips[3].shown_text == ("    Gam", "    ste")
    assert surface.strips[4].shown_text == ("ing    ", "am     ")
    assert surface.strips[0].shown_text == (" " * 7, " " * 7)
    assert protocol.lcd_text(3, 0, "    Gam") in surface.sent
    # what the strips show meanwhile comes after the banner
    surface.strips[3].set_text(0, "Phones")
    assert protocol.lcd_text(3, 0, "Phones") not in surface.sent
    assert surface.strips[3].text == ["Phones", ""]
    # a connect shows the banner too
    assert protocol.lcd_text(3, 0, "    Gam") in surface.strips[3].connected()
    await asyncio.sleep(0.05)
    assert surface.strips[3].shown_text == ("Phones", "")
    assert protocol.lcd_text(3, 0, "Phones") in surface.sent


async def test_a_new_banner_replaces_the_one_before(surface: RecordingSurface):
    surface.banner("One", "", 10)
    surface.banner("Two", "", 0.01)
    assert surface.strips[3].shown_text[0] == "     Tw"
    await asyncio.sleep(0.03)
    assert surface.strips[3].overlay is None
    # ending it again does nothing
    surface.end_banner()


async def test_the_shutdown_ends_a_banner(surface: RecordingSurface):
    surface.banner("Gaming", "", 10)
    await surface.put_away()
    assert all(strip.overlay is None for strip in surface.strips)


async def test_a_virtual_strip_shows_on_the_strip_it_is_on(surface: RecordingSurface) -> None:
    strip = VirtualStrip(surface, 12)
    strip.set_text(0, "Spotify long")
    strip.set_led(Button.REC, Led.FLASH)
    strip.set_ring(3, RingMode.WRAP)
    strip.set_color(Color.GREEN)
    strip.set_meter(5)
    # on none: nothing goes to the device
    assert surface.sent == []
    assert strip.text[0] == "Spotify"

    target = surface.strips[2]
    strip.bind(target)
    assert (target.text[0], target.leds[Button.REC], target.ring, target.color) == (
        "Spotify",
        Led.FLASH,
        (3, RingMode.WRAP),
        Color.GREEN,
    )
    # a fader it never set goes down
    assert target.fader == 0
    strip.set_meter(7)
    assert surface.meters(2) == [7]
    strip.set_fader(0.5)
    assert target.fader == protocol.fader_value(0.5)

    strip.bind(None)
    strip.set_text(1, "50%")
    assert target.text[1] == ""
