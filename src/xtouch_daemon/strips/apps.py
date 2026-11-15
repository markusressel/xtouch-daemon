"""Strips for the playback streams of applications: a configured group of them, or one `auto` picked."""

import asyncio
import logging
import time
from collections.abc import Callable

from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState, Stream
from xtouch_daemon.protocol import Color
from xtouch_daemon.strips.base import Level, StripEnv, VolumeStrip
from xtouch_daemon.surface import Strip

_LOGGER = logging.getLogger(__name__)


class AppStrip(VolumeStrip):
    """
    The volume of a set of streams. The fader and the encoder set all of them to the same volume, a stream that
    starts later gets it too. The mute button mutes all (or unmutes them when all are muted). The strip shows the
    loudest of them, and the meter the level of all of them together.

    While none of them is there, the strip shows "idle" on a dark LCD. The fader still sets the volume the next
    stream gets.

    It changes the volume of the streams themselves, like the per-application sliders of pavucontrol.
    """

    def __init__(self, strip: Strip, env: StripEnv, label: str, color: Color = Color.WHITE, meter: bool = True):
        super().__init__(strip, env, label, color, meter)
        self.streams: dict[int, Stream] = {}
        self.group_volume: int | None = None
        """The volume of the strip: set on the strip, or the loudest stream; None before the first stream."""

    def streams_in(self, state: AudioState) -> tuple[Stream, ...]:
        raise NotImplementedError

    def inactive_text(self) -> str:
        return "idle"

    def accepts_input(self) -> bool:
        return True

    def current(self, state: AudioState) -> tuple[Level | None, bool]:
        streams = {stream.index: stream for stream in self.streams_in(state)}
        group_volume = self.group_volume
        for index, stream in streams.items():
            if index not in self.streams and group_volume is not None and stream.volume != group_volume:
                _LOGGER.info(f"{self.label}: {stream.app} starts at {group_volume}%")
                self.run_command(self.env.backend.set_stream_volume(index, group_volume), f"volume of {stream.app}")
        previous, self.streams = self.streams, streams
        if not streams:
            return (Level(group_volume, False) if group_volume is not None else None), False
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
        return Level(volume, all(stream.muted for stream in streams.values())), True

    def meter_targets(self, state: AudioState) -> set[CaptureTarget]:
        if not self.meter:
            return set()
        return {CaptureTarget(str(stream.index), monitor=False) for stream in self.streams_in(state)}

    def is_playing(self, target: CaptureTarget, state: AudioState) -> bool:
        return any(str(stream.index) == target.node and stream.playing for stream in state.streams)

    async def apply_volume(self, percent: int) -> None:
        self.group_volume = percent
        await self._for_all(lambda index: self.env.backend.set_stream_volume(index, percent), "volume")

    async def apply_mute(self, muted: bool) -> None:
        await self._for_all(lambda index: self.env.backend.set_stream_mute(index, muted), "mute")

    async def _for_all(self, command: Callable[[int], object], what: str) -> None:
        results = await asyncio.gather(*(command(index) for index in self.streams), return_exceptions=True)  # type: ignore[arg-type]
        for result in results:
            if isinstance(result, Exception):
                _LOGGER.warning(f"{self.label}: {what}: {result}")


class AppGroupStrip(AppStrip):
    """The streams of the applications whose name or binary contains one of `patterns` (ignoring case)."""

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        patterns: tuple[str, ...],
        label: str,
        color: Color = Color.WHITE,
        meter: bool = True,
    ):
        super().__init__(strip, env, label, color, meter)
        self.patterns = patterns

    def streams_in(self, state: AudioState) -> tuple[Stream, ...]:
        return state.streams_matching(self.patterns)


class AutoStrip(AppStrip):
    """The streams of the application the `AutoAssigner` gave the strip, under its alias. Dark while it has none."""

    def __init__(
        self, strip: Strip, env: StripEnv, aliases: dict[str, str], color: Color = Color.WHITE, meter: bool = True
    ):
        super().__init__(strip, env, "", color, meter)
        self.aliases = aliases
        self.app: str | None = None

    def assign(self, app: str | None) -> None:
        if app == self.app:
            return
        self.app = app
        self.label = "" if app is None else self.aliases.get(app, app)
        # a new application keeps its own volume
        self.streams = {}
        self.group_volume = None

    def streams_in(self, state: AudioState) -> tuple[Stream, ...]:
        return state.streams_of_app(self.app) if self.app is not None else ()

    def inactive_text(self) -> str:
        return "" if self.app is None else "idle"

    def accepts_input(self) -> bool:
        return self.app is not None


class AutoAssigner:
    """
    Gives the `auto` strips the applications that play and have no strip of their own, in the order they started.
    An application keeps its strip while it plays, and for `hold` seconds after it stopped (so it does not jump
    between strips from one track to the next).
    """

    def __init__(self, slots: int, hold: float, ignore: tuple[str, ...], clock: Callable[[], float] = time.monotonic):
        self.assigned: list[str | None] = [None] * slots
        self.hold = hold
        self.ignore = ignore
        self._clock = clock
        self._stopped_at: dict[str, float] = {}

    def assign(self, state: AudioState, claimed: tuple[tuple[str, ...], ...] = ()) -> list[str | None]:
        """The application of every slot. `claimed` are the patterns of the strips with applications of their own."""
        now = self._clock()
        playing: list[str] = []
        for stream in sorted(state.streams, key=lambda stream: stream.index):
            if not stream.playing or stream.app in playing or stream.matches(self.ignore):
                continue
            if any(stream.matches(patterns) for patterns in claimed):
                continue
            playing.append(stream.app)

        for slot, app in enumerate(self.assigned):
            if app is None:
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
