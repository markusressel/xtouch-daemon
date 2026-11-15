"""
The X-Touch Extender as a surface: what each of its 8 strips shows, and the connection to the device.

The surface remembers everything a strip shows, so it shows it again after the device was switched off and on or
plugged in again, sends only what changed, keeps the motor of a fader still while a finger is on it, and moves the
motor faders smoothly. What happens on the device (fader moves, touches, buttons, encoders) goes to `on_event`.
"""

import asyncio
import logging
import math
import time
from collections.abc import Callable
from pathlib import Path

from xtouch_daemon import protocol
from xtouch_daemon.midi import DEV_SND, PROC_ASOUND_CARDS, RawMidi, find_card
from xtouch_daemon.protocol import Button, Color, Led, RingMode

_LOGGER = logging.getLogger(__name__)

DEVICE_NAME = "X-Touch-Ext"
SCAN_INTERVAL = 2.0
"""How often the sound cards are checked for the device while it is not connected."""

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
SEQUENCE_STAGGER = 0.08
"""Seconds between the strips of the startup and shutdown sequences (see `Surface.open()` and `Surface.put_away()`)."""
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

TOUCH_GRACE = 0.3
"""
Seconds a fader that moved without a touch waits for one. The device reports a touch only after the first few moves
of a quick hand (about 50-100 ms late), so such a move is held without driving the motor: with a touch it was the
hand, without one the device itself (e.g. its faders going down after it was switched on), and the fader goes back to
its value.
"""

TOUCHLESS_LET_GO = 0.5
"""
Seconds without a move after which the finger counts as gone from a fader without a working touch sensor (see
`Surface.touchless`).
"""
TOUCHLESS_STARTUP = 3.0
"""
Seconds after a connect in which a move of a fader without a working touch sensor does not count as a hand: after it was
switched on, the device moves its faders down by itself. Such moves are handled like those of the other faders (see
TOUCH_GRACE).
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
        self.meter: tuple[int, float] = (0, 0.0)
        """The level the meter was set to last, and when (`time.monotonic()`), for the live view of the GUI."""

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
        self.fader = protocol.fader_value(fraction)
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
        self.meter = (level, time.monotonic())
        self._send(protocol.meter(self.index, level))

    @property
    def position(self) -> int | None:
        """Where the fader is (see `fader` for where it should be), None while that is not known."""
        return None if self._position is None else round(self._position)

    # -- the motor ------------------------------------------------------------------------------------------------

    def touch(self, touched: bool) -> None:
        self.touched = touched
        if not touched and self.fader is not None:
            # back to the value the fader stands for (usually the one that was set last)
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
            *(protocol.lcd_text(self.index, line, text) for line, text in enumerate(self.text)),
            protocol.ring(self.index, *self.ring),
        ]


type EventHandler = Callable[[protocol.StripEvent], None]
type ConnectionHandler = Callable[[bool], None]


class Surface:
    """
    A Behringer X-Touch Extender in "MC" mode on USB, found by the name of its sound card. `run()` connects to it,
    and connects again whenever it was unplugged or switched off.
    """

    def __init__(
        self,
        device_name: str = DEVICE_NAME,
        proc_asound_cards: Path = PROC_ASOUND_CARDS,
        dev_snd: Path = DEV_SND,
    ):
        self.device_name = device_name
        self.touchless: frozenset[int] = frozenset()
        """
        The strips (from 0) whose fader has no working touch sensor: a move counts as a touch, a pause of
        TOUCHLESS_LET_GO as letting go.
        """
        self.proc_asound_cards = proc_asound_cards
        self.dev_snd = dev_snd
        self.strips = [Strip(self, index) for index in range(protocol.STRIPS)]
        self.on_event: EventHandler = lambda event: None
        self.on_connection: ConnectionHandler = lambda connected: None
        self._unconfirmed: dict[int, tuple[int, asyncio.TimerHandle]] = {}
        """The faders that moved without a touch: where to, and the timer that gives up waiting (TOUCH_GRACE)."""
        self._fingers: dict[int, asyncio.TimerHandle] = {}
        """The touchless faders a finger moves, with the timer that lets go of them (TOUCHLESS_LET_GO)."""
        self._connected_at = -math.inf
        """When the device was connected last (the time of the event loop), see TOUCHLESS_STARTUP."""
        self.on_unknown: Callable[[bytes], None] = lambda message: _LOGGER.debug(
            f"Unknown message from the device: {message.hex(' ')}"
        )
        """For the messages the daemon doesn't use: to find out what a device sends."""
        self._midi: RawMidi | None = None
        self._parser = protocol.MessageParser()
        self._disconnected = asyncio.Event()
        self._gliding: set[Strip] = set()
        self._glider: asyncio.Task[None] | None = None
        self._revealer: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._midi is not None

    # -- sending ------------------------------------------------------------------------------------------------

    def send(self, message: bytes) -> None:
        if self._midi is not None:
            self._midi.write(message)

    def send_colors(self) -> None:
        self.send(protocol.lcd_colors([strip.color if strip.shown else Color.BLACK for strip in self.strips]))

    def glide(self, strip: Strip) -> None:
        """Moves the fader of the strip to its target smoothly (see FADER_SMOOTH_TIME)."""
        if not strip.shown:
            # it moves when its turn in the startup sequence comes
            return
        self._gliding.add(strip)
        if self._glider is None or self._glider.done():
            self._glider = asyncio.create_task(self._glide(), name="fader motors")

    async def _glide(self) -> None:
        loop = asyncio.get_running_loop()
        while self._gliding:
            now = loop.time()
            for strip in list(self._gliding):
                if not strip.step(now):
                    self._gliding.discard(strip)
            if self._gliding:
                await asyncio.sleep(FADER_TICK)

    async def settled(self) -> None:
        """Waits until the startup sequence is done and the faders are where they should be."""
        if self._revealer is not None and not self._revealer.done():
            await self._revealer
        while self._glider is not None and not self._glider.done():
            await self._glider

    async def put_away(self) -> None:
        """The shutdown sequence: from the right, one strip after the other goes dark and puts its fader away."""
        for index, strip in enumerate(reversed(self.strips)):
            if index:
                await asyncio.sleep(SEQUENCE_STAGGER)
            strip.reset()
        await self.settled()

    async def _reveal(self) -> None:
        for index, strip in enumerate(self.strips):
            if index:
                await asyncio.sleep(SEQUENCE_STAGGER)
            strip.reveal()

    # -- connection ---------------------------------------------------------------------------------------------

    async def run(self) -> None:
        announced_missing = False
        try:
            while True:
                if not self.connect():
                    if not announced_missing:
                        _LOGGER.warning(f"{self.device_name} is not connected, waiting for it")
                        announced_missing = True
                    await asyncio.sleep(SCAN_INTERVAL)
                    continue
                announced_missing = False
                await self._disconnected.wait()
                _LOGGER.warning(f"{self.device_name} is gone, waiting for it to come back")
                announced_missing = True
        finally:
            await self.close()

    def connect(self) -> bool:
        """Connects to the device if it is there. False if it is not (or can't be opened)."""
        try:
            self.open()
        except LookupError:
            return False
        except OSError as e:
            _LOGGER.error(f"Can't open {self.device_name}: {e}")
            return False
        return True

    def open(self) -> None:
        """
        Connects to the device and shows everything on it. LookupError if it is not there, OSError if it can't be
        opened (e.g. another program has it open).
        """
        cards = self.proc_asound_cards.read_text()
        card = find_card(cards, self.device_name)
        if card is None:
            raise LookupError(f"{self.device_name} is not connected")
        path = self.dev_snd / f"midiC{card}D0"
        self._midi = RawMidi(path, on_data=self._on_data, on_closed=self._on_closed)
        self._disconnected.clear()
        self._connected_at = asyncio.get_running_loop().time()
        self._parser = protocol.MessageParser()
        _LOGGER.info(f"Connected to {self.device_name} at {path}")
        # the startup sequence: dark at first, then from the left one strip after the other lights up
        for strip in self.strips:
            strip.shown = False
        self.send_colors()
        self._revealer = asyncio.create_task(self._reveal(), name="startup sequence")
        self.on_connection(True)

    async def close(self) -> None:
        """Sends what is still on its way and closes the device."""
        midi = self._midi
        if midi is None:
            return
        await midi.drain()
        midi.close()

    def _on_closed(self) -> None:
        assert self._revealer is not None, "open() starts the startup sequence"
        self._revealer.cancel()
        for index, (_, timer) in self._unconfirmed.items():
            timer.cancel()
            self.strips[index].held = False
        self._unconfirmed.clear()
        for timer in self._fingers.values():
            timer.cancel()
        self._fingers.clear()
        self._midi = None
        self._disconnected.set()
        self.on_connection(False)

    def _on_data(self, data: bytes) -> None:
        for message in self._parser.feed(data):
            event = protocol.decode(message)
            if event is None:
                self.on_unknown(message)
                continue
            if isinstance(event, protocol.HostQuery):
                continue
            strip = self.strips[event.strip]
            match event:
                case protocol.FaderMoved(strip=index) if not strip.touched and self._move_is_touch(index):
                    # no touch sensor: the move is the touch
                    self._fingers[index] = self._let_go_later(index)
                    self._handle(protocol.FaderTouched(index, True))
                case protocol.FaderMoved(strip=index) if index in self._fingers:
                    # the finger is still there
                    self._fingers[index].cancel()
                    self._fingers[index] = self._let_go_later(index)
                case protocol.FaderTouched(strip=index, touched=touched) if index in self._fingers:
                    # the sensor works after all: from now on it tells when the finger is gone
                    self._fingers.pop(index).cancel()
                    if touched:
                        continue
                case protocol.FaderMoved(strip=index, value=value) if not strip.touched:
                    # a hand or the device itself: the touch tells (see TOUCH_GRACE)
                    strip.moved_by_hand(value)
                    strip.held = True
                    if index in self._unconfirmed:
                        self._unconfirmed[index][1].cancel()
                    timer = asyncio.get_running_loop().call_later(TOUCH_GRACE, self._untouched, index)
                    self._unconfirmed[index] = (value, timer)
                    continue
                case protocol.FaderTouched(strip=index, touched=True) if index in self._unconfirmed:
                    # the hand that moved it: what it did so far counts
                    value, timer = self._unconfirmed.pop(index)
                    timer.cancel()
                    strip.held = False
                    self._handle(event)
                    self._handle(protocol.FaderMoved(index, value))
                    continue
            self._handle(event)

    def _move_is_touch(self, index: int) -> bool:
        """Whether a move of the fader without a touch counts as one (see `touchless`)."""
        loop = asyncio.get_running_loop()
        return index in self.touchless and loop.time() >= self._connected_at + TOUCHLESS_STARTUP

    def _let_go_later(self, index: int) -> asyncio.TimerHandle:
        return asyncio.get_running_loop().call_later(TOUCHLESS_LET_GO, self._let_go, index)

    def _let_go(self, index: int) -> None:
        """A touchless fader stopped moving: the finger is gone."""
        del self._fingers[index]
        self._handle(protocol.FaderTouched(index, False))

    def _untouched(self, index: int) -> None:
        """No touch came: the device moved the fader, which goes back to its value."""
        del self._unconfirmed[index]
        strip = self.strips[index]
        strip.held = False
        _LOGGER.debug(f"Fader {index + 1} moved without a touch: back to its value")
        if strip.fader is not None:
            self.glide(strip)

    def _handle(self, event: protocol.StripEvent) -> None:
        strip = self.strips[event.strip]
        # the surface keeps the motor in step with the hand, the rest is up to the handler
        match event:
            case protocol.FaderTouched(touched=True):
                strip.touched = True
            case protocol.FaderMoved(value=value):
                strip.moved_by_hand(value)
        try:
            self.on_event(event)
        except Exception:
            _LOGGER.exception(f"Handling {event} failed")
        if isinstance(event, protocol.FaderTouched) and not event.touched:
            strip.touch(False)
