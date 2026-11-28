"""
The device as a whole: finding and connecting it (and again after it was unplugged), the events of its strips,
faders that are touched or move by themselves, and the startup and shutdown sequences.
"""

import asyncio
import logging
import math
import time
from collections.abc import Callable
from pathlib import Path

from xtouch_daemon.config.values import Pace, Sequence
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.hardware.strip import FADER_REST, FADER_TICK, Strip
from xtouch_daemon.hardware.transport import AlsaPort, Port, Transport
from xtouch_daemon.simulator.device import SimulatedDevice

_LOGGER = logging.getLogger(__name__)

DEVICE_NAME = "X-Touch-Ext"
SCAN_INTERVAL = 2.0
"""How often the sound cards are checked for the device while it is not connected."""


TIME_SCALE = 1.0
"""
Multiplies the times of the startup and shutdown sequences (their `Pace`): the tests set 0, so the strips are not
staggered.
"""
SHOW_STEPS = protocol.RING_MAX + 1
"""
The steps up (and as many down) of a strip in `show`: the LEDs of the ring one after the other, then the two at its
ends (the center bit).
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


def _ease(fraction: float) -> float:
    """0..1 to 0..1, slow at both ends (half a cosine): how the faders of `show` rise and fall."""
    return (1 - math.cos(math.pi * fraction)) / 2


def steps(sequence: Sequence, startup: bool) -> list[tuple[int, ...]]:
    """
    The strips (from 0) of a startup or shutdown sequence, step by step: `instant` all at once, `sweep` and `show`
    from the left (shutdown: from the right), `curtain` from the middle outwards (shutdown: from the outside in).
    """
    strips = range(protocol.STRIPS)
    match sequence:
        case "instant":
            order = [tuple(strips)]
        case "curtain":
            half = protocol.STRIPS // 2
            order = [(half - 1 - offset, half + offset) for offset in range(half)]
        case _:  # sweep, show
            order = [(index,) for index in strips]
    return order if startup else order[::-1]


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
        proc_asound_cards: Path | None = None,
        dev_snd: Path | None = None,
        port: Port | None = None,
    ):
        """
        `port` reaches the device, by default the sound card named `device_name` (`AlsaPort`, with
        `proc_asound_cards` and `dev_snd` where the sound cards are).
        """
        self.port = port or AlsaPort(device_name, proc_asound_cards, dev_snd)
        self.device_name = self.port.name
        self.startup = Pace()
        self.shutdown = Pace()
        """How the strips light up after a connect and go dark at the end, and how fast (see `steps()`)."""
        self.touchless: frozenset[int] = frozenset()
        """
        The strips (from 0) whose fader has no working touch sensor: a move counts as a touch, a pause of
        TOUCHLESS_LET_GO as letting go.
        """
        self.strips = [Strip(self, index) for index in range(protocol.STRIPS)]
        self.lent: list[Strip] | None = None
        """
        The strips of a test that has the device (see `lend()`), None while `strips` show on it. Hands, the colors
        and the motors are theirs then; `strips` keep what is drawn on them for later.
        """
        self.mirror = SimulatedDevice()
        """
        What the device shows, as far as the surface knows (for the live view): everything it sent, also while the
        device is away (what it will show once it is there), and what the device reported (moves, touches), with the
        motors and the meters moving over time (`time.monotonic()`).
        """
        self.mirror.forget_faders()
        self.on_event: EventHandler = lambda event: None
        self.on_connection: ConnectionHandler = lambda connected: None
        self.on_change: Callable[[], None] = lambda: None
        """
        Called whenever what the device shows (the mirror), the touches of the faders or the connection may have
        changed: for the live view, which sends a snapshot then.
        """
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
        self._midi: Transport | None = None
        self._parser = protocol.MessageParser()
        self._disconnected = asyncio.Event()
        self._gliding: set[Strip] = set()
        self._glider: asyncio.Task[None] | None = None
        self._revealer: asyncio.Task[None] | None = None
        self._lit: set[int] = set()
        """The strips the wave of light of `show` lights white at the moment."""
        self._waving: set[Strip] = set()
        """The strips whose fader the wave of `show` drives at the moment (see `in_wave()`)."""
        self._banner: asyncio.TimerHandle | None = None
        self._flashes: dict[int, asyncio.TimerHandle] = {}
        """The strips (from 0) that flash something (see `flash()`), with the timer that ends it."""

    @property
    def front(self) -> list[Strip]:
        """The strips that show on the device: those of a test while it has it (`lent`), else `strips`."""
        return self.lent if self.lent is not None else self.strips

    def lend(self) -> list[Strip]:
        """
        Hands the device to a test (see `hardware.selftest`): returns new strips that show on it, and get its hands
        (`on_event` goes on as before: whoever handles the test sets it). `strips` keep what is drawn on them without
        showing it, and show it again on `take_back()`.
        """
        assert self.lent is None, "the device is lent already"
        self.end_banner()
        for timer in self._flashes.values():
            timer.cancel()
        for index in self._flashes:
            self.strips[index].set_overlay(None)
        self._flashes.clear()
        for strip in self.strips:
            strip.shown = False
            self._gliding.discard(strip)
        self.lent = [Strip(self, index) for index in range(protocol.STRIPS)]
        for borrowed, strip in zip(self.lent, self.strips, strict=True):
            # dark and empty at first; the motor is where the fader of the strip put it
            borrowed.reveal(strip.position)
        return self.lent

    def take_back(self) -> None:
        """The test ends: `strips` show everything on the device again; the faders glide from where they are."""
        lent, self.lent = self.lent, None
        if lent is None:
            return
        for borrowed, strip in zip(lent, self.strips, strict=True):
            self._gliding.discard(borrowed)
            strip.reveal(borrowed.position)
        self.on_change()

    def banner(self, top: str, bottom: str, seconds: float) -> None:
        """
        Shows two lines of text across the LCDs of all strips for `seconds` (centered, 7 characters per strip), e.g.
        the label of a mode that comes. The strips keep showing what they show underneath, and again after it. Not
        while a test has the device.
        """
        if self.lent is not None:
            return
        if self._banner is not None:
            self._banner.cancel()
        for timer in self._flashes.values():
            timer.cancel()
        self._flashes.clear()
        width = protocol.LCD_CELL_WIDTH
        lines = [text[: width * protocol.STRIPS].center(width * protocol.STRIPS) for text in (top, bottom)]
        for strip in self.strips:
            start = strip.index * width
            strip.set_overlay((lines[0][start : start + width], lines[1][start : start + width]))
        self._banner = asyncio.get_running_loop().call_later(seconds, self.end_banner)

    def flash(self, index: int, top: str, bottom: str, seconds: float) -> None:
        """
        Shows two lines on the LCD of one strip (from 0) for `seconds`, e.g. what a slot shows now and why; not while
        a banner is up, which says more.
        """
        if self._banner is not None or self.lent is not None:
            return
        if (timer := self._flashes.pop(index, None)) is not None:
            timer.cancel()
        width = protocol.LCD_CELL_WIDTH
        self.strips[index].set_overlay((top[:width].center(width), bottom[:width].center(width)))
        self._flashes[index] = asyncio.get_running_loop().call_later(seconds, self._end_flash, index)

    def _end_flash(self, index: int) -> None:
        del self._flashes[index]
        self.strips[index].set_overlay(None)

    def end_banner(self) -> None:
        if self._banner is not None:
            self._banner.cancel()
            self._banner = None
        for strip in self.strips:
            strip.set_overlay(None)

    @property
    def connected(self) -> bool:
        return self._midi is not None

    # -- sending ------------------------------------------------------------------------------------------------

    def send(self, message: bytes) -> None:
        self.mirror.receive(message, time.monotonic())
        if self._midi is not None:
            self._midi.write(message)
        self.on_change()

    def send_colors(self) -> None:
        self.send(
            protocol.lcd_colors(
                [
                    Color.WHITE if strip.index in self._lit else strip.color if strip.shown else Color.BLACK
                    for strip in self.front
                ]
            )
        )

    def in_wave(self, strip: Strip) -> bool:
        """
        Whether the wave of `show` drives the fader of the strip: it glides on from where the wave leaves it (see
        `Strip.arrived()`), and the mirror tells where it is meanwhile.
        """
        return strip in self._waving

    def glide(self, strip: Strip) -> None:
        """Moves the fader of the strip to its target smoothly (see FADER_SMOOTH_TIME)."""
        if not strip.shown or self.in_wave(strip):
            # it moves when its turn in the startup sequence comes, or once the wave is past
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
        """The shutdown sequence (see `shutdown`): the strips go dark and put their faders away."""
        self.end_banner()
        await self._sequence(self.shutdown, startup=False)
        await self.settled()

    async def _reveal(self) -> None:
        """The startup sequence (see `startup`)."""
        await self._sequence(self.startup, startup=True)

    async def _sequence(self, pace: Pace, startup: bool) -> None:
        show = pace.sequence == "show"
        async with asyncio.TaskGroup() as group:
            for number, step in enumerate(steps(pace.sequence, startup)):
                if number:
                    await asyncio.sleep(pace.delay * TIME_SCALE)
                for index in step:
                    if show:
                        group.create_task(self._wave(self.strips[index], pace, startup))
                    elif startup:
                        self.strips[index].reveal()
                    else:
                        self.strips[index].reset()

    async def _wave(self, strip: Strip, pace: Pace, startup: bool) -> None:
        """
        A strip in the wave of `show`: its LCD turns white, its ring fills up LED by LED, its meter goes up and its
        buttons light up from the top (Rec first); then all of it goes off again the same way, the buttons from the top
        too. Its fader rises and falls in step with that. At startup the strip then shows what it is, with the fader
        arriving at its value; at shutdown it goes dark, with the fader at the bottom.
        """
        index = strip.index
        self._gliding.discard(strip)
        self._waving.add(strip)
        ticks_per_step = max(1, round(pace.step * TIME_SCALE / FADER_TICK))
        ticks = 2 * SHOW_STEPS * ticks_per_step
        # after a connect the fader is where the device leaves it (see FADER_REST); at the end where the strip put it
        start = round(FADER_REST) if startup or strip.position is None else strip.position
        # it ends at the value of the strip (one that changes meanwhile glides on from there), at the bottom at the end
        end = (strip.fader or 0) if startup else 0
        peak = max(protocol.fader_value(pace.fader), start, end)
        sent_fader = start
        lit = [False] * len(Button)
        self._lit.add(index)
        self.send_colors()
        for tick in range(ticks):
            if tick % ticks_per_step == 0:
                step = tick // ticks_per_step
                self._light(index, step, lit)
            await asyncio.sleep(FADER_TICK)
            done = (tick + 1) / ticks
            if done <= 0.5:
                value = start + (peak - start) * _ease(2 * done)
            else:
                value = peak + (end - peak) * _ease(2 * done - 1)
            if round(value) != sent_fader and not (strip.touched or strip.held):
                sent_fader = round(value)
                self.send(protocol.fader(index, sent_fader))
        self._lit.discard(index)
        self._waving.discard(strip)
        if startup:
            strip.reveal(sent_fader)
        else:
            if strip.color == Color.BLACK:
                # reset() sends the colors only for a strip that changes its own
                self.send_colors()
            strip.reset()
        strip.arrived(sent_fader)

    def _light(self, index: int, step: int, lit: list[bool]) -> None:
        """
        Step `step` (0..2 * SHOW_STEPS - 1) of the light of a strip in `show` (see `_wave()`): up to SHOW_STEPS on the
        way up, then down to all off. `lit`: which buttons are on, top to bottom, kept up to date.
        """
        up = step < SHOW_STEPS
        level = step + 1 if up else 2 * SHOW_STEPS - 1 - step
        self.send(protocol.ring(index, min(level, protocol.RING_MAX), RingMode.WRAP, level > protocol.RING_MAX))
        self.send(protocol.meter(index, round(protocol.METER_MAX * level / SHOW_STEPS)))
        spacing = SHOW_STEPS // len(Button)
        # on the way up and down alike the top button comes first: on in the order of the steps, off too
        down = step - SHOW_STEPS + 1
        for number, button in enumerate(Button):
            on = level >= number * spacing + 1 if up else down < number * spacing + 1
            if on != lit[number]:
                lit[number] = on
                self.send(protocol.led(index, button, Led.ON if on else Led.OFF))

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
                port = self.port
                await self._disconnected.wait()
                if self.port is port:
                    _LOGGER.warning(f"{self.device_name} is gone, waiting for it to come back")
                    announced_missing = True
        finally:
            await self.close()

    async def use(self, port: Port) -> None:
        """
        Reaches the device through `port` from now on (another sound card, or the virtual device): lets go of the one
        it is connected to, and `run()` connects through `port`, as to a device that came back.
        """
        _LOGGER.info(f"Switching from {self.device_name} to {port.name}")
        midi = self._midi
        await self.close()
        if midi is not None and self._midi is midi:
            # the transport says when the device went away, not always when it was closed
            self._on_closed()
        self.port = port
        self.device_name = port.name

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
        self._midi, path = self.port.open(on_data=self._on_data, on_closed=self._on_closed)
        self._disconnected.clear()
        self._connected_at = asyncio.get_running_loop().time()
        self._parser = protocol.MessageParser()
        self.mirror.forget_faders()
        _LOGGER.info(f"Connected to {self.device_name} at {path}")
        # the startup sequence: dark at first, then from the left one strip after the other lights up
        for strip in self.strips:
            strip.shown = False
        self.send_colors()
        self._revealer = asyncio.create_task(self._reveal(), name="startup sequence")
        self.on_connection(True)
        self.on_change()

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
            self.front[index].held = False
        self._unconfirmed.clear()
        for timer in self._fingers.values():
            timer.cancel()
        self._fingers.clear()
        self._lit.clear()
        self._midi = None
        self._disconnected.set()
        self.on_connection(False)
        self.on_change()

    def _on_data(self, data: bytes) -> None:
        self.mirror.observe(data, time.monotonic())
        self.on_change()
        for message in self._parser.feed(data):
            event = protocol.decode(message)
            if event is None:
                self.on_unknown(message)
                continue
            if isinstance(event, protocol.HostQuery):
                continue
            strip = self.front[event.strip]
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
        strip = self.front[index]
        strip.held = False
        self.on_change()
        _LOGGER.debug(f"Fader {index + 1} moved without a touch: back to its value")
        if strip.fader is not None:
            self.glide(strip)

    def hand(self, data: bytes) -> None:
        """
        What a hand on a device without one (a virtual twin) sends: taken as the device's own bytes, so the touch
        grace, the touchless faders and the mirror work as for a device.
        """
        self._on_data(data)

    def play(self, event: protocol.StripEvent) -> None:
        """
        An event of a hand from elsewhere (the GUI's, see `live.Play`), taken as if the device sent it: a fader is
        touched before it moves, so the motor doesn't fight the hand, and goes to its new value once let go. Nothing
        while no device is connected.
        """
        if self._midi is None:
            return
        self._handle(event)

    def _handle(self, event: protocol.StripEvent) -> None:
        strip = self.front[event.strip]
        if not isinstance(event, protocol.FaderMoved):
            _LOGGER.debug(f"Strip {event.strip + 1}: {event}")
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
        self.on_change()
