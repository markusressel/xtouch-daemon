"""
The X-Touch Extender as a surface: what each of its 8 strips shows, and the connection to the device.

The surface remembers everything a strip shows, so it shows it again after the device was switched off and on or
plugged in again, sends only what changed, keeps the motor of a fader still while a finger is on it, and moves the
motor faders smoothly. What happens on the device (fader moves, touches, buttons, encoders) goes to `on_event`.
"""

import asyncio
import logging
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
FADER_SNAP = 48
FADER_SNAP_SPEED = 2000
"""The fader is put at its target once it is this close (about 0.3 %) and this slow (fader steps per second)."""


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

    def __init__(self, surface: "Surface", index: int):
        self._surface = surface
        self.index = index
        self.touched = False
        self.color = Color.BLACK
        self.text = ["", ""]
        self.leds: dict[Button, Led] = {}
        self.ring: tuple[int, RingMode] = (0, RingMode.DOT)
        self.fader: int | None = None
        """Where the fader should be: None until it is known, so the fader does not move to 0 and back on a connect."""
        self._position: float | None = None
        """Where the fader is: what was sent to the motor last, or where a finger put it."""
        self._velocity = 0.0

    def reset(self) -> None:
        """Dark and empty, the fader at the bottom (e.g. before another strip configuration takes over)."""
        self.set_color(Color.BLACK)
        self.set_text(0, "")
        self.set_text(1, "")
        for button in Button:
            self.set_led(button, Led.OFF)
        self.set_ring(0)
        self.set_fader(0.0)

    def set_fader(self, fraction: float) -> None:
        """Moves the fader to 0.0..1.0, unless a finger is on it: then it moves there when it is let go."""
        self.fader = protocol.fader_value(fraction)
        if not self.touched:
            self._surface.glide(self)

    def set_led(self, button: Button, state: Led) -> None:
        if self.leds.get(button) == state:
            return
        self.leds[button] = state
        self._surface.send(protocol.led(self.index, button, state))

    def set_text(self, line: int, text: str) -> None:
        text = text[: protocol.LCD_CELL_WIDTH]
        if self.text[line] == text:
            return
        self.text[line] = text
        self._surface.send(protocol.lcd_text(self.index, line, text))

    def set_ring(self, position: int, mode: RingMode = RingMode.DOT) -> None:
        if self.ring == (position, mode):
            return
        self.ring = (position, mode)
        self._surface.send(protocol.ring(self.index, position, mode))

    def set_color(self, color: Color) -> None:
        if self.color == color:
            return
        self.color = color
        self._surface.send_colors()

    def set_meter(self, level: int) -> None:
        """
        Lights the meter up to 0..METER_MAX. Not remembered: the device lets it fall by itself, a level is held by
        sending it again.
        """
        self._surface.send(protocol.meter(self.index, level))

    # -- the motor ------------------------------------------------------------------------------------------------

    def touch(self, touched: bool) -> None:
        self.touched = touched
        if not touched and self.fader is not None:
            # back to the value the fader stands for (usually the one that was set last)
            self._surface.glide(self)

    def moved_by_hand(self, value: int) -> None:
        self._position = value
        self._velocity = 0.0

    def step(self) -> bool:
        """Moves the fader one tick closer to its target. False once it is there."""
        if self.touched or self.fader is None:
            return False
        if self._position is None:
            # not known where it is (e.g. after a connect): straight to the target
            self._position = self.fader
            self._velocity = 0.0
        else:
            if self._position == self.fader and self._velocity == 0.0:
                return False
            self._position, self._velocity = smooth_damp(
                self._position, self._velocity, self.fader, FADER_SMOOTH_TIME, FADER_TICK
            )
            if abs(self.fader - self._position) <= FADER_SNAP and abs(self._velocity) <= FADER_SNAP_SPEED:
                self._position = self.fader
                self._velocity = 0.0
        self._surface.send(protocol.fader(self.index, round(self._position)))
        return self._position != self.fader

    def connected(self) -> list[bytes]:
        """Everything the strip shows, for a device that was just connected: the fader goes straight to its place."""
        self.touched = False
        self._position = self.fader
        self._velocity = 0.0
        return [
            *([protocol.fader(self.index, self.fader)] if self.fader is not None else []),
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
        self.proc_asound_cards = proc_asound_cards
        self.dev_snd = dev_snd
        self.strips = [Strip(self, index) for index in range(protocol.STRIPS)]
        self.on_event: EventHandler = lambda event: None
        self.on_connection: ConnectionHandler = lambda connected: None
        self._midi: RawMidi | None = None
        self._parser = protocol.MessageParser()
        self._disconnected = asyncio.Event()
        self._gliding: set[Strip] = set()
        self._glider: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._midi is not None

    # -- sending ------------------------------------------------------------------------------------------------

    def send(self, message: bytes) -> None:
        if self._midi is not None:
            self._midi.write(message)

    def send_colors(self) -> None:
        self.send(protocol.lcd_colors([strip.color for strip in self.strips]))

    def glide(self, strip: Strip) -> None:
        """Moves the fader of the strip to its target smoothly (see FADER_SMOOTH_TIME)."""
        self._gliding.add(strip)
        if self._glider is None or self._glider.done():
            self._glider = asyncio.create_task(self._glide(), name="fader motors")

    async def _glide(self) -> None:
        while self._gliding:
            for strip in list(self._gliding):
                if not strip.step():
                    self._gliding.discard(strip)
            if self._gliding:
                await asyncio.sleep(FADER_TICK)

    async def settled(self) -> None:
        """Waits until the faders are where they should be."""
        while self._glider is not None and not self._glider.done():
            await self._glider

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
        self._parser = protocol.MessageParser()
        _LOGGER.info(f"Connected to {self.device_name} at {path}")
        for strip in self.strips:
            for message in strip.connected():
                self.send(message)
        self.send_colors()
        self.on_connection(True)

    async def close(self) -> None:
        """Sends what is still on its way and closes the device."""
        midi = self._midi
        if midi is None:
            return
        await midi.drain()
        midi.close()

    def _on_closed(self) -> None:
        self._midi = None
        self._disconnected.set()
        self.on_connection(False)

    def _on_data(self, data: bytes) -> None:
        for message in self._parser.feed(data):
            event = protocol.decode(message)
            if event is None or isinstance(event, protocol.HostQuery):
                continue
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
