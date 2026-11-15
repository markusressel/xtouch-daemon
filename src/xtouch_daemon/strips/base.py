"""What a strip does: the base of every kind of strip, and the volume handling they share."""

import asyncio
import logging
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import assert_never

from xtouch_daemon.audio.backend import AudioBackend, AudioCommandError
from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import BehaviorConfig, EncoderMode, Indicator
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.protocol import Button, Color, Led, RingMode
from xtouch_daemon.strips.knobs import BalanceKnob, Knob, VolumeKnob, ring_position
from xtouch_daemon.surface import Strip

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StripEnv:
    """What every strip works with."""

    backend: AudioBackend
    behavior: BehaviorConfig
    bridge: MqttBridge | None = None
    """The MQTT broker of Home Assistant, with an [mqtt] section."""


class StripController:
    """
    Drives one strip: `update()` shows the audio state on it (after every change), the `on_*` methods handle what
    happens on the device. None of them block: commands to the sound server run as tasks.
    """

    def __init__(self, strip: Strip, env: StripEnv, color: Color = Color.WHITE, meter: bool = True):
        self.strip = strip
        self.env = env
        self.color = color
        self.meter = meter and env.behavior.meters
        self._tasks: set[asyncio.Task[None]] = set()

    def update(self, state: AudioState) -> None:
        """Shows the state on the strip."""

    def meter_targets(self, state: AudioState) -> set[CaptureTarget]:
        """What the meter of the strip shows the level of."""
        return set()

    def is_playing(self, target: CaptureTarget, state: AudioState) -> bool:
        """Whether audio should flow at the target, so a capture without audio is not linked."""
        return False

    def on_fader(self, fraction: float) -> None:
        pass

    def on_touch(self, touched: bool) -> None:
        pass

    def on_button(self, button: Button, pressed: bool) -> None:
        pass

    def on_encoder(self, steps: int) -> None:
        pass

    def on_encoder_press(self, pressed: bool) -> None:
        pass

    def close(self) -> None:
        """The strip is taken over by another configuration: stops what is still running."""
        for task in self._tasks:
            task.cancel()

    def run_command(self, command: Awaitable[None], what: str) -> None:
        """Runs a command to the sound server in the background; one that fails is logged."""

        async def run() -> None:
            try:
                await command
            except AudioCommandError as e:
                _LOGGER.warning(f"Strip {self.strip.index + 1}: {what}: {e}")

        task = asyncio.create_task(run(), name=f"strip {self.strip.index + 1}: {what}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


@dataclass(frozen=True)
class Level:
    """The volume a strip shows."""

    volume: int
    muted: bool
    balance: float | None = None
    """See `Device.balance`."""


class VolumeStrip(StripController):
    """
    A strip that controls a volume: the fader sets it, the mute button mutes, the encoder does what `encoder` says
    (`knobs.py`: e.g. fine steps of the volume, or the balance). The LCD shows the label and the volume (or
    "muted"), the ring what the encoder controls, and the LEDs in `indicators` show what they are configured to (e.g.
    the rec LED whether an application records).

    The fader goes from `min_volume` at the bottom to `max_volume` at the top (by default 0 and `behavior.max_volume`),
    the encoder stays in that range too.

    Fader moves come faster than the sound server carries them out, so only the latest volume is set once the
    previous command is done.
    """

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        label: str,
        color: Color = Color.WHITE,
        meter: bool = True,
        indicators: Mapping[Button, Indicator] | None = None,
        min_volume: int | None = None,
        max_volume: int | None = None,
        encoder: EncoderMode = "volume",
    ):
        super().__init__(strip, env, color, meter)
        self.label = label
        self.min_volume = min_volume
        self.max_volume = max_volume
        self.indicators: dict[Button, Indicator] = dict(indicators or {})
        self.level: Level | None = None
        self.active = False
        self._wanted: int | None = None
        self._setter: asyncio.Task[None] | None = None
        self.knob = self.make_knob(encoder)

    # -- for the kinds of strips ----------------------------------------------------------------------------------

    def current(self, state: AudioState) -> tuple[Level | None, bool]:
        """The level to show (None if there is none) and whether the strip is active (lit) or idle (dark)."""
        raise NotImplementedError

    def inactive_text(self) -> str:
        return "off"

    async def apply_volume(self, percent: int) -> None:
        raise NotImplementedError

    async def apply_mute(self, muted: bool) -> None:
        raise NotImplementedError

    def make_knob(self, encoder: EncoderMode) -> Knob:
        """What the encoder does; the kinds of strips add theirs."""
        match encoder:
            case "volume":
                return VolumeKnob(self)
            case "balance":
                return BalanceKnob(self)
            case _:
                raise ValueError(f"{type(self).__name__} has no encoder {encoder!r}")

    async def apply_balance(self, balance: float) -> None:
        raise NotImplementedError

    def volume_range(self) -> tuple[int, int]:
        """The volumes of the fader at the bottom and at the top."""
        bottom = 0 if self.min_volume is None else self.min_volume
        return bottom, self.env.behavior.max_volume if self.max_volume is None else self.max_volume

    def _fraction(self, volume: int) -> float:
        """Where the fader is for the volume: 0 at the bottom, 1 at the top."""
        bottom, top = self.volume_range()
        return max(0.0, min(1.0, (volume - bottom) / (top - bottom)))

    def accepts_input(self) -> bool:
        """Whether the fader and encoder do something now (e.g. not for a device that is not there)."""
        return self.active

    def recording(self, state: AudioState) -> bool:
        """Whether an application records what the strip controls."""
        return False

    def playing(self, state: AudioState) -> bool:
        """Whether audio flows through what the strip controls."""
        return False

    def is_default(self, state: AudioState) -> bool:
        """Whether the strip controls the default device."""
        return False

    # -- showing --------------------------------------------------------------------------------------------------

    def update(self, state: AudioState) -> None:
        self.level, self.active = self.current(state)
        self.show()
        for button, indicator in self.indicators.items():
            self.strip.set_led(button, Led.ON if self.indicates(indicator, state) else Led.OFF)

    def indicates(self, indicator: Indicator, state: AudioState) -> bool:
        match indicator:
            case "off":
                return False
            case "recording":
                return self.recording(state)
            case "playing":
                return self.playing(state)
            case "default":
                return self.is_default(state)
            case "muted":
                return self.level is not None and self.level.muted
            case _ as unreachable:
                assert_never(unreachable)

    def show(self) -> None:
        self.strip.set_color(self.color if self.active else Color.BLACK)
        self.strip.set_text(0, self.label)
        level = self.level
        if level is None or not self.active:
            # nothing to control (e.g. an application that ended): the fader goes away
            self.strip.park()
            self.strip.set_ring(0)
            self.strip.set_led(Button.MUTE, Led.OFF)
            self.strip.set_text(1, self.inactive_text())
            return
        self.strip.set_fader(self._fraction(level.volume))
        self.strip.set_ring(*self.knob.ring())
        self.strip.set_led(Button.MUTE, Led.ON if level.muted else Led.OFF)
        if self._wanted is not None:
            self.strip.set_text(1, f"{self._wanted}%")
        else:
            self.strip.set_text(1, "muted" if level.muted else f"{level.volume}%")

    # -- the device -----------------------------------------------------------------------------------------------

    def on_fader(self, fraction: float) -> None:
        if self.accepts_input():
            bottom, top = self.volume_range()
            self.set_volume(round(bottom + fraction * (top - bottom)))

    def on_encoder(self, steps: int) -> None:
        if self.accepts_input():
            self.knob.turn(steps)

    def on_encoder_press(self, pressed: bool) -> None:
        if self.accepts_input():
            self.knob.push(pressed)

    def step_volume(self, steps: int) -> None:
        """`steps` of `behavior.encoder_step`."""
        assert self.level is not None, "an active strip has a level"
        base = self._wanted if self._wanted is not None else self.level.volume
        self.set_volume(base + steps * self.env.behavior.encoder_step)
        # the fader follows
        self.strip.set_fader(self._shown_fraction())

    def reset_volume(self) -> None:
        self.set_volume(self.env.behavior.reset_volume)
        self.strip.set_fader(self._shown_fraction())

    def volume_ring(self) -> tuple[int, RingMode]:
        """The volume on the ring, from the first LED."""
        volume = self._wanted if self._wanted is not None else self.level.volume if self.level is not None else 0
        return ring_position(self._fraction(volume)), RingMode.WRAP

    def close(self) -> None:
        super().close()
        self.knob.close()

    def on_button(self, button: Button, pressed: bool) -> None:
        if pressed and button == Button.MUTE and self.level is not None and self.accepts_input():
            self.run_command(self.apply_mute(not self.level.muted), "mute")

    def _shown_fraction(self) -> float:
        return self._fraction(self._wanted) if self._wanted is not None else 0.0

    def set_volume(self, percent: int) -> None:
        bottom, top = self.volume_range()
        self._wanted = max(bottom, min(top, percent))
        # right away, the sound server confirms it a moment later
        self.strip.set_text(1, f"{self._wanted}%")
        if self._setter is None or self._setter.done():
            self._setter = asyncio.create_task(self._apply_wanted(), name=f"strip {self.strip.index + 1}: volume")
            self._tasks.add(self._setter)
            self._setter.add_done_callback(self._tasks.discard)

    async def _apply_wanted(self) -> None:
        while self._wanted is not None:
            volume = self._wanted
            try:
                await self.apply_volume(volume)
            except AudioCommandError as e:
                _LOGGER.warning(f"Strip {self.strip.index + 1}: setting the volume: {e}")
            else:
                # until the sound server reports it, so the old volume does not flash up
                if self.level is not None:
                    self.level = Level(volume, self.level.muted)
            if self._wanted == volume:
                self._wanted = None
        self.show()
