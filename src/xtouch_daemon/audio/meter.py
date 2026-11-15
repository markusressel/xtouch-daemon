"""
Audio levels for the LED meters: the peaks of audio captured with `pw-record`.

The captures are passive (`node.passive`): they never wake a device. A meter shows a level only while something else
plays to the output or records from the input, so it does not keep an output from suspending, light the microphone
indicator of the desktop, or switch Bluetooth headphones into their headset mode.

They are native PipeWire streams on purpose: WirePlumber 0.5.18 (PipeWire 1.6.10) restores captures of PulseAudio
clients (`parec`, peak detection streams) at 0 % volume, so they would only get silence.
"""

import array
import asyncio
import contextlib
import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from xtouch_daemon.protocol import METER_MAX

_LOGGER = logging.getLogger(__name__)

FLOOR_DB = -60.0
"""The level of the lowest LED: the LEDs split FLOOR_DB..0 dB evenly (5 dB each)."""
CAPTURE_RATE = 8000
"""The audio is only looked at for its peaks, a low rate costs next to nothing."""
CAPTURE_CHANNELS = 2
CHUNK_BYTES = CAPTURE_RATE * CAPTURE_CHANNELS * 4 // 20
"""Read at once: 50 ms of float32 samples."""
STALL_TIMEOUT = 3.0
"""
A capture that gets no audio for this long although what it captures plays is started again: WirePlumber links a
passive capture only once and gives up when that fails (e.g. "item deactivated before format was set" while Bluetooth
headphones go away and the streams move).
"""
RESTART_DELAY = 1.0
PW_RECORD = "pw-record"


def peak_of(data: bytes) -> float:
    """The peak of float32 samples (1.0 is full scale)."""
    samples = array.array("f")
    samples.frombytes(data[: len(data) - len(data) % 4])
    if not samples:
        return 0.0
    return max(max(samples), -min(samples))


def level_of(peak: float) -> int:
    """The meter level 0..METER_MAX of a peak: 0 below FLOOR_DB, METER_MAX at full scale."""
    if peak <= 0.0:
        return 0
    db = 20 * math.log10(peak)
    return max(0, min(METER_MAX, math.ceil((db - FLOOR_DB) / -FLOOR_DB * METER_MAX)))


@dataclass(frozen=True)
class CaptureTarget:
    node: str | None
    """A node name, or the serial of a stream (the index PulseAudio tools show); None for the default output."""
    monitor: bool
    """The node is an output: its monitor is captured."""


def capture_command(target: CaptureTarget, command: str = PW_RECORD) -> list[str]:
    properties = [
        "node.passive = true",
        'application.name = "xtouch-daemon"',
        'media.name = "X-Touch meter"',
        # not saved by WirePlumber (it would restore the volume of a capture it has not seen before as 0 %)
        "state.restore-props = false",
        *(["stream.capture.sink = true"] if target.monitor else []),
    ]
    return [
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
    argv = capture_command(target, command)
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
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        await process.wait()


class Meter:
    """
    The level of one strip: the loudest peak of all of its targets (e.g. every stream of an application group) since
    it was taken last. `watch()` sets the targets, captures start and stop with them.
    """

    def __init__(self, playing: Callable[[CaptureTarget], bool], command: str = PW_RECORD):
        self._playing = playing
        self._command = command
        self._peak: float | None = None
        self._captures: dict[CaptureTarget, asyncio.Task[None]] = {}

    @property
    def targets(self) -> frozenset[CaptureTarget]:
        return frozenset(self._captures)

    def feed(self, peak: float) -> None:
        self._peak = peak if self._peak is None else max(self._peak, peak)

    def take_level(self) -> int | None:
        """The level since the last call, None without audio (then the device lets the meter fall by itself)."""
        if self._peak is None:
            return None
        level = level_of(self._peak)
        self._peak = None
        return level

    def watch(self, targets: Iterable[CaptureTarget]) -> None:
        wanted = set(targets)
        for target in [target for target in self._captures if target not in wanted]:
            self._captures.pop(target).cancel()
        for target in wanted - self._captures.keys():
            self._captures[target] = asyncio.create_task(self._keep_capturing(target), name=f"meter {target.node}")

    async def _keep_capturing(self, target: CaptureTarget) -> None:
        while True:
            await capture(target, self.feed, lambda: self._playing(target), self._command)
            await asyncio.sleep(RESTART_DELAY)

    def close(self) -> None:
        self.watch(())
