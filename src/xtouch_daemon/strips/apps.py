"""Strips for the playback streams of applications: a configured group of them, or one `auto` picked."""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState, Stream
from xtouch_daemon.config.values import EncoderMode
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.strips.base import Identity, Level, Look, StripEnv, VolumeStrip
from xtouch_daemon.strips.knobs import Knob, MediaKnob, PickKnob
from xtouch_daemon.system.launch import LaunchButton
from xtouch_daemon.system.processes import process_matching

if TYPE_CHECKING:
    from xtouch_daemon.strips.homeassistant import HomeAssistantControls

_LOGGER = logging.getLogger(__name__)


class AppStrip(VolumeStrip):
    """
    The volume of a set of streams. The fader and the encoder set all of them to the same volume, a stream that
    starts later gets it too. The mute button mutes all (or unmutes them when all are muted). The strip shows the
    loudest of them, and the meter the level of all of them together.

    While none of them is there, the strip shows "idle" on a dark LCD, its fader is down and does nothing. The strip
    keeps its volume: the next stream gets it. A paused media player of the applications keeps the strip active (see
    `MediaKnob`): the fader sets the volume the next stream gets.

    It changes the volume of the streams themselves, like the per-application sliders of pavucontrol.
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
        super().__init__(strip, env, identity, look, min_volume, max_volume, encoder, controls)
        self.streams: dict[int, Stream] = {}
        self.group_volume: int | None = None
        """The volume of the strip: set on the strip, or the loudest stream; None before the first stream."""
        self.launch: LaunchButton | None = None
        """What Select starts while the applications do not run (`launch`)."""
        self.state: AudioState | None = None
        """The state shown last."""

    def streams_in(self, state: AudioState) -> tuple[Stream, ...]:
        raise NotImplementedError

    def runs(self, state: AudioState) -> bool:
        """Whether one of the applications runs, for `launch`: by default when the program of `launch` runs."""
        return self.launch is not None and self.launch.program_runs(self.env.processes())

    @property
    def launches(self) -> bool:
        return self.launch is not None

    def update(self, state: AudioState) -> None:
        self.state = state
        super().update(state)
        if self.launch is not None:
            self._show_launch(self.launch, state)

    def _show_launch(self, launch: LaunchButton, state: AudioState) -> None:
        self.strip.set_led(Button.SELECT, launch.led(self.runs(state)))

    def on_button(self, button: Button, pressed: bool) -> None:
        if pressed and button == Button.SELECT and self.launch is not None and self.state is not None:
            if self.launch.press(self.runs(self.state)):
                self._show_launch(self.launch, self.state)
            return
        super().on_button(button, pressed)

    def inactive_text(self) -> str:
        return "idle"

    def make_knob(self, encoder: EncoderMode) -> Knob:
        return MediaKnob(self) if encoder == "media" else super().make_knob(encoder)

    def playing(self, state: AudioState) -> bool:
        return any(stream.playing for stream in self.streams_in(state))

    def current(self, state: AudioState) -> tuple[Level | None, bool]:
        streams = {stream.index: stream for stream in self.streams_in(state)}
        group_volume = self.group_volume
        for index, stream in streams.items():
            if index not in self.streams and group_volume is not None and stream.volume != group_volume:
                _LOGGER.info(f"{self.label}: {stream.app} starts at {group_volume}%")
                self.run_command(self.env.backend.set_stream_volume(index, group_volume), f"volume of {stream.app}")
        previous, self.streams = self.streams, streams
        if not streams:
            return (Level(group_volume, False) if group_volume is not None else None), self.knob.keeps_active()
        known = [stream.volume for index, stream in streams.items() if index in previous]
        if known:
            # the streams that were there before show what the volume is (it may have been changed elsewhere)
            volume = max(known)
        elif group_volume is not None:
            # only new streams: they are about to get the volume of the strip
            volume = group_volume
        else:
            volume = max(stream.volume for stream in streams.values())
        self.group_volume = volume
        # the balance of the first one: they get the same
        balance = streams[min(streams)].balance
        return Level(volume, all(stream.muted for stream in streams.values()), balance), True

    @property
    def title(self) -> str:
        return self.label

    def release(self) -> None:
        """What kept the strip active without streams is gone (see `Knob.keeps_active()`)."""
        if not self.streams:
            self.active = False
            self.show()

    def meter_targets(self, state: AudioState) -> set[CaptureTarget]:
        if not self.meter:
            return set()
        return {CaptureTarget(str(stream.index), monitor=False) for stream in self.streams_in(state)}

    def is_playing(self, target: CaptureTarget, state: AudioState) -> bool:
        return any(str(stream.index) == target.node and stream.playing for stream in state.streams)

    def target_gain(self, target: CaptureTarget, state: AudioState) -> float | None:
        return next((stream.gain for stream in state.streams if str(stream.index) == target.node), None)

    async def apply_volume(self, percent: int) -> None:
        self.group_volume = percent
        await self._for_all(lambda index: self.env.backend.set_stream_volume(index, percent), "volume")

    async def apply_mute(self, muted: bool) -> None:
        await self._for_all(lambda index: self.env.backend.set_stream_mute(index, muted), "mute")

    async def apply_balance(self, balance: float) -> None:
        await self._for_all(lambda index: self.env.backend.set_stream_balance(index, balance), "balance")

    async def _for_all(self, command: Callable[[int], object], what: str) -> None:
        results = await asyncio.gather(*(command(index) for index in self.streams), return_exceptions=True)  # type: ignore[arg-type]
        for result in results:
            if isinstance(result, Exception):
                _LOGGER.warning(f"{self.label}: {what}: {result}")


class AppGroupStrip(AppStrip):
    """
    The streams of the applications whose name or binary contains one of `patterns` (ignoring case). `processes` are
    the parts of the names of their processes (by default `patterns`), which count as the applications running.
    """

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        identity: Identity,
        patterns: tuple[str, ...],
        look: Look,
        min_volume: int | None = None,
        max_volume: int | None = None,
        encoder: EncoderMode = "volume",
        controls: HomeAssistantControls | None = None,
        processes: tuple[str, ...] | None = None,
    ):
        super().__init__(strip, env, identity, look, min_volume, max_volume, encoder, controls)
        self.patterns = patterns
        self.processes = patterns if processes is None else processes

    def streams_in(self, state: AudioState) -> tuple[Stream, ...]:
        return state.streams_matching(self.patterns)

    def runs(self, state: AudioState) -> bool:
        """
        An application of the group has a stream, or a process whose name contains one of `processes` runs (like the
        `processes` rule of a layout), or the program of `launch`: a silent voice chat runs too.
        """
        return (
            bool(self.streams_in(state))
            or process_matching(self.processes, self.env.processes()) is not None
            or super().runs(state)
        )

    def recording(self, state: AudioState) -> bool:
        return state.records_matching(self.patterns)


class PickSlot(Protocol):
    """Where the `pick` encoder of an `auto` strip picks and pins its application."""

    @property
    def pinned(self) -> bool: ...

    def position(self) -> tuple[int, int] | None:
        """Which of how many candidates the slot has, None for none of them."""
        ...

    def pick(self, steps: int) -> None: ...
    def toggle_pin(self) -> None: ...


class AutoStrip(AppStrip):
    """
    The streams of the application the `AutoAssigner` gave the strip, under its alias. Dark while it has none. With
    `encoder = "pick"`, the encoder picks the application (`slot`, which the mixer gives it) and a push pins it.
    """

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        identity: Identity,
        aliases: dict[str, str],
        look: Look,
        min_volume: int | None = None,
        max_volume: int | None = None,
        encoder: EncoderMode = "volume",
        controls: HomeAssistantControls | None = None,
    ):
        super().__init__(strip, env, identity, look, min_volume, max_volume, encoder, controls)
        self.aliases = aliases
        self.app: str | None = None
        self.slot: PickSlot | None = None
        """Where it picks its application: its place in the `AutoAssigner`, or the slot of channels and states."""

    def make_knob(self, encoder: EncoderMode) -> Knob:
        return PickKnob(self) if encoder == "pick" else super().make_knob(encoder)

    def set_look(self, look: Look) -> None:
        # the label is the application's
        self.look = look

    def assign(self, app: str | None) -> None:
        if app == self.app:
            return
        self.app = app
        self.label = "" if app is None else self.aliases.get(app, app)
        # a new application keeps its own volume, and its own player
        self.streams = {}
        self.group_volume = None
        self.knob.reset()

    def streams_in(self, state: AudioState) -> tuple[Stream, ...]:
        return state.streams_of_app(self.app) if self.app is not None else ()

    def runs(self, state: AudioState) -> bool:
        """The strip has an application (it plays, was picked, or its hold time is not over), or `launch`'s runs."""
        return self.app is not None or super().runs(state)

    def recording(self, state: AudioState) -> bool:
        return self.app is not None and state.records_app(self.app)

    def inactive_text(self) -> str:
        return "" if self.app is None else "idle"

    @property
    def title(self) -> str:
        return self.label or "auto"


class AutoAssigner:
    """
    Gives the `auto` strips the applications that play and have no strip of their own, in the order they started.
    An application keeps its strip while it plays, and for `hold` seconds after it stopped (so it does not jump
    between strips from one track to the next). A pinned slot keeps its application until it is unpinned. `pick`
    puts another application into a slot.
    """

    def __init__(self, slots: int, hold: float, ignore: tuple[str, ...], clock: Callable[[], float] = time.monotonic):
        self.assigned: list[str | None] = [None] * slots
        self.hold = hold
        self.ignore = ignore
        self._clock = clock
        self._stopped_at: dict[str, float] = {}
        self.pinned: set[int] = set()
        """The slots that keep their application."""

    def _apps(self, state: AudioState, claimed: tuple[tuple[str, ...], ...], playing: bool) -> list[str]:
        """The applications without a strip of their own, in the order they started (only the ones that play)."""
        apps: list[str] = []
        for stream in sorted(state.streams, key=lambda stream: stream.index):
            if (playing and not stream.playing) or stream.app in apps or stream.matches(self.ignore):
                continue
            if any(stream.matches(patterns) for patterns in claimed):
                continue
            apps.append(stream.app)
        return apps

    def candidates(self, state: AudioState, claimed: tuple[tuple[str, ...], ...] = ()) -> list[str]:
        """What a slot can pick: the applications without a strip of their own that are there, paused ones too."""
        return self._apps(state, claimed, playing=False)

    def pick(self, slot: int, steps: int, state: AudioState, claimed: tuple[tuple[str, ...], ...] = ()) -> None:
        """
        Moves the slot `steps` applications on among the candidates; one that another slot has swaps with it. A
        pinned slot stays pinned, with the new application.
        """
        candidates = self.candidates(state, claimed)
        if not candidates:
            return
        current = self.assigned[slot]
        if current in candidates:
            app = candidates[(candidates.index(current) + steps) % len(candidates)]
        else:
            app = candidates[0 if steps > 0 else -1]
        if app in self.assigned:
            self.assigned[self.assigned.index(app)] = current
        self.assigned[slot] = app
        self._stopped_at.pop(app, None)

    def toggle_pin(self, slot: int) -> None:
        """Pins the slot (only one with an application), or unpins it."""
        if slot in self.pinned:
            self.pinned.discard(slot)
        elif self.assigned[slot] is not None:
            self.pinned.add(slot)

    def assign(self, state: AudioState, claimed: tuple[tuple[str, ...], ...] = ()) -> list[str | None]:
        """The application of every slot. `claimed` are the patterns of the strips with applications of their own."""
        now = self._clock()
        playing = self._apps(state, claimed, playing=True)

        for slot, app in enumerate(self.assigned):
            if app is None or slot in self.pinned:
                continue
            if app in playing:
                self._stopped_at.pop(app, None)
            elif now - self._stopped_at.setdefault(app, now) >= self.hold:
                self.assigned[slot] = None
                del self._stopped_at[app]

        for app in playing:
            if app in self.assigned:
                continue
            if None not in self.assigned:
                break
            self.assigned[self.assigned.index(None)] = app
        return list(self.assigned)


class AutoSlot:
    """A slot of the `AutoAssigner` for its strip: picks and pins with the current state, then shows the result."""

    def __init__(
        self,
        assigner: AutoAssigner,
        index: int,
        state: Callable[[], AudioState],
        claimed: tuple[tuple[str, ...], ...],
        refresh: Callable[[], None],
    ):
        self.assigner = assigner
        self.index = index
        self._state = state
        self._claimed = claimed
        self._refresh = refresh

    @property
    def pinned(self) -> bool:
        return self.index in self.assigner.pinned

    def position(self) -> tuple[int, int] | None:
        """Which of how many candidates the slot has, None for none of them."""
        candidates = self.assigner.candidates(self._state(), self._claimed)
        app = self.assigner.assigned[self.index]
        return (candidates.index(app), len(candidates)) if app in candidates else None

    def pick(self, steps: int) -> None:
        self.assigner.pick(self.index, steps, self._state(), self._claimed)
        self._refresh()

    def toggle_pin(self) -> None:
        self.assigner.toggle_pin(self.index)
        self._refresh()
