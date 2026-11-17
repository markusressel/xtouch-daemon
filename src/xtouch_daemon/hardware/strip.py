"""
A strip of the device: what it shows (LCD, LEDs, ring, meter) and where its fader is, which glides to its target
like a damped spring. `VirtualStrip` is the strip of a channel, on a slot of the device or off it (see
`runtime/binder.py`).
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Literal

from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode

if TYPE_CHECKING:
    from xtouch_daemon.hardware.surface import Surface

_LOGGER = logging.getLogger(__name__)

type Claimable = Literal["fader", "encoder", "select", "rec", "solo"]
"""
What the controls of a slot (`[controls]`) can take of a strip of the device: the fader, the encoder with its ring,
and the buttons with their LEDs; not Mute, which stays with what the strip shows.
"""
CLAIMABLE_BUTTONS: dict[Button, Claimable] = {Button.REC: "rec", Button.SOLO: "solo", Button.SELECT: "select"}

FADER_TICK = 0.01
FADER_SMOOTH_TIME = 0.1
"""
Motor faders glide to a new position instead of jumping there: they follow their target like a critically damped
spring (no overshoot) that reaches it in about FADER_SMOOTH_TIME. The spring keeps its speed when the target moves on,
so updates that come in steps (a volume dragged elsewhere arrives in 1-2 % steps) become one even movement instead of
a start and stop per step.
"""
FADER_SLOW_SMOOTH_TIME = 0.3
"""
The smooth time of the big moves: a fader that is put away (see `Strip.park()`), e.g. when the daemon stops, and the
first move after a connect. The motors stop short of the bottom after a fast move, a slower one gets there; and the
startup and shutdown sequences look calmer.
"""


FADER_SNAP = 48
FADER_SNAP_SPEED = 2000
"""The fader is put at its target once it is this close (about 0.3 %) and this slow (fader steps per second)."""
FADER_CONFIRM_DELAYS = (0.15, 0.4)
"""
Seconds after a fader arrived at which its target is sent again, in case its motor stopped short of it.
"""
FADER_REST = 0.0
"""
Where a fader is assumed to be when that is not known (after a connect): at the bottom, where the daemon leaves the
faders when it stops and where the device starts with them. So a fader glides there from the start too.
"""


def smooth_damp(position: float, velocity: float, target: float, smooth_time: float, dt: float) -> tuple[float, float]:
    """
    One step of a critically damped spring towards the target: the new position and velocity. The approximation of
    the exponential from "Game Programming Gems 4" (chapter 1.10), as Unity's SmoothDamp uses it.
    """
    omega = 2.0 / smooth_time
    x = omega * dt
    decay = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)
    change = position - target
    temp = (velocity + omega * change) * dt
    velocity = (velocity - omega * temp) * decay
    position = target + (change + temp) * decay
    return position, velocity


class Strip:
    """What one strip shows. Everything is remembered and shown again after a reconnect."""

    def __init__(self, surface: Surface, index: int):
        self._surface = surface
        self.index = index
        self.touched = False
        self.shown = True
        """Whether the device shows the strip: not after a connect until its turn in the startup sequence."""
        self.color = Color.BLACK
        self.text = ["", ""]
        self.leds: dict[Button, Led] = dict.fromkeys(Button, Led.OFF)
        """All of them, so a connect turns off what the device still shows from before (e.g. Select of an app strip)."""
        self.ring: tuple[int, RingMode] = (0, RingMode.DOT)
        self.fader: int | None = None
        """Where the fader should be: None until it is known, so the fader does not move to 0 and back on a connect."""
        self._position: float | None = None
        """Where the fader is: what was sent to the motor last, or where a finger put it."""
        self._velocity = 0.0
        self._slow = False
        """Whether the fader moves slowly (see FADER_SLOW_SMOOTH_TIME) until it arrives."""
        self._confirm_at: list[float] = []
        """When to send the target again (see FADER_CONFIRM_DELAYS)."""
        self.held = False
        """Moved without a touch, waiting for one (see TOUCH_GRACE): the motor keeps still like for a touch."""
        self.overlay: tuple[str, str] | None = None
        """What the LCD shows instead of `text` for a moment (see `Surface.banner()`), None for nothing."""

    @property
    def shown_text(self) -> tuple[str, str]:
        """The two lines the LCD shows: the overlay while there is one, else the text."""
        return self.overlay if self.overlay is not None else (self.text[0], self.text[1])

    def set_overlay(self, lines: tuple[str, str] | None) -> None:
        """Shows the lines on the LCD instead of the text (None: the text again)."""
        before = self.shown_text
        self.overlay = (
            None if lines is None else (lines[0][: protocol.LCD_CELL_WIDTH], lines[1][: protocol.LCD_CELL_WIDTH])
        )
        for line, text in enumerate(self.shown_text):
            if text != before[line]:
                self._send(protocol.lcd_text(self.index, line, text))

    def reset(self) -> None:
        """Dark and empty, the fader at the bottom (e.g. before another strip configuration takes over)."""
        self.set_color(Color.BLACK)
        self.set_text(0, "")
        self.set_text(1, "")
        for button in Button:
            self.set_led(button, Led.OFF)
        self.set_ring(0)
        self.park()

    def park(self) -> None:
        """Puts the fader away: slowly to the bottom (see FADER_SLOW_SMOOTH_TIME)."""
        self.set_fader(0.0, slow=True)

    def set_fader(self, fraction: float, slow: bool = False) -> None:
        """
        Moves the fader to 0.0..1.0, unless a finger is on it: then it moves there when it is let go. A `slow` move
        stays slow until the fader arrived, even when the target changes on the way.
        """
        value = protocol.fader_value(fraction)
        if value != self.fader:
            _LOGGER.debug(f"Fader {self.index + 1}: to {value}{' (touched)' if self.touched else ''}")
        self.fader = value
        self._slow = self._slow or slow
        if not (self.touched or self.held):
            self._surface.glide(self)

    def _send(self, message: bytes) -> None:
        if self.shown:
            self._surface.send(message)

    def reveal(self) -> None:
        """Its turn in the startup sequence: shows everything, and the fader glides to its place."""
        self.shown = True
        for message in self.connected():
            self._surface.send(message)
        self._surface.send_colors()
        if self.fader is not None:
            self._surface.glide(self)

    def set_led(self, button: Button, state: Led) -> None:
        if self.leds.get(button) == state:
            return
        self.leds[button] = state
        self._send(protocol.led(self.index, button, state))

    def set_text(self, line: int, text: str) -> None:
        text = text[: protocol.LCD_CELL_WIDTH]
        if self.text[line] == text:
            return
        self.text[line] = text
        if self.overlay is None:
            self._send(protocol.lcd_text(self.index, line, text))

    def set_ring(self, position: int, mode: RingMode = RingMode.DOT) -> None:
        if self.ring == (position, mode):
            return
        self.ring = (position, mode)
        self._send(protocol.ring(self.index, position, mode))

    def set_color(self, color: Color) -> None:
        if self.color == color:
            return
        self.color = color
        self._surface.send_colors()

    def set_meter(self, level: int) -> None:
        """
        Lights the meter up to 0..METER_MAX. Not shown again after a connect: the device lets it fall by itself, a
        level is held by sending it again.
        """
        self._send(protocol.meter(self.index, level))

    @property
    def position(self) -> int | None:
        """Where the fader is (see `fader` for where it should be), None while that is not known."""
        return None if self._position is None else round(self._position)

    # -- the motor ------------------------------------------------------------------------------------------------

    def touch(self, touched: bool) -> None:
        self.touched = touched
        if not touched and self.fader is not None:
            # back to the value the fader stands for (usually the one that was set last). Also when the hand left it
            # there: let go, the device moves the fader back to the value it got last, from before the touch
            now = asyncio.get_running_loop().time()
            self._confirm_at = [now, *(now + delay for delay in FADER_CONFIRM_DELAYS)]
            self._surface.glide(self)

    def moved_by_hand(self, value: int) -> None:
        self._position = value
        self._velocity = 0.0
        self._slow = False

    def step(self, now: float) -> bool:
        """
        Moves the fader one tick closer to its target, or sends the target again once it is there (see
        FADER_CONFIRM_DELAYS). False once there is nothing left to do. `now` is the time of the event loop.
        """
        if self.touched or self.held or self.fader is None:
            self._confirm_at.clear()
            return False
        if self._position is None:
            # the first move after a connect: from where the fader probably is, slowly
            self._position = FADER_REST
            self._velocity = 0.0
            self._slow = self._position != self.fader
            if not self._slow:
                # assumed to be there already: the target all the same, in case it is not
                self._surface.send(protocol.fader(self.index, self.fader))
                self._confirm_at = [now + delay for delay in FADER_CONFIRM_DELAYS]
                return True
        if self._position == self.fader and self._velocity == 0.0:
            if self._confirm_at and now >= self._confirm_at[0]:
                self._confirm_at.pop(0)
                self._surface.send(protocol.fader(self.index, self.fader))
            return bool(self._confirm_at)
        self._position, self._velocity = smooth_damp(
            self._position,
            self._velocity,
            self.fader,
            FADER_SLOW_SMOOTH_TIME if self._slow else FADER_SMOOTH_TIME,
            FADER_TICK,
        )
        if abs(self.fader - self._position) <= FADER_SNAP and abs(self._velocity) <= FADER_SNAP_SPEED:
            self._position = self.fader
            self._velocity = 0.0
            self._slow = False
            self._confirm_at = [now + delay for delay in FADER_CONFIRM_DELAYS]
        self._surface.send(protocol.fader(self.index, round(self._position)))
        return True

    def connected(self) -> list[bytes]:
        """
        Everything the strip shows, for a device that was just connected. The fader glides to its place from
        FADER_REST (see `reveal()`): a device that was switched off and on again put its faders there before it was
        connected, without telling.
        """
        self.touched = False
        self._position = None
        self._velocity = 0.0
        return [
            *(protocol.led(self.index, button, state) for button, state in self.leds.items()),
            *(protocol.lcd_text(self.index, line, text) for line, text in enumerate(self.shown_text)),
            protocol.ring(self.index, *self.ring),
        ]

    def show_from(self, other: Strip, skip: frozenset[Claimable] = frozenset()) -> None:
        """
        Shows what `other` shows (see `VirtualStrip`): its LCD, LEDs and ring; the fader glides to its value. Not the
        parts in `skip`: a claim shows those.
        """
        self.set_color(other.color)
        for line, text in enumerate(other.text):
            self.set_text(line, text)
        for button, state in other.leds.items():
            if CLAIMABLE_BUTTONS.get(button) not in skip:
                self.set_led(button, state)
        if "encoder" not in skip:
            self.set_ring(*other.ring)
        if "fader" in skip:
            return
        if other.fader is None or other.fader == 0:
            self.park()
        else:
            self.set_fader(protocol.fader_fraction(other.fader))


class VirtualStrip(Strip):
    """
    What the strip of a channel shows, wherever it is: the controller of the channel draws on it, and it passes that
    on to the strip of the device it is on (`target`), if any. A channel that no slot shows is on none, and shows
    everything again when it gets one (`bind()`). Its `index` is its place in the configuration.
    """

    def __init__(self, surface: Surface, index: int):
        super().__init__(surface, index)
        # its own messages never go to the device: those of `target` do
        self.shown = False
        self.target: Strip | None = None
        self.masked: frozenset[Claimable] = frozenset()
        """The parts a claim shows on the strip of the device: kept here, but not passed on."""

    def bind(self, target: Strip | None) -> None:
        """Puts it on the strip of the device (None: on none), which then shows what it shows."""
        self.target = target
        if target is not None:
            target.show_from(self, self.masked)

    def mask(self, parts: frozenset[Claimable]) -> None:
        """Lets a claim show these parts; those it gives back show what this strip shows again."""
        freed = self.masked - parts
        self.masked = parts
        if self.target is None:
            return
        for button, state in self.leds.items():
            if CLAIMABLE_BUTTONS.get(button) in freed:
                self.target.set_led(button, state)
        if "encoder" in freed:
            self.target.set_ring(*self.ring)
        if "fader" in freed and self.fader is not None:
            self.target.set_fader(protocol.fader_fraction(self.fader))

    # what it shows is kept as `Strip` keeps it, but sent to `target` only (its index may be beyond the device's)

    def set_led(self, button: Button, state: Led) -> None:
        self.leds[button] = state
        if self.target is not None and CLAIMABLE_BUTTONS.get(button) not in self.masked:
            self.target.set_led(button, state)

    def set_text(self, line: int, text: str) -> None:
        self.text[line] = text[: protocol.LCD_CELL_WIDTH]
        if self.target is not None:
            self.target.set_text(line, text)

    def set_ring(self, position: int, mode: RingMode = RingMode.DOT) -> None:
        self.ring = (position, mode)
        if self.target is not None and "encoder" not in self.masked:
            self.target.set_ring(position, mode)

    def set_color(self, color: Color) -> None:
        self.color = color
        if self.target is not None:
            self.target.set_color(color)

    def set_fader(self, fraction: float, slow: bool = False) -> None:
        self.fader = protocol.fader_value(fraction)
        if self.target is not None and "fader" not in self.masked:
            self.target.set_fader(fraction, slow)

    def set_meter(self, level: int) -> None:
        if self.target is not None:
            self.target.set_meter(level)
