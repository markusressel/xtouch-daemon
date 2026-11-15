"""What a strip does: the base of every kind of strip, and the volume handling they share."""

import asyncio
import logging
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, assert_never

from haad_mqtt_autodiscovery.entity import MQTTEntity

from xtouch_daemon.audio.backend import AudioBackend, AudioCommandError
from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import BehaviorConfig, EncoderMode, Indicator
from xtouch_daemon.media import MediaPlayers
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.protocol import Button, Color, Led, RingMode
from xtouch_daemon.strips.knobs import BalanceKnob, HomeAssistantKnob, Knob, VolumeKnob, ring_position
from xtouch_daemon.surface import Strip

if TYPE_CHECKING:
    from xtouch_daemon.strips.homeassistant import FaderLink, HomeAssistantControls

_LOGGER = logging.getLogger(__name__)

NOTICE_TIME = 2.0
"""
Seconds the second line of the LCD shows the exact value of what the encoder did (e.g. the balance or the position in
the track, see `VolumeStrip.notify`) instead of the volume.
"""


@dataclass(frozen=True)
class StripEnv:
    """What every strip works with."""

    backend: AudioBackend
    behavior: BehaviorConfig
    bridge: MqttBridge | None = None
    """The MQTT broker of Home Assistant, with an [mqtt] section."""
    players: MediaPlayers | None = None
    """The media players of the session, for `encoder = "media"`."""


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

    @property
    def entities(self) -> dict[MQTTEntity, str | None]:
        """Its entities in Home Assistant, with the state each starts with (None: none, e.g. events)."""
        return {}

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


UNITY = 100
"""The volume of the `behavior.unity_at` mark."""


def fader_volume(fraction: float, bottom: int, top: int, unity_at: int) -> float:
    """
    The volume of the fader at 0.0..1.0 for the range `bottom`..`top`: 100 % at `unity_at` percent of the travel and
    linear on both sides of it (see `BehaviorConfig.unity_at`), linear for ranges that do not go across 100 %.
    """
    if not bottom < UNITY < top:
        return bottom + fraction * (top - bottom)
    knee = unity_at / 100
    if fraction <= knee:
        return bottom + fraction / knee * (UNITY - bottom)
    return UNITY + (fraction - knee) / (1 - knee) * (top - UNITY)


def fader_position(volume: float, bottom: int, top: int, unity_at: int) -> float:
    """Where the fader is for the volume, 0.0..1.0: the inverse of `fader_volume`."""
    volume = max(bottom, min(top, volume))
    if not bottom < UNITY < top:
        return (volume - bottom) / (top - bottom)
    knee = unity_at / 100
    if volume <= UNITY:
        return (volume - bottom) / (UNITY - bottom) * knee
    return knee + (volume - UNITY) / (top - UNITY) * (1 - knee)


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
        controls: HomeAssistantControls | None = None,
    ):
        super().__init__(strip, env, color, meter)
        self.label = label
        self.controls = controls
        """Its fader and/or encoder in Home Assistant (`fader`/`encoder = "homeassistant"`)."""
        if controls is not None:
            controls.on_change = self.show
        self.min_volume = min_volume
        self.max_volume = max_volume
        self.indicators: dict[Button, Indicator] = dict(indicators or {})
        self.level: Level | None = None
        self.active = False
        self._wanted: int | None = None
        self._setter: asyncio.Task[None] | None = None
        self.notice: str | None = None
        """Shown on the second line instead of the volume for a moment (`notify`)."""
        self._notice_timer: asyncio.TimerHandle | None = None
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
            case "homeassistant":
                return HomeAssistantKnob(self)
            case _:
                raise ValueError(f"{type(self).__name__} has no encoder {encoder!r}")

    async def apply_balance(self, balance: float) -> None:
        raise NotImplementedError

    def volume_range(self) -> tuple[int, int]:
        """The volumes of the fader at the bottom and at the top."""
        bottom = 0 if self.min_volume is None else self.min_volume
        return bottom, self.env.behavior.max_volume if self.max_volume is None else self.max_volume

    def _fraction(self, volume: int) -> float:
        """Where the fader is for the volume: 0 at the bottom, 1 at the top (see `fader_position`)."""
        bottom, top = self.volume_range()
        return fader_position(volume, bottom, top, self.env.behavior.unity_at)

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

    @property
    def ha_fader(self) -> FaderLink | None:
        """The fader, if it belongs to Home Assistant (then the encoder sets the volume)."""
        return self.controls.fader if self.controls is not None else None

    def show(self) -> None:
        self.strip.set_color(self.color if self.active else Color.BLACK)
        self.strip.set_text(0, self.label)
        if self.ha_fader is not None and self.controls is not None and self.controls.connected:
            self.ha_fader.show()
        level = self.level
        if level is None or not self.active:
            # nothing to control (e.g. an application that ended): the fader goes away
            if self.ha_fader is None:
                self.strip.park()
            self.strip.set_ring(*(self.knob.ring() if self.knob.idle_too else (0, RingMode.DOT)))
            self.strip.set_led(Button.MUTE, Led.OFF)
            self.strip.set_text(1, self.notice or self.inactive_text())
            return
        if self.ha_fader is None:
            self.strip.set_fader(self._fraction(level.volume))
        self.strip.set_ring(*self.knob.ring())
        self.strip.set_led(Button.MUTE, Led.ON if level.muted else Led.OFF)
        if self.notice is not None:
            self.strip.set_text(1, self.notice)
        elif self._wanted is not None:
            self.strip.set_text(1, f"{self._wanted}%")
        else:
            self.strip.set_text(1, "muted" if level.muted else f"{level.volume}%")

    def notify(self, text: str) -> None:
        """Shows `text` on the second line instead of the volume for NOTICE_TIME, e.g. `R 15%` for the balance."""
        self._end_notice_timer()
        self.notice = text
        self._notice_timer = asyncio.get_running_loop().call_later(NOTICE_TIME, self._end_notice)
        self.strip.set_text(1, text)

    def _end_notice(self) -> None:
        self._notice_timer = None
        self.notice = None
        self.show()

    def _end_notice_timer(self) -> None:
        if self._notice_timer is not None:
            self._notice_timer.cancel()
            self._notice_timer = None

    # -- the device -----------------------------------------------------------------------------------------------

    def on_fader(self, fraction: float) -> None:
        if self.ha_fader is not None and self.controls is not None:
            if self.controls.connected:
                self.ha_fader.moved(fraction)
        elif self.accepts_input():
            bottom, top = self.volume_range()
            self.set_volume(round(fader_volume(fraction, bottom, top, self.env.behavior.unity_at)))

    def on_encoder(self, steps: int) -> None:
        if self.knob.idle_too or self.accepts_input():
            self.knob.turn(steps)

    def on_encoder_press(self, pressed: bool) -> None:
        if self.knob.idle_too or self.accepts_input():
            self.knob.push(pressed)

    def on_touch(self, touched: bool) -> None:
        if self.ha_fader is not None and self.controls is not None:
            self.ha_fader.touch(touched)
            self.ha_event("fader_touched" if touched else "fader_released")

    def ha_event(self, event_type: str) -> None:
        """An event of the fader or the encoder for Home Assistant."""
        if self.controls is not None and self.controls.connected:
            self.run_command(self.controls.events.trigger(event_type), event_type)

    def step_volume(self, steps: int) -> None:
        """`steps` of `behavior.encoder_step`."""
        assert self.level is not None, "an active strip has a level"
        base = self._wanted if self._wanted is not None else self.level.volume
        self.set_volume(base + steps * self.env.behavior.encoder_step)
        self._fader_follows()

    def reset_volume(self) -> None:
        self.set_volume(self.env.behavior.reset_volume)
        self._fader_follows()

    def _fader_follows(self) -> None:
        if self.ha_fader is None:
            self.strip.set_fader(self._shown_fraction())

    def volume_ring(self) -> tuple[int, RingMode]:
        """The volume on the ring, from the first LED."""
        volume = self._wanted if self._wanted is not None else self.level.volume if self.level is not None else 0
        return ring_position(self._fraction(volume)), RingMode.WRAP

    @property
    def entities(self) -> dict[MQTTEntity, str | None]:
        return self.controls.entities if self.controls is not None else {}

    def close(self) -> None:
        super().close()
        self._end_notice_timer()
        self.knob.close()
        if self.controls is not None:
            self.controls.close()

    def on_button(self, button: Button, pressed: bool) -> None:
        if pressed and button == Button.MUTE and self.level is not None and self.accepts_input():
            self.run_command(self.apply_mute(not self.level.muted), "mute")

    def _shown_fraction(self) -> float:
        return self._fraction(self._wanted) if self._wanted is not None else 0.0

    def set_volume(self, percent: int) -> None:
        bottom, top = self.volume_range()
        self._wanted = max(bottom, min(top, percent))
        # the volume is what changes now: it replaces a notice
        self._end_notice_timer()
        self.notice = None
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
                    # the rest (the balance) as it was: the ring of the balance would go dark for a moment
                    self.level = replace(self.level, volume=volume)
            if self._wanted == volume:
                self._wanted = None
        self.show()
