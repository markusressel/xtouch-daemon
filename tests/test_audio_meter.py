import array
import asyncio
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from xtouch_daemon.audio import meter as meter_module
from xtouch_daemon.audio.meter import CHUNK_BYTES, CaptureTarget, Meter, capture, capture_command, level_of, peak_of
from xtouch_daemon.protocol import METER_MAX

OUTPUT = CaptureTarget(node=None, monitor=True)
STREAM = CaptureTarget(node="42", monitor=False)


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
    assert level_of(1.0) == METER_MAX
    assert level_of(2.0) == METER_MAX
    # -60 dB and below is the floor
    assert level_of(0.0001) == 0
    assert level_of(0.001) == 0
    # -6 dB is the 11th of 12 LEDs, -30 dB the 6th
    assert level_of(0.5) == 11
    assert level_of(10 ** (-30 / 20)) == 6


def test_the_capture_command_is_passive_and_raw():
    output = capture_command(OUTPUT)
    assert output[0] == "pw-record"
    assert "--target" not in output
    properties = output[output.index("-P") + 1]
    assert "node.passive = true" in properties
    assert "stream.capture.sink = true" in properties
    assert output[-2:] == ["--raw", "-"]

    stream = capture_command(STREAM, "/usr/bin/pw-record")
    assert stream[:3] == ["/usr/bin/pw-record", "--target", "42"]
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
    meter.feed(1.0)
    meter.feed(0.5)
    assert meter.take_level() == METER_MAX
    assert meter.take_level() is None


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
    await asyncio.sleep(0)
