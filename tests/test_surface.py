import asyncio
import contextlib
import logging
import os
import tty
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.conftest import RecordingSurface
from xtouch_daemon import protocol
from xtouch_daemon import surface as surface_module
from xtouch_daemon.protocol import Button, Color, Led, RingMode
from xtouch_daemon.surface import FADER_SMOOTH_TIME, FADER_TICK, Strip, Surface, smooth_damp

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
    monkeypatch.setattr(surface_module, "FADER_CONFIRM_DELAYS", (0.02, 0.05))
    strip = surface.strips[0]
    loop = asyncio.get_running_loop()
    strip.set_fader(0.5)
    await arrival(strip)
    arrived = loop.time()
    count = len(surface.faders(0))

    await surface.settled()

    # the motor of the device may have stopped short of it: the target again, twice
    assert surface.faders(0)[count:] == [protocol.fader_value(0.5)] * 2
    assert loop.time() - arrived >= 0.05


async def test_a_touched_fader_gets_no_target_again(surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(surface_module, "FADER_CONFIRM_DELAYS", (0.05,))
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

    surface._on_data(bytes([0xE1, 0x7F, 0x7F, 0x90, 0x11, 0x7F, 0xB0, 0x12, 0x41, 0x90, 0x23, 0x7F]))

    assert events == [
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
    monkeypatch.setattr(surface_module, "FADER_SLOW_SMOOTH_TIME", 0.2)
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
    monkeypatch.setattr(surface_module, "FADER_SLOW_SMOOTH_TIME", 0.2)
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


async def test_a_slow_move_stays_slow_until_the_fader_arrived(
    surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface_module, "FADER_SLOW_SMOOTH_TIME", 0.2)
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
