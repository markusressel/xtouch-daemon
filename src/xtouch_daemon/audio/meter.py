"""
Audio levels for the LED meters: the peaks of audio captured with `pw-record`.

The captures are passive (`node.passive`): they never wake a device. A meter shows a level only while something else
plays to the output or records from the input, so it does not keep an output from suspending, light the microphone
indicator of the desktop, or switch Bluetooth headphones into their headset mode.

They are native PipeWire streams on purpose: WirePlumber 0.5.18 (PipeWire 1.6.10) restores captures of PulseAudio
clients (`parec`, peak detection streams) at 0 % volume, so they would only get silence.

Where the volume is (measured with PipeWire 1.6.10, see docs/architecture.md): a stream and an input apply their
volume and Mute in their own node (audioconvert), so everything that links to them gets the audio after both. The
monitor of an output is taken before the output's volume and Mute (`monitor.channel-volumes` is off by default). The
meters capture what they can and turn it into the level of the strip's `meter_point` with the volume the sound server
tells (`scale_of()`): the audio of a muted stream or input is gone, its pre-fader level with it.
"""

import array
import asyncio
import contextlib
import logging
import math
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from xtouch_daemon.config import MeterPoint
from xtouch_daemon.protocol import METER_MAX, METER_SIGNAL_MAX

_LOGGER = logging.getLogger(__name__)

FLOOR_DB = -60.0
"""The level of the lowest LED: the levels up to METER_SIGNAL_MAX split FLOOR_DB..0 dB evenly (5 dB each)."""
CLIP_HOLD = 0.5
"""
Seconds the meter stays full, the red clip LED lit, after a peak at full scale: the device lets it fall at once, a
single clip would only flash.
"""
CAPTURE_RATE = 8000
"""The audio is only looked at for its peaks, a low rate costs next to nothing."""
CAPTURE_CHANNELS = 2
CHUNK_BYTES = CAPTURE_RATE * CAPTURE_CHANNELS * 4 // 50
"""Read at once: 20 ms of float32 samples."""
STALL_TIMEOUT = 3.0
"""
A capture that gets no audio for this long although what it captures plays is started again: WirePlumber links a
passive capture only once and gives up when that fails (e.g. "item deactivated before format was set" while Bluetooth
headphones go away and the streams move).
"""
RESTART_DELAY = 1.0
GAIN_SETTLE = 0.3
"""
Seconds a volume still counts after it changed, for a pre-fader level from audio captured after the volume: the
audio comes that much later than the news of the change, so a fader pulled down would make the level of the audio
from before jump up (and light the clip LED). Until then the level is divided by the loudest of these volumes, which
shows it too low for a moment instead.
"""
PW_RECORD = "pw-record"
STDBUF = shutil.which("stdbuf")
"""
`stdbuf -o0` (coreutils) runs pw-record with unbuffered output: buffered, it writes 4096 bytes at a time (64 ms here),
so the meters came late, and two meters of the same audio apart by up to that much. Unbuffered it writes every
cycle of the graph (about 10 ms). Without it the meters work all the same, only later.
"""


def peak_of(data: bytes) -> float:
    """The peak of float32 samples (1.0 is full scale)."""
    samples = array.array("f")
    samples.frombytes(data[: len(data) - len(data) % 4])
    if not samples:
        return 0.0
    return max(max(samples), -min(samples))


def level_of(peak: float) -> int:
    """
    The meter level of a peak: 0 below FLOOR_DB, up to METER_SIGNAL_MAX just below full scale, and METER_MAX (the
    clip LED) at full scale and above.
    """
    if peak >= 1.0:
        return METER_MAX
    if peak <= 0.0:
        return 0
    db = 20 * math.log10(peak)
    return max(0, min(METER_SIGNAL_MAX, math.ceil((db - FLOOR_DB) / -FLOOR_DB * METER_SIGNAL_MAX)))


@dataclass(frozen=True)
class CaptureTarget:
    node: str | None
    """A node name, or the serial of a stream (the index PulseAudio tools show); None for the default output."""
    monitor: bool
    """The node is an output: its monitor is captured."""


def scale_of(
    target: CaptureTarget, point: MeterPoint, gain: float | None, settled: float | None = None
) -> float | None:
    """
    What the peaks captured from the target are multiplied by for the level at `point`, with `gain` the volume of the
    target (with Mute, see `Device.gain`; None if unknown: the peaks as they come) and `settled` the loudest of its
    gains of the last GAIN_SETTLE seconds. None: the capture tells nothing about that level (a muted stream).

    The monitor of an output is before its volume, the audio of a stream or an input after it.
    """
    if gain is None:
        return 1.0
    if point == "post_fader":
        return gain if target.monitor else 1.0
    if target.monitor:
        return 1.0
    if gain <= 0.0:
        return None
    return 1.0 / max(gain, settled or 0.0)


def capture_command(target: CaptureTarget, command: str = PW_RECORD, stdbuf: str | None = STDBUF) -> list[str]:
    properties = [
        "node.passive = true",
        'application.name = "xtouch-daemon"',
        'media.name = "X-Touch meter"',
        # not saved by WirePlumber (it would restore the volume of a capture it has not seen before as 0 %)
        "state.restore-props = false",
        *(["stream.capture.sink = true"] if target.monitor else []),
        # stays with its target: WirePlumber makes a stream whose target is the default when it is linked follow the
        # default from then on (like PulseAudio), so the meter of the default output would show the next default
        # output after Select. A target that is not there ends the capture instead of linking it to the default.
        *(["node.dont-reconnect = true"] if target.node is not None else []),
    ]
    return [
        *([stdbuf, "-o0"] if stdbuf is not None else []),
        command,
        *(["--target", target.node] if target.node is not None else []),
        "-P",
        "{ " + " ".join(properties) + " }",
        "--format",
        "f32",
        "--rate",
        str(CAPTURE_RATE),
        "--channels",
        str(CAPTURE_CHANNELS),
        "--latency",
        "50ms",
        "--raw",
        "-",
    ]


async def capture(
    target: CaptureTarget, feed: Callable[[float], None], playing: Callable[[], bool], command: str = PW_RECORD
) -> None:
    """
    Feeds the peaks of the target until the capture ends, or until it got no audio for STALL_TIMEOUT although
    `playing()` says the target plays: then it is not linked.
    """
    if shutil.which(command) is None:
        # stdbuf would start, and then fail to start it
        _LOGGER.error(f"Can't start {command} for the meters: not found")
        return
    argv = capture_command(target, command, STDBUF)
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
    except OSError as e:
        _LOGGER.error(f"Can't start {command} for the meters: {e}")
        return
    assert process.stdout is not None
    try:
        while True:
            try:
                data = await asyncio.wait_for(process.stdout.readexactly(CHUNK_BYTES), STALL_TIMEOUT)
            except TimeoutError:
                if playing():
                    _LOGGER.info(
                        f"The meter capture of {target.node or 'the default output'} gets no audio, restarting"
                    )
                    return
                continue
            except asyncio.IncompleteReadError:
                return
            feed(peak_of(data))
    finally:
        await _end(process)


async def _end(process: asyncio.subprocess.Process) -> None:
    """
    Kills the capture and waits for it, also when the task is cancelled again meanwhile (a reload cancels it, then the
    end of the event loop): otherwise the process is never waited for.
    """
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    cancelled = False
    while True:
        try:
            await process.wait()
        except asyncio.CancelledError:
            # killed, so the wait is short
            cancelled = True
        else:
            break
    if cancelled:
        raise asyncio.CancelledError


class Meter:
    """
    The level of one strip: the loudest peak of all of its targets (e.g. every stream of an application group) since
    it was taken last. `watch()` sets the targets, captures start and stop with them.
    """

    def __init__(
        self,
        playing: Callable[[CaptureTarget], bool],
        command: str = PW_RECORD,
        clock: Callable[[], float] = time.monotonic,
        gain: Callable[[CaptureTarget], float | None] = lambda target: None,
        point: MeterPoint = "pre_fader",
    ):
        """
        `gain` tells the volume of a target (with Mute, see `Device.gain`; None if unknown), `point` where the meter
        takes the level (see `scale_of()`).
        """
        self._playing = playing
        self._command = command
        self._clock = clock
        self._gain = gain
        self.point: MeterPoint = point
        self._gains: dict[CaptureTarget, tuple[float, list[tuple[float, float]]]] = {}
        """For each target: its gain, and the gains before it with when they stop counting (see GAIN_SETTLE)."""
        self._peak: float | None = None
        self._clipped: float | None = None
        """When the last peak at full scale came."""
        self._captures: dict[CaptureTarget, asyncio.Task[None]] = {}
        self._ending: set[asyncio.Task[None]] = set()
        """Captures that are cancelled and still end their process."""

    @property
    def targets(self) -> frozenset[CaptureTarget]:
        return frozenset(self._captures)

    def feed(self, peak: float) -> None:
        self._peak = peak if self._peak is None else max(self._peak, peak)
        if peak >= 1.0:
            self._clipped = self._clock()

    def feed_from(self, target: CaptureTarget, peak: float) -> None:
        """A peak captured from the target, as the level at the meter point."""
        scale = scale_of(target, self.point, (gain := self._gain(target)), self._settled(target, gain))
        if scale is not None:
            self.feed(peak * scale)

    def _settled(self, target: CaptureTarget, gain: float | None) -> float | None:
        """The loudest gain of the target in the last GAIN_SETTLE seconds before `gain`, None for none."""
        if gain is None:
            return None
        now = self._clock()
        last, before = self._gains.get(target, (gain, []))
        if gain != last:
            before.append((now + GAIN_SETTLE, last))
        before = [(until, value) for until, value in before if until > now]
        self._gains[target] = (gain, before)
        return max((value for _, value in before), default=None)

    def take_level(self) -> int | None:
        """
        The level since the last call, None without audio (then the device lets the meter fall by itself). For
        CLIP_HOLD after a clip it is METER_MAX.
        """
        if self._clipped is not None and self._clock() - self._clipped < CLIP_HOLD:
            self._peak = None
            return METER_MAX
        if self._peak is None:
            return None
        level = level_of(self._peak)
        self._peak = None
        return level

    def watch(self, targets: Iterable[CaptureTarget]) -> None:
        wanted = set(targets)
        self._gains = {target: gains for target, gains in self._gains.items() if target in wanted}
        for target in [target for target in self._captures if target not in wanted]:
            task = self._captures.pop(target)
            task.cancel()
            self._ending.add(task)
            task.add_done_callback(self._ending.discard)
        for target in wanted - self._captures.keys():
            self._captures[target] = asyncio.create_task(self._keep_capturing(target), name=f"meter {target.node}")

    async def _keep_capturing(self, target: CaptureTarget) -> None:
        while True:
            await capture(
                target, lambda peak: self.feed_from(target, peak), lambda: self._playing(target), self._command
            )
            await asyncio.sleep(RESTART_DELAY)

    def close(self) -> None:
        """Stops the captures; `wait_closed()` waits until their processes ended."""
        self.watch(())

    async def wait_closed(self) -> None:
        await asyncio.gather(*self._ending, return_exceptions=True)
