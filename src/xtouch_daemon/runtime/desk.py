"""
The desk: the 8 strips of the device for as long as the daemon runs, whatever configuration, mixer or slots show on
them. It knows the hands (faders under a finger, buttons held down), hands every event of the device to the presenter
bound to its strip, and sends a release to whoever got the press, even when another presenter was bound in between.
The meters of the strips and the chord of Solo buttons are its business too: a capture goes on while another
mixer takes over a strip that shows the same. See "The runtime" in
docs/development/design/slots/daemon.md.
"""

import asyncio
from collections.abc import Callable, Sequence
from typing import Protocol, assert_never

from xtouch_daemon.audio.meter import PW_RECORD, Capturer, CaptureTarget, Meter, Reading, leds_of
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.values import MeterPoint
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.hardware.strip import CLAIMABLE_BUTTONS, Claimable
from xtouch_daemon.hardware.surface import Surface

type Control = Button | None
"""A control of a strip that is pressed and let go: a button, or the encoder (None)."""
type Key = tuple[int, Control | str]
"""A strip of the device (from 0) and its control; "fader" for the touch of its fader."""
FADER = "fader"
METER_INTERVAL = 0.1
"""How often the meters show the peak since the last time (the device lets them fall in between)."""


class Hands(Protocol):
    """What handles the events of a strip of the device: a presenter, or a claim."""

    def on_fader(self, fraction: float) -> None: ...
    def on_touch(self, touched: bool) -> None: ...
    def on_button(self, button: Button, pressed: bool) -> None: ...
    def on_encoder(self, steps: int) -> None: ...
    def on_encoder_press(self, pressed: bool) -> None: ...


class Claim(Hands, Protocol):
    """
    Controls of a strip of the device that act whatever it shows (`[controls]` of a slot): the events of the
    controls it `takes` go to it, not to the presenter.
    """

    @property
    def taken(self) -> frozenset[Claimable]: ...


class Presenter(Hands, Protocol):
    """What the desk hands the events of a strip of the device to (today's strip controllers)."""

    def meter_targets(self, state: AudioState) -> set[CaptureTarget]: ...
    def is_playing(self, target: CaptureTarget, state: AudioState) -> bool: ...
    def target_gain(self, target: CaptureTarget, state: AudioState) -> float | None: ...
    def held_meter(self, point: MeterPoint) -> Reading | None: ...


def touchless(config: Config) -> frozenset[int]:
    """The strips (from 0) whose fader moves count without a touch: all of them without `touch_required`."""
    if not config.device.touch_required:
        return frozenset(range(protocol.STRIPS))
    return frozenset(number - 1 for number in config.device.touchless_faders)


class Desk:
    """
    The strips of the device and the hands on them. `bind()` gives a strip (from 0) its presenter; `hands_free` are
    called when the last finger left the device (what waited for that may happen now), `on_chord` when the Solo
    buttons of `chord` (strips from 0) are all held down. Its meters capture with `capture_command` what the
    presenters show (see `watch()`), `run()` shows them.
    """

    def __init__(
        self,
        surface: Surface,
        chord: frozenset[int] = frozenset(),
        on_chord: Callable[[], None] = lambda: None,
        capture_command: str = PW_RECORD,
        capturer: Capturer | None = None,
    ):
        self.surface = surface
        self.chord = chord
        self.on_chord = on_chord
        self.hands_free: list[Callable[[], None]] = []
        self.presenters: list[Presenter | None] = [None] * len(surface.strips)
        """The presenter bound to each strip of the device."""
        self.claims: list[Claim | None] = [None] * len(surface.strips)
        """The claim on each strip of the device: its controls go to it (see `claim()`)."""
        self._touched: set[int] = set()
        """The faders of the device (from 0) a finger is on."""
        self._held: set[tuple[int, Control]] = set()
        """The buttons of the device held down: the strip (from 0) and the button, None for the encoder."""
        self._pressed: dict[Key, Hands | None] = {}
        """Who got each press and touch not let go yet: they get its release."""
        self._held_solos: set[int] = set()
        self.state: AudioState = DISCONNECTED
        """The audio state the presenters show, for the meters (see `watch()`)."""
        self.meters = [self._meter(strip, capture_command, capturer) for strip in range(len(surface.strips))]
        """The meter of each strip of the device."""
        surface.on_event = self.dispatch

    def _meter(self, strip: int, command: str, capturer: Capturer | None) -> Meter:
        def playing(target: CaptureTarget) -> bool:
            presenter = self.presenters[strip]
            return presenter is not None and presenter.is_playing(target, self.state)

        def gain(target: CaptureTarget) -> float | None:
            presenter = self.presenters[strip]
            return presenter.target_gain(target, self.state) if presenter is not None else None

        return Meter(playing, command, gain=gain, capturer=capturer)

    def bind(self, strip: int, presenter: Presenter | None, meter_point: MeterPoint = "pre_fader") -> None:
        """
        Binds a presenter to a strip of the device (from 0), its meter shows the level at `meter_point`. The fader
        under a finger goes over to it: the presenter that had the touch lets go, the new one gets it at once (so
        each sees a touch and its release). The meter captures what it shows from the next `watch()` on.
        """
        self.meters[strip].point = meter_point
        if self.presenters[strip] is presenter:
            return
        self.presenters[strip] = presenter
        self._hand_over_fader(strip)

    def claim(self, strip: int, claim: Claim | None) -> None:
        """
        Puts a claim on a strip of the device (from 0), None takes it away: the controls it takes go to it, the others
        to the presenter. A fader under a finger goes over as on `bind()`.
        """
        if self.claims[strip] is claim:
            return
        self.claims[strip] = claim
        self._hand_over_fader(strip)

    def _owner(self, strip: int, control: Claimable) -> Hands | None:
        """Who gets the events of a control of a strip now: its claim if it takes it, else the presenter."""
        claim = self.claims[strip]
        return claim if claim is not None and control in claim.taken else self.presenters[strip]

    def _hand_over_fader(self, strip: int) -> None:
        """The fader under a finger goes to its owner now: the one that had the touch lets go, the new one gets it."""
        if strip not in self._touched:
            return
        before = self._pressed.get((strip, FADER))
        owner = self._owner(strip, "fader")
        if before is owner:
            return
        if before is not None:
            before.on_touch(False)
        self._pressed[(strip, FADER)] = owner
        if owner is not None:
            owner.on_touch(True)

    def unbind(self, presenters: Sequence[Presenter]) -> None:
        """Takes these presenters off the device (a mixer that goes): their strips show nothing until bound again."""
        for strip, presenter in enumerate(self.presenters):
            if presenter is not None and any(presenter is gone for gone in presenters):
                self.bind(strip, None)

    @property
    def busy(self) -> bool:
        """Whether a finger is on the device: a fader touched, a button held, a touchless fader that just moved."""
        return bool(self._touched or self._held) or any(strip.held for strip in self.surface.strips)

    def held_slots(self) -> frozenset[int]:
        """The strips of the device (from 1) under a finger, with a button held, or whose touchless fader just moved."""
        return frozenset(
            {
                *(strip + 1 for strip in self._touched),
                *(strip + 1 for strip, button in self._held if not (button == Button.SOLO and strip in self.chord)),
                *(index + 1 for index, strip in enumerate(self.surface.strips) if strip.held),
            }
        )

    def dispatch(self, event: protocol.StripEvent) -> None:
        released = self._follow_hands(event)
        match event:
            case protocol.FaderMoved(strip=strip, value=value):
                if (owner := self._owner(strip, "fader")) is not None:
                    owner.on_fader(protocol.fader_fraction(value))
            case protocol.FaderTouched(strip=strip, touched=touched):
                if (owner := self._press((strip, FADER), "fader", touched)) is not None:
                    owner.on_touch(touched)
            case protocol.ButtonPressed(strip=strip, button=button, pressed=pressed):
                control = CLAIMABLE_BUTTONS.get(button)
                if (owner := self._press((strip, button), control, pressed)) is not None:
                    owner.on_button(button, pressed)
                if button == Button.SOLO:
                    self._follow_chord(strip, pressed)
            case protocol.EncoderTurned(strip=strip, steps=steps):
                if (owner := self._owner(strip, "encoder")) is not None:
                    owner.on_encoder(steps)
            case protocol.EncoderPressed(strip=strip, pressed=pressed):
                if (owner := self._press((strip, None), "encoder", pressed)) is not None:
                    owner.on_encoder_press(pressed)
            case _ as unreachable:
                assert_never(unreachable)
        if released and not (self._touched or self._held):
            for listener in list(self.hands_free):
                listener()

    def _press(self, key: Key, control: Claimable | None, down: bool) -> Hands | None:
        """
        Who gets a press (the owner of the control now; None for one no claim can take) or its release (who got the
        press).
        """
        owner = self._owner(key[0], control) if control is not None else self.presenters[key[0]]
        if down:
            self._pressed[key] = owner
            return owner
        return self._pressed.pop(key, owner)

    def _follow_hands(self, event: protocol.StripEvent) -> bool:
        """Which faders are touched and which buttons held; True for a release."""
        match event:
            case protocol.FaderTouched(strip=strip, touched=touched):
                (self._touched.add if touched else self._touched.discard)(strip)
                return not touched
            case protocol.ButtonPressed(strip=strip, button=button, pressed=pressed):
                (self._held.add if pressed else self._held.discard)((strip, button))
                return not pressed
            case protocol.EncoderPressed(strip=strip, pressed=pressed):
                (self._held.add if pressed else self._held.discard)((strip, None))
                return not pressed
            case _:
                return False

    def _follow_chord(self, strip: int, pressed: bool) -> None:
        if strip not in self.chord:
            return
        if not pressed:
            self._held_solos.discard(strip)
            return
        self._held_solos.add(strip)
        if self._held_solos == self.chord:
            # once per chord: the buttons have to be let go first
            self._held_solos.clear()
            self.on_chord()

    # -- meters ---------------------------------------------------------------------------------------------------

    def watch(self, state: AudioState) -> None:
        """The meters capture what the presenters bound now show in `state`."""
        self.state = state
        for presenter, meter in zip(self.presenters, self.meters, strict=True):
            meter.watch(presenter.meter_targets(state) if presenter is not None else ())

    def show_meters(self) -> None:
        """
        Shows the level of each strip since the last time; without audio the one its presenter holds (a voice in
        voice chat), or nothing, so the device lets the meter fall.
        """
        for strip, presenter, meter in zip(self.surface.strips, self.presenters, self.meters, strict=True):
            level = meter.take_level()
            if level is None and presenter is not None and (held := presenter.held_meter(meter.point)) is not None:
                level = leds_of(held)
            if level is not None:
                strip.set_meter(level)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(METER_INTERVAL)
            self.show_meters()

    def close(self) -> None:
        """Stops the captures; `wait_closed()` waits until their processes ended."""
        for meter in self.meters:
            meter.close()

    async def wait_closed(self) -> None:
        await asyncio.gather(*(meter.wait_closed() for meter in self.meters))
