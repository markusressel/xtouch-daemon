"""
The simulated device: what the host sets on it (texts, colors, LEDs, rings, meters, motors) and what a hand does on
it (touch and move faders, press buttons, turn and push encoders), as the bytes the real device takes and sends. Pure:
no IO, no asyncio, no Qt; the time comes in as `now` (seconds), so frontends and tests drive it.

What it does is verified on the device (see docs/hardware.md), except these assumptions:

- the motor goes to its target at a fixed speed, `MOTOR_SECONDS` over the whole range;
- a meter falls by one level every `METER_FALL` seconds after it was set (as the live view assumed);
- a quick hand's touch comes `touch_delay` seconds after its first move (the device: 50-100 ms);
- after switching on, the faders go down by themselves, reporting their moves without a touch.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import (
    Button,
    Color,
    LcdColors,
    LcdText,
    Led,
    LedSet,
    MessageParser,
    MeterSet,
    MotorMoved,
    RingMode,
    RingSet,
)

MOTOR_SECONDS = 0.1
"""How long the motor takes over the whole range (an assumption)."""
METER_FALL = 0.15
"""Seconds per level a meter falls (an assumption)."""
TOUCH_DELAY = 0.07
"""Seconds after the first move of a quick hand until the touch is reported."""
REPORT_STEP = 4
"""The device reports fader positions in multiples of 4."""
SERIAL = b"SIM0001"


@dataclass
class SimulatedStrip:
    color: Color = Color.BLACK
    leds: dict[Button, Led] = field(default_factory=lambda: dict.fromkeys(Button, Led.OFF))
    ring: tuple[int, RingMode, bool] = (0, RingMode.DOT, False)
    """Position, mode and the center LED."""
    meter: int = 0
    meter_at: float = 0.0
    """When the meter was set; it falls from there."""
    fader: float = 0.0
    """Where the fader is, 0..FADER_MAX."""
    target: int = 0
    """Where the motor goes (the value the host set last)."""
    moving: bool = False
    """Whether the motor runs: after the host set a value, and when a finger lets go; it stops where it arrives."""
    reporting: bool = False
    """Whether the motor's moves are reported, as after switching on (they aren't otherwise)."""
    touched: bool = False
    touch_due: float | None = None
    """When the touch of a hand that moves the fader is reported, None for none coming."""
    pushed: bool = False

    def meter_at_time(self, now: float) -> int:
        return max(0, self.meter - int((now - self.meter_at) / METER_FALL))


class SimulatedDevice:
    def __init__(self, broken_touch: Iterable[int] = (), touch_delay: float = TOUCH_DELAY):
        self.broken_touch = set(broken_touch)
        """The strips (from 0) whose touch sensor failed: they never report a touch."""
        self.touch_delay = touch_delay
        self.strips = [SimulatedStrip() for _ in range(protocol.STRIPS)]
        self.lcd = [" " * protocol.LCD_LINE_LENGTH, " " * protocol.LCD_LINE_LENGTH]
        """The two lines of characters across all strips."""
        self.version = 0
        """Counts the changes, for frontends to paint again."""
        self._parser = MessageParser()
        self._now = 0.0

    # -- what the host sends ----------------------------------------------------------------------------------------

    def receive(self, data: bytes, now: float) -> None:
        """Takes bytes from the host."""
        self.advance(now)
        for message in self._parser.feed(data):
            match protocol.decode_host(message):
                case MotorMoved(strip=strip, value=value):
                    self.strips[strip].target = value
                    self.strips[strip].moving = True
                    self.strips[strip].reporting = False
                case LedSet(strip=strip, button=button, state=state):
                    self.strips[strip].leds[button] = state
                case RingSet(strip=strip, position=position, mode=mode, center=center):
                    self.strips[strip].ring = (position, mode, center)
                case MeterSet(strip=strip, level=level):
                    self.strips[strip].meter, self.strips[strip].meter_at = level, now
                case LcdText(offset=offset, text=text):
                    self._write(offset, text)
                case LcdColors(colors=colors):
                    for strip, color in zip(self.strips, colors, strict=True):
                        strip.color = color
                case _:
                    # a message the device does not use
                    continue
            self.version += 1

    def _write(self, offset: int, text: str) -> None:
        """Characters from `offset` on, across the two lines like the device (past the end they are lost)."""
        whole = "".join(self.lcd)
        end = min(len(whole), offset + len(text))
        whole = whole[:offset] + text[: end - offset] + whole[end:]
        self.lcd = [whole[: protocol.LCD_LINE_LENGTH], whole[protocol.LCD_LINE_LENGTH :]]

    def text(self, strip: int) -> tuple[str, str]:
        """The two lines of a strip's LCD."""
        start = strip * protocol.LCD_CELL_WIDTH
        return (
            self.lcd[0][start : start + protocol.LCD_CELL_WIDTH],
            self.lcd[1][start : start + protocol.LCD_CELL_WIDTH],
        )

    # -- time -------------------------------------------------------------------------------------------------------

    def advance(self, now: float) -> bytes:
        """Lets time pass: the motors move, touches of moving hands arrive. Returns what the device sends."""
        elapsed, self._now = max(0.0, now - self._now), max(now, self._now)
        sent = bytearray()
        for index, strip in enumerate(self.strips):
            if strip.touch_due is not None and now >= strip.touch_due:
                strip.touch_due = None
                strip.touched = True
                sent += protocol.fader_touched(index, True)
                self.version += 1
            if strip.touched or not strip.moving:
                continue
            step = protocol.FADER_MAX * elapsed / MOTOR_SECONDS
            before = self._reported(strip.fader)
            if abs(strip.target - strip.fader) <= step:
                strip.fader = strip.target
                strip.moving = False
            else:
                strip.fader += step if strip.target > strip.fader else -step
            self.version += 1
            if strip.reporting and self._reported(strip.fader) != before:
                sent += protocol.fader_moved(index, self._reported(strip.fader))
        return bytes(sent)

    @staticmethod
    def _reported(position: float) -> int:
        return round(position) // REPORT_STEP * REPORT_STEP

    def meter(self, strip: int) -> int:
        """The level a meter shows now."""
        return self.strips[strip].meter_at_time(self._now)

    # -- what a hand does --------------------------------------------------------------------------------------------

    def touch(self, strip: int, touched: bool) -> bytes:
        """A finger on a fader (or off it: the motor goes to the strip's value again)."""
        state = self.strips[strip]
        state.touch_due = None
        if strip in self.broken_touch or state.touched == touched:
            return b""
        state.touched = touched
        # let go, it goes to the strip's value
        state.moving = not touched
        self.version += 1
        return protocol.fader_touched(strip, touched)

    def move(self, strip: int, fraction: float, hand: bool = True) -> bytes:
        """
        A fader moved to `fraction` (0..1). By a hand that does not touch it yet (`hand`), the touch follows after
        `touch_delay`, as with a quick hand; without (`hand=False`: Alt-drag, or the device itself) none follows.
        """
        state = self.strips[strip]
        state.fader = float(protocol.fader_value(fraction))
        state.moving = state.reporting = False
        if hand and not state.touched and state.touch_due is None and strip not in self.broken_touch:
            state.touch_due = self._now + self.touch_delay
        self.version += 1
        return protocol.fader_moved(strip, self._reported(state.fader))

    def press(self, strip: int, button: Button, pressed: bool) -> bytes:
        return protocol.button(strip, button, pressed)

    def turn(self, strip: int, steps: int) -> bytes:
        return protocol.encoder_turned(strip, steps)

    def push(self, strip: int, pressed: bool) -> bytes:
        self.strips[strip].pushed = pressed
        self.version += 1
        return protocol.encoder_pressed(strip, pressed)

    # -- the device as a whole ---------------------------------------------------------------------------------------

    def hello(self) -> bytes:
        """What the device sends when a host connects: its query."""
        return protocol.host_query(SERIAL, b"\x00\x00\x00\x00")

    def power_cycle(self) -> bytes:
        """
        Switched off and on: texts, colors, LEDs, rings and meters are gone, the device asks for a host, and the
        faders go down by themselves, reporting their moves (without a touch).
        """
        self.lcd = [" " * protocol.LCD_LINE_LENGTH, " " * protocol.LCD_LINE_LENGTH]
        # the faders stay where they are, and go down from there; the motor targets the bottom
        self.strips = [
            SimulatedStrip(fader=state.fader, touched=state.touched, moving=True, reporting=True)
            for state in self.strips
        ]
        self.version += 1
        return self.hello()
