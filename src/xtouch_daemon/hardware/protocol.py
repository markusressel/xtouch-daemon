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


# -- the other side: the messages to the device as the device reads them, and what it sends -------------------------
# (for the simulated device, see docs/development/design/device-simulator.md)


@dataclass(frozen=True)
class MotorMoved:
    """The host moves the motor of a fader."""

    strip: int
    value: int
    """0..FADER_MAX"""


@dataclass(frozen=True)
class LedSet:
    strip: int
    button: Button
    state: Led


@dataclass(frozen=True)
class RingSet:
    strip: int
    position: int
    """0 (off) or 1..RING_MAX"""
    mode: RingMode
    center: bool


@dataclass(frozen=True)
class MeterSet:
    strip: int
    level: int
    """0..METER_MAX"""


@dataclass(frozen=True)
class LcdText:
    """Characters written into the 2 x LCD_LINE_LENGTH characters of the LCDs, from `offset` on."""

    offset: int
    text: str


@dataclass(frozen=True)
class LcdColors:
    colors: tuple[Color, ...]


type HostEvent = MotorMoved | LedSet | RingSet | MeterSet | LcdText | LcdColors
"""What the host sets on the device."""


def decode_host(message: bytes) -> HostEvent | None:
    """
    One complete MIDI message of the host as the device takes it, None for one it does not use. An LED takes any
    velocity but 0 (off) and 1 (flashing) as on.
    """
    if not message:
        return None
    status = message[0]
    kind = status & 0xF0
    if kind == 0xE0 and len(message) == 3:
        return MotorMoved(status & 0x0F, message[1] | message[2] << 7)
    if status == 0x90 and len(message) == 3 and message[1] < 4 * STRIPS:
        note, velocity = message[1], message[2]
        state = Led.OFF if velocity == 0 else Led.FLASH if velocity == 1 else Led.ON
        return LedSet(note % STRIPS, Button(note - note % STRIPS), state)
    if status == 0xB0 and len(message) == 3 and V_POT_RING_CC <= message[1] < V_POT_RING_CC + STRIPS:
        value = message[2]
        return RingSet(message[1] - V_POT_RING_CC, value & 0x0F, RingMode(value >> 4 & 0x03), bool(value & 0x40))
    if kind == 0xD0 and len(message) == 2:
        return MeterSet(message[1] >> 4, message[1] & 0x0F)
    if message.startswith(SYSEX_HEADER) and message[-1] == SYSEX_END and len(message) > len(SYSEX_HEADER) + 1:
        command, data = message[len(SYSEX_HEADER)], message[len(SYSEX_HEADER) + 1 : -1]
        if command == 0x12 and data:
            return LcdText(data[0], data[1:].decode("ascii", errors="replace"))
        if command == 0x72 and len(data) == STRIPS:
            return LcdColors(tuple(Color(color & 0x07) for color in data))
    return None


def fader_moved(strip: int, value: int) -> bytes:
    """The device: a fader moved to 0..FADER_MAX."""
    _check_strip(strip)
    return bytes([0xE0 | strip, value & 0x7F, value >> 7 & 0x7F])


def fader_touched(strip: int, touched: bool) -> bytes:
    _check_strip(strip)
    return bytes([0x90, FADER_TOUCH_NOTE + strip, 0x7F if touched else 0x00])


def button(strip: int, which: Button, pressed: bool) -> bytes:
    _check_strip(strip)
    return bytes([0x90, which + strip, 0x7F if pressed else 0x00])


def encoder_turned(strip: int, steps: int) -> bytes:
    """Steps 1..63 clockwise, -1..-63 counter-clockwise."""
    _check_strip(strip)
    if not 1 <= abs(steps) <= 0x3F:
        raise ValueError(f"{steps} steps are not 1..63 either way")
    return bytes([0xB0, V_POT_TURN_CC + strip, steps if steps > 0 else 0x40 - steps])


def encoder_pressed(strip: int, pressed: bool) -> bytes:
    _check_strip(strip)
    return bytes([0x90, V_POT_PUSH_NOTE + strip, 0x7F if pressed else 0x00])


def host_query(serial: bytes, challenge: bytes) -> bytes:
    """What the device sends after it started: its serial (7 bytes) and a challenge (4 bytes)."""
    if len(serial) != 7 or len(challenge) != 4:
        raise ValueError("the serial has 7 bytes, the challenge 4")
    return SYSEX_HEADER + b"\x01" + serial + challenge + bytes([SYSEX_END])
