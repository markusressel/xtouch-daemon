"""What a strip does: the base of every kind of strip, and the volume handling they share."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol, assert_never

from haad_mqtt_autodiscovery.entity import MQTTEntity

from xtouch_daemon.audio.backend import AudioBackend, AudioCommandError
from xtouch_daemon.audio.media import MediaPlayers
from xtouch_daemon.audio.meter import CaptureTarget, Lit, Reading
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.bindings import HOME_ASSISTANT, LevelBinding, RunAction, WatchBinding, fill, placeholders_of
from xtouch_daemon.config.buttons import HOLD_TIME, WHILE_HELD, Action, ButtonSetup, LaunchAction, indicator
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.values import ColorName, EncoderMode, Indicator, MeterPoint, color_of
from xtouch_daemon.hardware.protocol import METER_MAX, Button, Color, Led, RingMode
from xtouch_daemon.hardware.strip import Claimable, Strip
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.strips.bound import BoundParts, Parts, led_key
from xtouch_daemon.strips.knobs import BalanceKnob, CommandKnob, HomeAssistantKnob, Knob, VolumeKnob, ring_position
from xtouch_daemon.strips.value import led_of_line, level_of_line, run_program, value_text
from xtouch_daemon.system.commands import Commands
from xtouch_daemon.system.launch import LaunchButton, Launcher
from xtouch_daemon.voip.provider import VoipProvider

if TYPE_CHECKING:
    from xtouch_daemon.strips.homeassistant import FaderLink, HomeAssistantControls

_LOGGER = logging.getLogger(__name__)

NOTICE_TIME = 2.0
"""
Seconds the second line of the LCD shows the exact value of what the encoder did (e.g. the balance or the position in
the track, see `VolumeStrip.notify`) instead of the volume.
"""
OFFLINE_TEXT = "offline"
"""The second line of the LCD while Home Assistant, which sets it, is not there."""


class SlotActions(Protocol):
    """What buttons ask of the slots (the `SlotEngine`): modes and overrides, as the buttons of `[controls]` do."""

    @property
    def mode(self) -> str: ...
    def value(self, name: str) -> bool: ...
    def cycle_modes(self) -> None: ...
    def choose_mode(self, mode: str) -> None: ...
    def toggle(self, name: str) -> None: ...


@dataclass(frozen=True)
class StripEnv:
    """What every strip works with."""

    backend: AudioBackend
    behavior: BehaviorConfig
    bridge: MqttBridge | None = None
    """The MQTT broker of Home Assistant, with an [mqtt] section."""
    players: MediaPlayers | None = None
    """The media players of the session, for `encoder = "media"`."""
    voip: VoipProvider | None = None
    """The participants of the voice chat, with a [voip] section."""
    launcher: Launcher = field(default_factory=Launcher)
    """Starts the applications of strips with `launch`."""
    processes: Callable[[], frozenset[str]] = frozenset
    """The names of the processes that run (see `processes.running_processes()`), as the mixer saw them last."""
    actions: SlotActions | None = None
    """The modes and states of the slots, for buttons with `mode:`, `toggle:` and `cycle_modes`."""
    solo: Callable[[StripController, bool], None] = lambda strip, on: None
    """Mutes the strips but this one (True), and unmutes them again (False): `mute_others`."""
    commands: Commands = field(default_factory=Commands)
    """Runs the programs of command channels."""


@dataclass(frozen=True)
class Identity:
    """
    Who a controller is, whatever strip of the device shows it: `id` is part of the ids of its entities in Home
    Assistant (the id of its channel), `name` of their names and of the log.
    """

    id: str
    name: str


@dataclass(frozen=True)
class Look:
    """How a controller looks on the strip it is on: the options of the configuration."""

    label: str | None = None
    """The top line; None for what the controller shows by itself (e.g. the description of a device)."""
    color: ColorName = "white"
    meter: bool = True
    """Whether the LED meter shows the level (if `behavior.meters` is on)."""
    meter_point: MeterPoint = "pre_fader"
    buttons: Mapping[Button, ButtonSetup] = field(default_factory=dict[Button, ButtonSetup])
    """What Select, Rec and Solo do and what their LEDs show."""
    lit_when_idle: bool = False
    """Whether the LCD keeps its backlight while the strip is idle."""
    parts: Parts = field(default_factory=Parts)
    """The parts bound to programs of your own or to Home Assistant (`config.bindings`)."""


class StripController:
    """
    Drives one strip: `update()` shows the audio state on it (after every change), the `on_*` methods handle what
    happens on the device. None of them block: commands to the sound server run as tasks. Its identity and look come
    from outside: the configuration of a strip, or of a channel.
    """

    def __init__(self, strip: Strip, env: StripEnv, identity: Identity, look: Look):
        self.strip = strip
        self.env = env
        self.identity = identity
        self.look = look
        self.taken: frozenset[Claimable] = frozenset()
        """The controls of its strip the controls of the slot claim (`[controls]`): their events go there."""
        self._tasks: set[asyncio.Task[None]] = set()

    def set_look(self, look: Look) -> None:
        """Another look (the strip it is on now has other options); shows at the next `update()`."""
        self.look = look

    def set_taken(self, taken: frozenset[Claimable]) -> None:
        """The controls of the slot claim these controls of the strip it is on (none when it leaves the slot)."""
        self.taken = taken

    @property
    def color(self) -> Color:
        return color_of(self.look.color)

    @property
    def meter(self) -> bool:
        return self.look.meter and self.env.behavior.meters

    def update(self, state: AudioState) -> None:
        """Shows the state on the strip."""

    @property
    def launches(self) -> bool:
        """Whether Select launches an application (`launch`), which needs the processes that run."""
        return False

    def meter_targets(self, state: AudioState) -> set[CaptureTarget]:
        """What the meter of the strip shows the level of."""
        return set()

    def is_playing(self, target: CaptureTarget, state: AudioState) -> bool:
        """Whether audio should flow at the target, so a capture without audio is not linked."""
        return False

    def target_gain(self, target: CaptureTarget, state: AudioState) -> float | None:
        """
        The volume of a target of the meter, with Mute, as the factor of the amplitude (see `Device.gain`); None if it
        is not there.
        """
        return None

    @property
    def title(self) -> str:
        """What the strip is, for the log: its label, or its name."""
        return self.identity.name

    def held_meter(self, point: MeterPoint) -> Reading | None:
        """
        What the meter shows without a capture of its own: audio as a `Peak` (e.g. a participant of the voice chat),
        anything else as `Lit` (e.g. a level Home Assistant set); None for nothing. `point` is the strip's
        `meter_point`. The device lets a meter fall, so the mixer sends it again and again.
        """
        return None

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
                _LOGGER.warning(f"{self.identity.name}: {what}: {e}")

        task = asyncio.create_task(run(), name=f"{self.identity.name}: {what}")
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
    "muted"), the ring what the encoder controls, and the LEDs of the buttons (`Look.buttons`) what they are
    configured to (e.g. the rec LED whether an application records). Select, Rec and Solo do what their press and hold
    say (`act()`): a hold once the button is down for HOLD_TIME, a press when it is let go before (at once without a
    hold).

    The fader goes from `min_volume` at the bottom to `max_volume` at the top (by default 0 and `behavior.max_volume`),
    the encoder stays in that range too.

    Fader moves come faster than the sound server carries them out, so only the latest volume is set once the
    previous command is done.
    """

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        identity: Identity,
        look: Look,
        min_volume: int | None = None,
        max_volume: int | None = None,
        encoder: EncoderMode = "volume",
        controls: HomeAssistantControls | None = None,
    ):
        super().__init__(strip, env, identity, look)
        self.label = look.label or ""
        """The top line: the label of the look, or what the kind of strip shows."""
        self.controls = controls
        """
        Its parts in Home Assistant (`"homeassistant"`), and the numbers there of its values of programs of your own.
        """
        if controls is not None:
            controls.on_change = self._parts_changed
        self.fader_in_home_assistant = controls is not None and controls.fader is not None
        """
        Whether the fader belongs to Home Assistant: then it sets no volume. Without the entity (Simulate has no MQTT)
        it stays where it is, as while Home Assistant is not connected.
        """
        self._warned: set[str] = set()
        """The parts in Home Assistant without an entity that the log has named already."""
        self.bound = BoundParts(env.commands, env.behavior.encoder_step, identity.name, self._parts_changed)
        """The programs of its bound parts (`Look.parts`, the LEDs of `Look.buttons`), for as long as it lives."""
        self._bind_parts()
        self.min_volume = min_volume
        self.max_volume = max_volume
        self.level: Level | None = None
        self.state_known: AudioState | None = None
        """The state of the last `update()`, for the LEDs of the buttons after a press."""
        self.active = False
        self._wanted: int | None = None
        self._setter: asyncio.Task[None] | None = None
        self.notice: str | None = None
        """Shown on the second line instead of the volume for a moment (`notify`)."""
        self._notice_timer: asyncio.TimerHandle | None = None
        self.encoder_mode: EncoderMode = encoder
        """What the encoder does by the configuration; while the fader is taken, it sets the volume (see `knob`)."""
        self.knob = self._new_knob()
        self._holds: dict[Button, asyncio.TimerHandle] = {}
        """The buttons pressed whose hold comes once HOLD_TIME is over."""
        self._acting: dict[Button, Action] = {}
        """The buttons held whose action lasts until they are let go (`WHILE_HELD`)."""
        self._talking = False
        """Mute went off for `talk`: it goes on again when the button is let go."""
        self._launches: dict[Button, LaunchButton] = {}
        self._make_launches()

    def set_look(self, look: Look) -> None:
        super().set_look(look)
        self.label = look.label or self.label
        self._make_launches()
        self._rebind_parts()

    def _bind_parts(self) -> None:
        """Runs the programs of the bound parts of the look; Home Assistant gets their values."""
        self.bound.bind(self.look.parts, self.look.buttons)
        if self.controls is not None:
            self.controls.attach(self.bound.fader, self.bound.encoder)
        self._warn_missing_entities()

    def _warn_missing_entities(self) -> None:
        """
        A place can't move a part into Home Assistant: its entities are the channel's. Such a part shows what it does
        while Home Assistant is not there; the log says why. Not in Simulate, which has no MQTT at all.
        """
        if self.env.bridge is None:
            return
        controls = self.controls
        parts = self.look.parts
        missing = [
            *(["lcd"] if parts.lcd == HOME_ASSISTANT and (controls is None or controls.bottom is None) else []),
            *(["color"] if parts.color == HOME_ASSISTANT and (controls is None or controls.color is None) else []),
            *(["meter"] if parts.meter == HOME_ASSISTANT and (controls is None or controls.meter is None) else []),
            *(
                f"{button.name.lower()}.led"
                for button, setup in self.look.buttons.items()
                if setup.led == HOME_ASSISTANT and (controls is None or button.name.lower() not in controls.leds)
            ),
        ]
        for part in missing:
            if part not in self._warned:
                self._warned.add(part)
                _LOGGER.warning(
                    f'{self.identity.name}: {part} = "homeassistant" works on the channel itself only, not on a place'
                )

    def _rebind_parts(self) -> None:
        """The bound parts of another look: the encoder does what its binding says now."""
        encoder = self.bound.encoder
        self._bind_parts()
        if self.bound.encoder is not encoder:
            self._make_knob()

    def _parts_changed(self) -> None:
        """A bound part changed (a value, a line of a watch, an entity of Home Assistant): the strip shows it."""
        self.show()
        if self.state_known is not None:
            self.show_buttons(self.state_known)

    @property
    def launches(self) -> bool:
        """Whether a button starts a program of its own (`{ launch = [...] }`)."""
        return bool(self._launches)

    def _make_launches(self) -> None:
        """A `LaunchButton` per button that starts a program of its own (`{ launch = [...] }`)."""
        launches: dict[Button, LaunchButton] = {}
        for button, setup in self.look.buttons.items():
            for action in (setup.press, setup.hold):
                if isinstance(action, LaunchAction):
                    before = self._launches.get(button)
                    keep = before is not None and before.command == action.launch
                    launches[button] = (
                        before
                        if keep and before is not None
                        else LaunchButton(
                            action.launch, self.env.launcher, self.identity.name, action.launch_when_running
                        )
                    )
        self._launches = launches

    def set_place(self, encoder: EncoderMode, min_volume: int | None, max_volume: int | None) -> None:
        """What the encoder does and the volume range: those of the place the strip is on now."""
        self.encoder_mode = encoder
        self.min_volume = min_volume
        self.max_volume = max_volume
        self._make_knob()

    def set_taken(self, taken: frozenset[Claimable]) -> None:
        """With the fader taken (and not the encoder), the encoder sets the volume, as with a Home Assistant fader."""
        before = self._knob_mode()
        super().set_taken(taken)
        if self._knob_mode() != before:
            self._make_knob()

    def _knob_mode(self) -> EncoderMode | None:
        """What the encoder does now: a mode, or None for the value of its binding (`Look.parts`)."""
        if "fader" in self.taken and "encoder" not in self.taken:
            return "volume"
        if self.bound.encoder is not None:
            return None
        return self.encoder_mode

    def _new_knob(self) -> Knob:
        mode = self._knob_mode()
        if mode is None:
            assert self.bound.encoder is not None, "the encoder is bound to a program"
            return CommandKnob(self, self.bound.encoder)
        return self.make_knob(mode)

    def _make_knob(self) -> None:
        self.knob.close()
        self.knob = self._new_knob()

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
        raise NotImplementedError

    def playing(self, state: AudioState) -> bool:
        """Whether audio flows through what the strip controls."""
        raise NotImplementedError

    def is_default(self, state: AudioState) -> bool:
        """Whether the strip controls the default device."""
        return False

    # -- showing --------------------------------------------------------------------------------------------------

    def update(self, state: AudioState) -> None:
        self.state_known = state
        self.level, self.active = self.current(state)
        self.show()
        self.show_buttons(state)

    def show_buttons(self, state: AudioState) -> None:
        """The LEDs of Select, Rec and Solo, as their `led` says."""
        for button, setup in self.look.buttons.items():
            self.strip.set_led(button, self.button_led(button, setup, state))

    def button_led(self, button: Button, setup: ButtonSetup, state: AudioState) -> Led:
        if (shown := indicator(setup.led)) is not None:
            return Led.ON if self.indicates(shown, state) else Led.OFF
        if isinstance(setup.led, WatchBinding):
            line = self.bound.line(led_key(button))
            return led_of_line(line) if line is not None else Led.OFF
        if setup.led == "homeassistant":
            return self.controls.led(button.name.lower()) if self.controls is not None else Led.OFF
        if setup.led == "shown":
            return Led.ON if self.shows_other() else Led.OFF
        return self.action_led(button, setup.press, state)

    def action_led(self, button: Button, action: Action, state: AudioState) -> Led:
        """What the LED of a button shows for its press (`led = "press"`)."""
        match action:
            case LaunchAction():
                launch = self._launches[button]
                return launch.led(launch.program_runs(self.env.processes()))
            case "off" | "homeassistant" | RunAction():
                return Led.OFF
            case "talk" | "mute_others":
                return Led.ON if button in self._acting else Led.OFF
            case "cycle_modes":
                return Led.ON if self.env.actions is not None and self.env.actions.mode != "default" else Led.OFF
            case str() if action.startswith(("mode:", "toggle:")):
                actions = self.env.actions
                if actions is None:
                    return Led.OFF
                if action.startswith("mode:"):
                    return Led.ON if actions.mode == action.removeprefix("mode:") else Led.OFF
                return Led.ON if actions.value(action.removeprefix("toggle:")) else Led.OFF
            case _:
                return Led.ON if self.action_lit(action, state) else Led.OFF

    def action_lit(self, action: str, state: AudioState) -> bool:
        """Whether the LED of an action of the kind of strip is lit (`default`, `next`, `profile`, `launch`)."""
        return False

    def shows_other(self) -> bool:
        """Whether the strip shows another device than the default one (after `next`)."""
        return False

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
        if self.bound.fader is not None:
            # the look binds it to a program
            return None
        return self.controls.fader if self.controls is not None else None

    @property
    def fader_sets_volume(self) -> bool:
        """Whether the fader sets the volume: it is not bound to Home Assistant or to a program."""
        return self.bound.fader is None and not self.fader_in_home_assistant

    @property
    def color(self) -> Color:
        return color_of(self.color_name)

    @property
    def color_name(self) -> ColorName:
        """The color of the LCD: the look's, or what its binding says (the look's until that is known)."""
        part = self.look.parts.color
        if isinstance(part, WatchBinding):
            return self.bound.color or self.look.color
        if part == "homeassistant" and self.controls is not None:
            return self.controls.color_name(self.look.color)
        return self.look.color

    def second_line(self, text: str) -> str:
        """The second line of the LCD: `text`, what the strip type shows there, unless `lcd` binds it."""
        part = self.look.parts.lcd
        if isinstance(part, WatchBinding):
            return self.bound.line("lcd") or ""
        if part == "homeassistant":
            return self.controls.bottom_text() if self.controls is not None else OFFLINE_TEXT
        return text

    def held_meter(self, point: MeterPoint) -> Reading | None:
        """The level a binding of the meter sets (`Look.parts`): a watch's, or Home Assistant's; else none."""
        part = self.look.parts.meter
        if isinstance(part, LevelBinding):
            line = self.bound.line("meter")
            level = level_of_line(line, part.min, part.max) if line is not None else None
            return Lit(round(level * METER_MAX)) if level is not None else None
        if part == "homeassistant" and self.controls is not None:
            return self.controls.meter_level()
        return None

    def show(self) -> None:
        self.strip.set_color(self.color if self.active or self.look.lit_when_idle else Color.BLACK)
        self.strip.set_text(0, self.label)
        if self.bound.fader is not None:
            self._show_value_fader()
        elif self.ha_fader is not None and self.controls is not None and self.controls.connected:
            self.ha_fader.show()
        level = self.level
        if level is None or not self.active:
            # nothing to control (e.g. an application that ended): the fader goes away
            if self.fader_sets_volume:
                self.strip.park()
            self.strip.set_ring(*(self.knob.ring() if self.knob.idle_too else (0, RingMode.DOT)))
            self.strip.set_led(Button.MUTE, Led.OFF)
            self.strip.set_text(1, self.notice or self.second_line(self.inactive_text()))
            return
        if self.fader_sets_volume:
            self.strip.set_fader(self._fraction(level.volume))
        self.strip.set_ring(*self.knob.ring())
        self.strip.set_led(Button.MUTE, Led.ON if level.muted else Led.OFF)
        if self.notice is not None:
            self.strip.set_text(1, self.notice)
        elif self._wanted is not None:
            self.strip.set_text(1, f"{self._wanted}%")
        else:
            self.strip.set_text(1, self.second_line("muted" if level.muted else f"{level.volume}%"))

    def _show_value_fader(self) -> None:
        """The fader bound to a program shows its value (down while it is not known), but not under a finger."""
        value = self.bound.fader
        assert value is not None, "the fader is bound to a program"
        if value.touched:
            return
        fraction = value.fraction()
        if fraction is None:
            self.strip.park()
        else:
            self.strip.set_fader(fraction)

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
        if (value := self.bound.fader) is not None:
            # also while the strip is idle: the value is not the audio's
            value.moved(fraction)
            self.notify(value.text())
        elif self.ha_fader is not None and self.controls is not None:
            if self.controls.connected:
                self.ha_fader.moved(fraction)
        elif self.fader_sets_volume and self.accepts_input():
            bottom, top = self.volume_range()
            self.set_volume(round(fader_volume(fraction, bottom, top, self.env.behavior.unity_at)))

    def on_encoder(self, steps: int) -> None:
        if self.knob.idle_too or self.accepts_input():
            self.knob.turn(steps)

    def on_encoder_press(self, pressed: bool) -> None:
        if self.knob.idle_too or self.accepts_input():
            self.knob.push(pressed)

    def on_touch(self, touched: bool) -> None:
        if (value := self.bound.fader) is not None:
            value.touch(touched)
            if not touched:
                # let go, it stays where the hand left it (or goes where `watch` said meanwhile)
                self._show_value_fader()
        elif self.ha_fader is not None and self.controls is not None:
            self.ha_fader.touch(touched)
            self.ha_event("fader_touched" if touched else "fader_released")

    def ha_event(self, event_type: str) -> None:
        """An event of the fader or the encoder for Home Assistant."""
        if self.controls is not None and self.controls.events is not None and self.controls.connected:
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
        if self.fader_sets_volume:
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
        for timer in self._holds.values():
            timer.cancel()
        self._holds.clear()
        for button in list(self._acting):
            self._end_action(button)
        if self.controls is not None:
            self.controls.close()
        self.bound.close()

    def on_button(self, button: Button, pressed: bool) -> None:
        if button == Button.MUTE:
            if pressed and self.level is not None and self.accepts_input():
                self.run_command(self.apply_mute(not self.level.muted), "mute")
            return
        setup = self.look.buttons.get(button)
        if setup is None or not setup.acts:
            return
        if pressed:
            if setup.hold == "off":
                self._start_action(button, setup.press)
            else:
                self._cancel_hold(button)
                self._holds[button] = asyncio.get_running_loop().call_later(HOLD_TIME, self._held, button, setup.hold)
            return
        timer = self._holds.pop(button, None)
        if timer is not None:
            # let go before the hold: a press
            timer.cancel()
            self._start_action(button, setup.press)
        self._end_action(button)

    def _cancel_hold(self, button: Button) -> None:
        timer = self._holds.pop(button, None)
        if timer is not None:
            timer.cancel()

    def _held(self, button: Button, action: Action) -> None:
        self._holds.pop(button, None)
        self._start_action(button, action)

    def _start_action(self, button: Button, action: Action) -> None:
        if isinstance(action, str) and action in WHILE_HELD:
            self._acting[button] = action
        self.act(button, action, True)
        if self.state_known is not None:
            self.show_buttons(self.state_known)

    def _end_action(self, button: Button) -> None:
        action = self._acting.pop(button, None)
        if action is None:
            return
        self.act(button, action, False)
        if self.state_known is not None:
            self.show_buttons(self.state_known)

    def act(self, button: Button, action: Action, down: bool) -> None:
        """
        Does an action of a button: once (`down`), or for an action that lasts while held (`WHILE_HELD`) its start
        and its end.
        """
        actions = self.env.actions
        match action:
            case "off":
                pass
            case LaunchAction():
                launch = self._launches[button]
                launch.press(launch.program_runs(self.env.processes()))
            case RunAction():
                self.run_action(button, action)
            case "talk":
                self.talk(down)
            case "mute_others":
                self.env.solo(self, down)
            case "homeassistant":
                self.ha_event(f"{button.name.lower()}_{'pressed' if down else 'released'}")
            case str() if action == "cycle_modes" or action.startswith(("mode:", "toggle:")):
                if actions is None:
                    _LOGGER.warning(f"{self.identity.name}: {action} needs the slots")
                elif action == "cycle_modes":
                    actions.cycle_modes()
                elif action.startswith("mode:"):
                    actions.choose_mode(action.removeprefix("mode:"))
                else:
                    actions.toggle(action.removeprefix("toggle:"))
            case _:
                self.do(action)

    def run_action(self, button: Button, action: RunAction) -> None:
        """Runs the program of a button; `{value}` in it is the value of the fader (see `value_for_run()`)."""
        argv = action.run
        what = f"{self.identity.name}.{button.name.lower()}"
        if "value" in placeholders_of(argv):
            value = self.value_for_run()
            if value is None:
                _LOGGER.warning(f"{what}: {argv[0]} needs the value, which is not known yet")
                return
            argv = tuple(fill(argv, value=value_text(value)))
        run_program(self.env.commands, argv, what)

    def value_for_run(self) -> float | None:
        """
        What `{value}` is in the program of a button: the value of the fader if it is bound to a program, else of the
        encoder if it is, else the volume; None while it is not known.
        """
        if self.bound.fader is not None:
            return self.bound.fader.value
        if self.bound.encoder is not None:
            return self.bound.encoder.value
        if self._wanted is not None:
            return self._wanted
        return self.level.volume if self.level is not None else None

    def do(self, action: str) -> None:
        """An action of the kind of strip: `default`, `next`, `profile`, `launch`."""
        _LOGGER.debug(f"{self.identity.name}: {type(self).__name__} can't {action}")

    def talk(self, down: bool) -> None:
        """Push to talk: Mute goes off while the button is held, and on again when it is let go."""
        if down:
            if self.level is not None and self.level.muted and self.accepts_input():
                self._talking = True
                self.run_command(self.apply_mute(False), "talk")
        elif self._talking:
            self._talking = False
            self.run_command(self.apply_mute(True), "talk ends")

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
            self._setter = asyncio.create_task(self._apply_wanted(), name=f"{self.identity.name}: volume")
            self._tasks.add(self._setter)
            self._setter.add_done_callback(self._tasks.discard)

    async def _apply_wanted(self) -> None:
        while self._wanted is not None:
            volume = self._wanted
            _LOGGER.debug(f"{self.identity.name}: volume {volume}%")
            try:
                await self.apply_volume(volume)
            except AudioCommandError as e:
                _LOGGER.warning(f"{self.identity.name}: setting the volume: {e}")
            else:
                # until the sound server reports it, so the old volume does not flash up
                if self.level is not None:
                    # the rest (the balance) as it was: the ring of the balance would go dark for a moment
                    self.level = replace(self.level, volume=volume)
            if self._wanted == volume:
                self._wanted = None
        self.show()
