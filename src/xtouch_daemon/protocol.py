"""
The Mackie Control protocol of a Behringer X-Touch Extender in "MC" mode (an MCU XT, model id 0x15), as far as it is
used here. Verified on the device (2026-11-15): faders, fader touch, buttons, encoder turns, LEDs, rings, meters, LCD
text and colors, and the host query. Not verified yet: the encoder push notes (the standard of the MCU).

Pure functions: decoding the MIDI messages of the device into events, and building the messages that drive it.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum

STRIPS = 8

SYSEX_START = 0xF0
SYSEX_END = 0xF7
SYSEX_HEADER = bytes([SYSEX_START, 0x00, 0x00, 0x66, 0x15])
"""Mackie's manufacturer id and the model id of the MCU XT (an extender)."""

FADER_MAX = 0x3FFF
"""Faders are pitch bend: 14 bits."""

LCD_LINE_LENGTH = 56
LCD_CELL_WIDTH = 7
"""The two lines of the LCD are 56 characters each, 7 per strip."""

METER_MAX = 14
"""
Meter levels 0..14, as measured on the device: one more of its 8 LEDs every two levels (1 and 2 light one, 9 and 10
five), 11 lights six, 12 and 13 seven, 14 all eight, the red clip LED at the top too. 15 lights none. The device
lets every level fall back by itself, also 14: it does not hold the clip LED (Mackie Control's "overload").
"""
METER_SIGNAL_MAX = 12
"""The loudest level of audio that does not clip: seven LEDs, the red one stays dark."""

RING_MAX = 11
"""Ring positions 1..11 (0 switches the ring off)."""

FADER_TOUCH_NOTE = 0x68


class Button(IntEnum):
    """The four buttons of a strip: the note of strip 0, the strips follow each other."""

    REC = 0x00
    SOLO = 0x08
    MUTE = 0x10
    SELECT = 0x18


V_POT_PUSH_NOTE = 0x20
V_POT_TURN_CC = 0x10
V_POT_RING_CC = 0x30


class Led(Enum):
    OFF = 0x00
    FLASH = 0x01
    ON = 0x7F


class RingMode(IntEnum):
    DOT = 0
    BOOST_CUT = 1
    WRAP = 2
    SPREAD = 3


class Color(IntEnum):
    """The backlight colors of an LCD (a Behringer extension of the protocol)."""

    BLACK = 0
    RED = 1
    GREEN = 2
    YELLOW = 3
    BLUE = 4
    MAGENTA = 5
    CYAN = 6
    WHITE = 7


# -- events from the device --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FaderMoved:
    strip: int
    value: int
    """0..FADER_MAX"""


@dataclass(frozen=True)
class FaderTouched:
    strip: int
    touched: bool


@dataclass(frozen=True)
class ButtonPressed:
    strip: int
    button: Button
    pressed: bool


@dataclass(frozen=True)
class EncoderTurned:
    strip: int
    steps: int
    """Positive clockwise, negative counter-clockwise; faster turns send more steps at once."""


@dataclass(frozen=True)
class EncoderPressed:
    strip: int
    pressed: bool


@dataclass(frozen=True)
class HostQuery:
    """The device asks for a host (it sends this on its own after it started)."""

    serial: bytes
    challenge: bytes


type StripEvent = FaderMoved | FaderTouched | ButtonPressed | EncoderTurned | EncoderPressed
"""What happens on a strip."""
type Event = StripEvent | HostQuery


def decode(message: bytes) -> Event | None:
    """One complete MIDI message of the device as an event, or None for messages that are not used."""
    if not message:
        return None
    status = message[0]
    kind = status & 0xF0
    if kind == 0xE0 and len(message) == 3:
        return FaderMoved(strip=status & 0x0F, value=message[1] | message[2] << 7)
    if kind == 0x90 and len(message) == 3:
        note, pressed = message[1], message[2] != 0
        if FADER_TOUCH_NOTE <= note < FADER_TOUCH_NOTE + STRIPS:
            return FaderTouched(strip=note - FADER_TOUCH_NOTE, touched=pressed)
        if V_POT_PUSH_NOTE <= note < V_POT_PUSH_NOTE + STRIPS:
            return EncoderPressed(strip=note - V_POT_PUSH_NOTE, pressed=pressed)
        if note < 4 * STRIPS:
            return ButtonPressed(strip=note % STRIPS, button=Button(note - note % STRIPS), pressed=pressed)
        return None
    if kind == 0xB0 and len(message) == 3 and V_POT_TURN_CC <= message[1] < V_POT_TURN_CC + STRIPS:
        value = message[2]
        steps = value if value < 0x40 else -(value - 0x40)
        return EncoderTurned(strip=message[1] - V_POT_TURN_CC, steps=steps)
    if message.startswith(SYSEX_HEADER + b"\x01") and message[-1] == SYSEX_END and len(message) == 18:
        return HostQuery(serial=message[6:13], challenge=message[13:17])
    return None


class MessageParser:
    """Splits the bytes read from the device into complete MIDI messages (with running status)."""

    def __init__(self):
        self._status: int | None = None
        self._data = bytearray()
        self._sysex: bytearray | None = None

    def feed(self, data: bytes) -> list[bytes]:
        messages = []
        for byte in data:
            if self._sysex is not None:
                self._sysex.append(byte)
                if byte == SYSEX_END:
                    messages.append(bytes(self._sysex))
                    self._sysex = None
                continue
            if byte == SYSEX_START:
                self._sysex = bytearray([byte])
                self._status = None
                continue
            if byte >= 0xF8:
                # real time messages (clock, active sensing) may come in between, they are not used
                continue
            if byte & 0x80:
                self._status = byte
                self._data.clear()
                continue
            if self._status is None:
                continue
            self._data.append(byte)
            if len(self._data) == _data_length(self._status):
                messages.append(bytes([self._status, *self._data]))
                self._data.clear()
        return messages


def _data_length(status: int) -> int:
    return 1 if status & 0xF0 in (0xC0, 0xD0) else 2


# -- messages to the device --------------------------------------------------------------------------------------


def _check_strip(strip: int) -> None:
    if not 0 <= strip < STRIPS:
        raise ValueError(f"strip {strip} is not 0..{STRIPS - 1}")


def fader(strip: int, value: int) -> bytes:
    """Moves the motor fader to 0..FADER_MAX."""
    _check_strip(strip)
    value = max(0, min(FADER_MAX, value))
    return bytes([0xE0 | strip, value & 0x7F, value >> 7])


def led(strip: int, button: Button, state: Led) -> bytes:
    _check_strip(strip)
    return bytes([0x90, button + strip, state.value])


def ring(strip: int, position: int, mode: RingMode = RingMode.DOT, center: bool = False) -> bytes:
    """Lights the LED ring of an encoder: position 0 (off) or 1..RING_MAX."""
    _check_strip(strip)
    if not 0 <= position <= RING_MAX:
        raise ValueError(f"ring position {position} is not 0..{RING_MAX}")
    return bytes([0xB0, V_POT_RING_CC + strip, (0x40 if center else 0) | mode << 4 | position])


def meter(strip: int, level: int) -> bytes:
    """Lights the meter up to 0..METER_MAX. The device lets it fall back by itself, so it has to be sent again."""
    _check_strip(strip)
    level = max(0, min(METER_MAX, level))
    return bytes([0xD0, strip << 4 | level])


def lcd_text(strip: int, line: int, text: str) -> bytes:
    """The text of one strip on line 0 (top) or 1 (bottom): up to LCD_CELL_WIDTH characters of ASCII."""
    _check_strip(strip)
    if line not in (0, 1):
        raise ValueError(f"line {line} is not 0 or 1")
    cell = text[:LCD_CELL_WIDTH].ljust(LCD_CELL_WIDTH)
    data = cell.encode("ascii", errors="replace")
    return SYSEX_HEADER + bytes([0x12, line * LCD_LINE_LENGTH + strip * LCD_CELL_WIDTH]) + data + bytes([SYSEX_END])


def lcd_colors(colors: list[Color]) -> bytes:
    """The backlight colors of all strips at once."""
    if len(colors) != STRIPS:
        raise ValueError(f"{len(colors)} colors given, the device has {STRIPS} strips")
    return SYSEX_HEADER + bytes([0x72, *colors]) + bytes([SYSEX_END])


def fader_value(fraction: float) -> int:
    """A position 0.0..1.0 as a fader value."""
    return round(max(0.0, min(1.0, fraction)) * FADER_MAX)


def fader_fraction(value: int) -> float:
    return value / FADER_MAX
