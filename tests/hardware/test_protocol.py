import pytest

from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led, MessageParser, RingMode, decode


def test_decodes_what_the_device_sent():
    # captured from the device
    assert decode(bytes([0xE1, 0x24, 0x01])) == protocol.FaderMoved(strip=1, value=0x24 | 0x01 << 7)
    assert decode(bytes([0x90, 0x6A, 0x7F])) == protocol.FaderTouched(strip=2, touched=True)
    assert decode(bytes([0x90, 0x6A, 0x00])) == protocol.FaderTouched(strip=2, touched=False)
    assert decode(bytes([0x90, 0x13, 0x7F])) == protocol.ButtonPressed(strip=3, button=Button.MUTE, pressed=True)
    assert decode(bytes([0x90, 0x1B, 0x00])) == protocol.ButtonPressed(strip=3, button=Button.SELECT, pressed=False)
    assert decode(bytes([0x90, 0x00, 0x7F])) == protocol.ButtonPressed(strip=0, button=Button.REC, pressed=True)
    assert decode(bytes([0x90, 0x0F, 0x7F])) == protocol.ButtonPressed(strip=7, button=Button.SOLO, pressed=True)
    assert decode(bytes([0xB0, 0x11, 0x02])) == protocol.EncoderTurned(strip=1, steps=2)
    assert decode(bytes([0xB0, 0x14, 0x41])) == protocol.EncoderTurned(strip=4, steps=-1)
    assert decode(bytes([0x90, 0x22, 0x7F])) == protocol.EncoderPressed(strip=2, pressed=True)
    assert decode(bytes([0x90, 0x22, 0x00])) == protocol.EncoderPressed(strip=2, pressed=False)
    query = bytes.fromhex("f00000661501") + b"015640E5DD9" + bytes([0xF7])
    assert decode(query) == protocol.HostQuery(serial=b"015640E", challenge=b"5DD9")


@pytest.mark.parametrize(
    "message",
    [
        b"",
        bytes([0xE1, 0x24]),  # too short for a fader
        bytes([0x90, 0x70, 0x7F]),  # a note the extender does not have
        bytes([0x90, 0x2A, 0x7F]),  # between the encoder pushes and the fader touches
        bytes([0xB0, 0x30, 0x01]),  # a ring, which only goes to the device
        bytes([0xB0, 0x11]),
        bytes([0xC0, 0x01]),
        bytes.fromhex("f00000661512") + b"text" + bytes([0xF7]),  # not a host query
        bytes.fromhex("f00000661501") + b"short" + bytes([0xF7]),
    ],
)
def test_ignores_messages_that_are_not_used(message: bytes):
    assert decode(message) is None


def test_parser_splits_messages_with_running_status_and_sysex():
    parser = MessageParser()
    messages = parser.feed(bytes([0xE1, 0x24, 0x01, 0x78, 0x01, 0xF0, 0x00, 0x00]))
    messages += parser.feed(bytes([0x66, 0xF7, 0xF8, 0x90, 0x6A]))
    messages += parser.feed(bytes([0x7F]))

    assert messages == [
        bytes([0xE1, 0x24, 0x01]),
        bytes([0xE1, 0x78, 0x01]),
        bytes([0xF0, 0x00, 0x00, 0x66, 0xF7]),
        bytes([0x90, 0x6A, 0x7F]),
    ]


def test_parser_drops_data_without_a_status_and_skips_real_time_bytes():
    parser = MessageParser()
    # data before any status byte means nothing
    assert parser.feed(bytes([0x12, 0x34])) == []
    # clock and active sensing in the middle of a message do not break it
    assert parser.feed(bytes([0x90, 0xF8, 0x10, 0xFE, 0x7F])) == [bytes([0x90, 0x10, 0x7F])]


def test_parser_reads_messages_with_one_data_byte():
    parser = MessageParser()
    assert parser.feed(bytes([0xD0, 0x18, 0x1C, 0xC0, 0x05])) == [
        bytes([0xD0, 0x18]),
        bytes([0xD0, 0x1C]),
        bytes([0xC0, 0x05]),
    ]


def test_a_sysex_ends_the_running_status():
    parser = MessageParser()
    messages = parser.feed(bytes([0x90, 0x10, 0x7F, 0xF0, 0x01, 0xF7, 0x10, 0x7F]))
    assert messages == [bytes([0x90, 0x10, 0x7F]), bytes([0xF0, 0x01, 0xF7])]


def test_encodes_what_was_shown_on_the_device():
    # the messages of the test on the device
    assert protocol.fader(0, 0x3000) == bytes([0xE0, 0x00, 0x60])
    assert protocol.led(0, Button.MUTE, Led.ON) == bytes([0x90, 0x10, 0x7F])
    assert protocol.led(1, Button.MUTE, Led.FLASH) == bytes([0x90, 0x11, 0x01])
    assert protocol.led(7, Button.SELECT, Led.OFF) == bytes([0x90, 0x1F, 0x00])
    assert protocol.ring(1, 6, RingMode.BOOST_CUT) == bytes([0xB0, 0x31, 0x16])
    assert protocol.ring(2, 11, RingMode.WRAP, center=True) == bytes([0xB0, 0x32, 0x40 | 0x20 | 11])
    assert protocol.meter(1, 8) == bytes([0xD0, 0x18])
    assert protocol.lcd_text(1, 0, "haad") == bytes.fromhex("f000006615120768616164202020f7")
    assert protocol.lcd_text(0, 1, "toolongtext")[5:7] == bytes([0x12, 56])
    colors = [Color.RED, Color.GREEN, Color.YELLOW, Color.BLUE, Color.MAGENTA, Color.CYAN, Color.WHITE, Color.RED]
    assert protocol.lcd_colors(colors) == bytes.fromhex("f00000661572010203040506070" + "1f7")


def test_lcd_text_is_cut_to_the_cell_and_non_ascii_is_replaced():
    message = protocol.lcd_text(0, 0, "Grüße und mehr")
    assert message[7:-1] == b"Gr??e u"
    assert len(message) == len(protocol.SYSEX_HEADER) + 2 + protocol.LCD_CELL_WIDTH + 1


def test_values_beyond_the_range_are_clamped():
    assert protocol.fader(0, -5) == protocol.fader(0, 0)
    assert protocol.fader(0, 0x7FFF) == protocol.fader(0, protocol.FADER_MAX)
    assert protocol.meter(0, 20) == protocol.meter(0, protocol.METER_MAX)
    assert protocol.meter(0, -1) == protocol.meter(0, 0)


def test_rejects_what_the_device_does_not_have():
    with pytest.raises(ValueError, match="strip 8"):
        protocol.fader(8, 0)
    with pytest.raises(ValueError, match="strip -1"):
        protocol.led(-1, Button.MUTE, Led.ON)
    with pytest.raises(ValueError, match="ring position 12"):
        protocol.ring(0, 12)
    with pytest.raises(ValueError, match="ring position -1"):
        protocol.ring(0, -1)
    with pytest.raises(ValueError, match="line 2"):
        protocol.lcd_text(0, 2, "x")
    with pytest.raises(ValueError, match="1 colors"):
        protocol.lcd_colors([Color.RED])


def test_fader_fractions_and_values_convert_both_ways():
    assert protocol.fader_value(0.0) == 0
    assert protocol.fader_value(1.0) == protocol.FADER_MAX
    assert protocol.fader_value(1.5) == protocol.FADER_MAX
    assert protocol.fader_value(-0.5) == 0
    assert protocol.fader_fraction(protocol.FADER_MAX) == 1.0
    assert protocol.fader_fraction(protocol.fader_value(0.25)) == pytest.approx(0.25, abs=1e-4)


# -- the other side, for the simulated device ------------------------------------------------------------------------


def test_the_device_reads_what_the_host_sends():
    for strip in range(protocol.STRIPS):
        for value in (0, 1, 0x7F, 0x80, 0x2000, protocol.FADER_MAX):
            assert protocol.decode_host(protocol.fader(strip, value)) == protocol.MotorMoved(strip, value)
        for button in Button:
            for state in Led:
                assert protocol.decode_host(protocol.led(strip, button, state)) == protocol.LedSet(strip, button, state)
        for position in range(protocol.RING_MAX + 1):
            for mode in RingMode:
                for center in (False, True):
                    assert protocol.decode_host(protocol.ring(strip, position, mode, center)) == protocol.RingSet(
                        strip, position, mode, center
                    )
        for level in range(protocol.METER_MAX + 1):
            assert protocol.decode_host(protocol.meter(strip, level)) == protocol.MeterSet(strip, level)
        for line in (0, 1):
            offset = line * protocol.LCD_LINE_LENGTH + strip * protocol.LCD_CELL_WIDTH
            message = protocol.lcd_text(strip, line, "Speaker")
            assert protocol.decode_host(message) == protocol.LcdText(offset, "Speaker")
    colors = list(Color)
    assert protocol.decode_host(protocol.lcd_colors(colors)) == protocol.LcdColors(tuple(colors))
    # any other velocity lights the LED
    assert protocol.decode_host(bytes([0x90, 0x01, 0x40])) == protocol.LedSet(1, Button.REC, Led.ON)


@pytest.mark.parametrize(
    "message",
    [
        b"",
        bytes([0x90, 0x68, 0x7F]),  # a touch is no LED
        bytes([0xB0, 0x10, 0x01]),  # a turn is no ring
        bytes([0x80, 0x00, 0x00]),
        protocol.SYSEX_HEADER + bytes([0x12, protocol.SYSEX_END]),
        protocol.SYSEX_HEADER + bytes([0x72, 1, 2, protocol.SYSEX_END]),
        protocol.SYSEX_HEADER + bytes([0x99, 0, protocol.SYSEX_END]),
        protocol.SYSEX_HEADER + bytes([protocol.SYSEX_END]),
    ],
)
def test_the_device_ignores_what_it_does_not_use(message: bytes):
    assert protocol.decode_host(message) is None


def test_the_host_reads_what_the_device_sends():
    for strip in range(protocol.STRIPS):
        for value in (0, 4, 0x7F, 0x80, protocol.FADER_MAX):
            assert decode(protocol.fader_moved(strip, value)) == protocol.FaderMoved(strip, value)
        for flag in (False, True):
            assert decode(protocol.fader_touched(strip, flag)) == protocol.FaderTouched(strip, flag)
            assert decode(protocol.encoder_pressed(strip, flag)) == protocol.EncoderPressed(strip, flag)
            for button in Button:
                assert decode(protocol.button(strip, button, flag)) == protocol.ButtonPressed(strip, button, flag)
        for steps in (1, 5, 63, -1, -5, -63):
            assert decode(protocol.encoder_turned(strip, steps)) == protocol.EncoderTurned(strip, steps)
    serial, challenge = b"ABCDEFG", b"\x01\x02\x03\x04"
    assert decode(protocol.host_query(serial, challenge)) == protocol.HostQuery(serial, challenge)


def test_the_device_sends_only_what_it_can():
    for steps in (0, 64, -64):
        with pytest.raises(ValueError, match="steps"):
            protocol.encoder_turned(0, steps)
    with pytest.raises(ValueError, match="7 bytes"):
        protocol.host_query(b"short", b"\x00" * 4)
    with pytest.raises(ValueError, match="strip"):
        protocol.button(8, Button.REC, True)
