import array
import asyncio
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.support.processes import child_processes
from xtouch_daemon.audio import meter as meter_module
from xtouch_daemon.audio.meter import (
    CHUNK_BYTES,
    CLIP_HOLD,
    GAIN_SETTLE,
    CaptureTarget,
    Meter,
    capture,
    capture_command,
    level_of,
    peak_of,
    scale_of,
)
from xtouch_daemon.hardware.protocol import METER_MAX, METER_SIGNAL_MAX

OUTPUT = CaptureTarget(node=None, monitor=True)
STREAM = CaptureTarget(node="42", monitor=False)
INPUT = CaptureTarget(node="mic", monitor=False)

# real pw-record stand-ins: their output comes in real time
pytestmark = pytest.mark.looptime(False)


def samples(*values: float) -> bytes:
    return array.array("f", values).tobytes()


def test_the_peak_is_the_loudest_sample_either_way():
    assert peak_of(samples(0.1, -0.5, 0.25)) == pytest.approx(0.5)
    assert peak_of(samples(0.3, -0.1)) == pytest.approx(0.3)
    # an incomplete sample at the end is left out
    assert peak_of(samples(0.2) + b"\x00\x00") == pytest.approx(0.2)
    assert peak_of(b"") == 0.0
    assert peak_of(b"\x00") == 0.0


def test_the_level_spreads_the_decibels_over_the_leds():
    assert level_of(0.0) == 0
    assert level_of(-1.0) == 0
    # full scale and above clips: the red LED
    assert level_of(1.0) == METER_MAX
    assert level_of(2.0) == METER_MAX
    assert level_of(0.999) == METER_SIGNAL_MAX
    # -60 dB and below is the floor
    assert level_of(0.0001) == 0
    assert level_of(0.001) == 0
    # -6 dB is the 11th of 12 LEDs, -30 dB the 6th
    assert level_of(0.5) == 11
    assert level_of(10 ** (-30 / 20)) == 6


def test_the_capture_command_is_passive_and_raw():
    output = capture_command(OUTPUT, stdbuf=None)
    assert output[0] == "pw-record"
    assert "--target" not in output
    properties = output[output.index("-P") + 1]
    assert "node.passive = true" in properties
    assert "stream.capture.sink = true" in properties
    assert output[-2:] == ["--raw", "-"]

    # unbuffered: the audio comes every cycle of the graph, not in blocks of 64 ms
    stream = capture_command(STREAM, "/usr/bin/pw-record", "/usr/bin/stdbuf")
    assert stream[:5] == ["/usr/bin/stdbuf", "-o0", "/usr/bin/pw-record", "--target", "42"]
    assert "stream.capture.sink" not in stream[stream.index("-P") + 1]
    # a capture of a device or stream stays with it; the one of the default output follows the default
    assert "node.dont-reconnect = true" in stream[stream.index("-P") + 1]
    assert "node.dont-reconnect" not in properties


def executable(directory: Path, script: str) -> str:
    path = directory / "pw-record"
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def chunk_of(value: float) -> str:
    """A shell command that writes one chunk of samples of `value`."""
    data = samples(*[value] * (CHUNK_BYTES // 4))
    return "printf '" + "".join(f"\\{byte:03o}" for byte in data) + "'\n"


async def test_feeds_the_peaks_until_the_capture_ends(tmp_path: Path):
    command = executable(tmp_path, chunk_of(0.5) + chunk_of(0.25) + "printf 'x'\n")
    peaks: list[float] = []
    await asyncio.wait_for(capture(STREAM, peaks.append, lambda: True, command), 5)
    assert peaks == pytest.approx([0.5, 0.25])


async def test_a_capture_that_can_not_start_ends(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    peaks: list[float] = []
    await capture(STREAM, peaks.append, lambda: True, str(tmp_path / "missing"))
    assert peaks == []
    assert "Can't start" in caplog.text


async def test_a_capture_that_fails_to_run_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # without stdbuf the command itself runs, and fails: not a program
    monkeypatch.setattr(meter_module, "STDBUF", None)
    path = tmp_path / "pw-record"
    path.write_bytes(b"\x00\x01")
    path.chmod(0o755)
    await capture(STREAM, lambda peak: None, lambda: True, str(path))
    assert "Can't start" in caplog.text


async def test_a_silent_capture_is_restarted_only_while_its_target_plays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(meter_module, "STALL_TIMEOUT", 0.05)
    caplog.set_level("INFO")
    command = executable(tmp_path, "exec sleep 10\n")
    answers = iter([False, False, True])
    asked: list[bool] = []

    def playing() -> bool:
        asked.append(next(answers))
        return asked[-1]

    await asyncio.wait_for(capture(OUTPUT, lambda peak: None, playing, command), 5)
    assert asked == [False, False, True]
    assert "the default output gets no audio" in caplog.text


async def wait_for(condition: Callable[[], bool]) -> None:
    for _ in range(1000):
        if condition():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("the condition did not come true")


def test_the_level_is_the_loudest_peak_since_it_was_taken_last():
    meter = Meter(lambda target: False)
    assert meter.take_level() is None
    meter.feed(0.25)
    meter.feed(0.5)
    meter.feed(0.1)
    assert meter.take_level() == 11
    assert meter.take_level() is None


def test_a_clip_lights_the_red_led_for_a_while():
    now = 100.0
    meter = Meter(lambda target: False, clock=lambda: now)
    meter.feed(0.5)
    meter.feed(1.0)
    meter.feed(0.25)
    assert meter.take_level() == METER_MAX
    # also without audio, and with quieter audio
    now += CLIP_HOLD / 2
    assert meter.take_level() == METER_MAX
    meter.feed(0.5)
    assert meter.take_level() == METER_MAX
    now += CLIP_HOLD / 2
    meter.feed(0.5)
    assert meter.take_level() == 11
    assert meter.take_level() is None


def test_the_monitor_of_an_output_is_before_its_volume_the_audio_of_streams_and_inputs_after_it():
    # pre-fader: the monitor as it is, a stream or an input divided by its volume
    assert scale_of(OUTPUT, "pre_fader", 0.125) == 1.0
    assert scale_of(STREAM, "pre_fader", 0.125) == 8.0
    assert scale_of(INPUT, "pre_fader", 0.5) == 2.0
    # post-fader: the monitor times the volume, a stream or an input as it is
    assert scale_of(OUTPUT, "post_fader", 0.125) == 0.125
    assert scale_of(STREAM, "post_fader", 0.125) == 1.0
    assert scale_of(INPUT, "post_fader", 0.5) == 1.0


def test_muted_audio_tells_nothing_before_the_fader():
    # the stream mutes itself: its audio is gone before the capture
    assert scale_of(STREAM, "pre_fader", 0.0) is None
    assert scale_of(INPUT, "pre_fader", 0.0) is None
    # the monitor of a muted output still has it
    assert scale_of(OUTPUT, "pre_fader", 0.0) == 1.0
    # after the fader, a muted output is silent
    assert scale_of(OUTPUT, "post_fader", 0.0) == 0.0
    assert scale_of(STREAM, "post_fader", 0.0) == 1.0


def test_an_unknown_volume_leaves_the_audio_as_captured():
    for point in ("pre_fader", "post_fader"):
        assert scale_of(STREAM, point, None) == 1.0
        assert scale_of(OUTPUT, point, None) == 1.0


def test_a_volume_that_just_was_louder_divides_until_it_settled():
    assert scale_of(STREAM, "pre_fader", 0.125, settled=1.0) == 1.0
    # a quieter one before does not count: the louder one is the safe side
    assert scale_of(STREAM, "pre_fader", 0.5, settled=0.125) == 2.0


def test_a_meter_shows_the_level_at_its_point():
    gains = {STREAM: 0.125, OUTPUT: 0.5}
    pre = Meter(lambda target: False, gain=gains.get)
    post = Meter(lambda target: False, gain=gains.get, point="post_fader")

    for meter in (pre, post):
        # half the full scale after a volume of 50 % (0.125)
        meter.feed_from(STREAM, 0.0625)
    # before the fader it is the audio of the application: -6 dB
    assert pre.take_level() == 11
    # after it what plays: -24 dB
    assert post.take_level() == level_of(0.0625) == 8

    pre.feed_from(OUTPUT, 0.5)
    post.feed_from(OUTPUT, 0.5)
    assert pre.take_level() == 11
    assert post.take_level() == level_of(0.25)


def test_a_muted_stream_leaves_the_pre_fader_meter_dark():
    meter = Meter(lambda target: False, gain=lambda target: 0.0)
    meter.feed_from(STREAM, 0.0)
    # no level: the device lets the meter fall, as without audio
    assert meter.take_level() is None


def test_a_pre_fader_level_clips_like_any_other():
    meter = Meter(lambda target: False, gain=lambda target: 0.125)
    meter.feed_from(STREAM, 0.125)
    assert meter.take_level() == METER_MAX


def test_a_fader_pulled_down_does_not_clip_the_audio_that_was_still_on_its_way():
    now = 10.0
    gains = {STREAM: 1.0}
    meter = Meter(lambda target: False, clock=lambda: now, gain=gains.get)
    meter.feed_from(STREAM, 0.5)
    assert meter.take_level() == 11

    gains[STREAM] = 0.001
    # audio from before the change, at the old volume
    meter.feed_from(STREAM, 0.5)
    assert meter.take_level() == 11
    now += GAIN_SETTLE / 2
    meter.feed_from(STREAM, 0.0005)
    # too low for a moment, not clipped
    assert meter.take_level() == level_of(0.0005)
    now += GAIN_SETTLE / 2
    meter.feed_from(STREAM, 0.0005)
    assert meter.take_level() == 11


def test_a_target_that_is_no_longer_watched_forgets_its_volumes():
    now = 10.0
    gains = {STREAM: 1.0}
    meter = Meter(lambda target: False, clock=lambda: now, gain=gains.get)
    meter.feed_from(STREAM, 0.5)
    gains[STREAM] = 0.125
    meter.feed_from(STREAM, 0.5)
    assert meter._gains[STREAM] == (0.125, [(10.0 + GAIN_SETTLE, 1.0)])

    meter.watch([])
    assert meter._gains == {}


async def test_watches_its_targets_and_captures_again_after_a_capture_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(meter_module, "RESTART_DELAY", 0.01)
    starts = tmp_path / "starts"
    command = executable(tmp_path, f"echo started >> {starts}\n" + chunk_of(1.0))
    meter = Meter(lambda target: True, command)

    meter.watch([STREAM, OUTPUT])
    assert meter.targets == {STREAM, OUTPUT}
    # the capture ends after one chunk, and starts again
    await wait_for(lambda: starts.exists() and len(starts.read_text().splitlines()) >= 4)
    assert meter.take_level() == METER_MAX

    meter.watch([OUTPUT])
    assert meter.targets == {OUTPUT}
    meter.close()
    assert meter.targets == frozenset()
    await meter.wait_closed()
    assert child_processes() == set()


async def test_a_capture_that_is_cancelled_again_while_it_ends_still_waits_for_its_process(tmp_path: Path):
    started = tmp_path / "started"
    command = executable(tmp_path, f"touch {started}\nexec sleep 10\n")
    task = asyncio.create_task(capture(STREAM, lambda peak: None, lambda: False, command))
    await wait_for(started.exists)

    task.cancel()
    # in its end, waiting for the killed process
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child_processes() == set()
