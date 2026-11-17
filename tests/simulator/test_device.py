"""
The simulated device: what the host sets, what a hand does, the motor and meters over time, and its faults.
"""

import pytest

from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode, decode
from xtouch_daemon.simulator.device import METER_FALL, MOTOR_SECONDS, SERIAL, SimulatedDevice


def events(data: bytes) -> list[object]:
    return [decode(message) for message in protocol.MessageParser().feed(data)]


def test_it_shows_what_the_host_sets():
    device = SimulatedDevice()
    before = device.version
    device.receive(
        protocol.lcd_text(2, 0, "Speaker")
        + protocol.lcd_text(2, 1, "80 %")
        + protocol.lcd_colors([Color.CYAN] * protocol.STRIPS)
        + protocol.led(2, Button.MUTE, Led.FLASH)
        + protocol.ring(2, 6, RingMode.SPREAD, center=True)
        + protocol.meter(2, 10)
        + bytes([0x80, 0x00, 0x00]),  # not used
        now=1.0,
    )
    assert device.version > before
    assert device.text(2) == ("Speaker", "80 %   ")
    assert device.text(1) == (" " * 7, " " * 7)
    strip = device.strips[2]
    assert (strip.color, strip.leds[Button.MUTE], strip.ring) == (Color.CYAN, Led.FLASH, (6, RingMode.SPREAD, True))
    # a meter falls by itself
    assert device.meter(2) == 10
    device.advance(1.0 + 3 * METER_FALL + 0.001)
    assert device.meter(2) == 7
    device.advance(10.0)
    assert device.meter(2) == 0


def test_text_past_the_end_is_lost():
    device = SimulatedDevice()
    device.receive(protocol.SYSEX_HEADER + bytes([0x12, 110]) + b"abcdef" + bytes([protocol.SYSEX_END]), now=0.0)
    assert device.lcd[1].endswith("ab")


def test_the_motor_goes_to_its_target_unless_touched():
    device = SimulatedDevice()
    device.receive(protocol.fader(0, protocol.FADER_MAX), now=0.0)
    assert device.advance(MOTOR_SECONDS / 2) == b""  # a motor move is not reported
    assert device.strips[0].fader == pytest.approx(protocol.FADER_MAX / 2)
    device.advance(MOTOR_SECONDS)
    assert device.strips[0].fader == protocol.FADER_MAX
    # a finger holds it; let go, it goes to the value again
    assert events(device.touch(0, True)) == [protocol.FaderTouched(0, True)]
    assert device.touch(0, True) == b""
    device.receive(protocol.fader(0, 0), now=0.2)
    device.advance(1.0)
    assert device.strips[0].fader == protocol.FADER_MAX
    device.touch(0, False)
    device.advance(1.0 + MOTOR_SECONDS / 2)
    assert device.strips[0].fader == pytest.approx(protocol.FADER_MAX / 2)
    device.advance(2.0)
    assert device.strips[0].fader == 0


def test_a_quick_hand_touches_after_its_first_moves():
    device = SimulatedDevice(touch_delay=0.07)
    device.advance(1.0)
    assert events(device.move(1, 0.5)) == [protocol.FaderMoved(1, protocol.fader_value(0.5) // 4 * 4)]
    device.move(1, 0.6)
    assert device.advance(1.05) == b""
    assert events(device.advance(1.08)) == [protocol.FaderTouched(1, True)]
    assert device.strips[1].touched
    # the motor doesn't pull it back while it is touched
    assert device.strips[1].fader == protocol.fader_value(0.6)
    # without a hand (the device itself, or Alt-drag), no touch follows
    device.move(2, 0.3, hand=False)
    assert device.advance(2.0) == b""


def test_a_broken_touch_sensor_never_reports_a_touch():
    device = SimulatedDevice(broken_touch={0})
    assert device.touch(0, True) == b""
    device.move(0, 0.5)
    assert device.advance(1.0) == b""
    # the motor stays still: nothing moves it back
    assert device.strips[0].fader == protocol.fader_value(0.5)


def test_buttons_and_encoders():
    device = SimulatedDevice()
    assert events(device.press(3, Button.SOLO, True)) == [protocol.ButtonPressed(3, Button.SOLO, True)]
    assert events(device.turn(3, -2)) == [protocol.EncoderTurned(3, -2)]
    assert events(device.push(3, True)) == [protocol.EncoderPressed(3, True)]
    assert device.strips[3].pushed


def test_switched_off_and_on():
    device = SimulatedDevice()
    assert events(device.hello()) == [protocol.HostQuery(SERIAL, b"\x00" * 4)]
    device.receive(protocol.lcd_text(0, 0, "Mic") + protocol.fader(0, 0x2000), now=0.0)
    device.advance(1.0)
    assert events(device.power_cycle()) == [protocol.HostQuery(SERIAL, b"\x00" * 4)]
    assert device.text(0) == (" " * 7, " " * 7)
    # the faders go down by themselves, and say so (without a touch)
    moves = events(device.advance(1.0 + MOTOR_SECONDS))
    assert moves
    assert all(isinstance(event, protocol.FaderMoved) and event.strip == 0 for event in moves)
    assert device.strips[0].fader == 0
    # the host takes over again: its motor moves are not reported
    device.receive(protocol.fader(0, 0x1000), now=2.0)
    assert device.advance(3.0) == b""


def test_a_mirror_takes_what_the_device_reported():
    mirror = SimulatedDevice()
    mirror.forget_faders()
    assert not mirror.strips[1].known

    before = mirror.version
    mirror.observe(
        protocol.fader_touched(1, True)
        + protocol.fader_moved(1, 4092)
        + protocol.encoder_pressed(2, True)
        + protocol.button(3, Button.MUTE, True)
        + protocol.host_query(SERIAL, b"\x00\x00\x00\x00"),
        now=1.0,
    )
    assert mirror.version > before
    assert mirror.strips[1].known
    assert (mirror.strips[1].fader, mirror.strips[1].touched) == (4092, True)
    assert mirror.strips[2].pushed

    # let go, the motor goes back to the value the host set
    mirror.receive(protocol.fader(1, 8192), now=1.0)
    mirror.observe(protocol.fader_touched(1, False), now=1.0)
    mirror.advance(1.0 + MOTOR_SECONDS)
    assert mirror.strips[1].fader == 8192
