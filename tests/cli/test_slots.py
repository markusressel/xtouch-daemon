"""
`simulate` and `observe`: the slots of a configuration in given states, the table of its outcomes, recording and
replaying observations.
"""

from pathlib import Path

import pytest

from tests.support.audio import stream
from tests.support.cli import invoke
from tests.support.slots import EXAMPLE
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.audio.pulse import SoundServerError
from xtouch_daemon.cli import slots as simulate_command
from xtouch_daemon.slots.inputs import Observation
from xtouch_daemon.slots.recording import read_log, to_line


def test_the_slots_and_why():
    result = invoke(
        "simulate", str(EXAMPLE), "--state", "call", "--playing", "mpv", "--playing", "spotify", "--absent", "mic"
    )
    assert result.exit_code == 0
    assert result.output.splitlines()[:6] == [
        "1  out",
        "     game if gaming: doesn't hold (gaming is off)",
        "2  browser",
        "     people if gaming and present: doesn't hold (gaming is off, present: no)",
        "3  auto:mpv",
        "4  auto:spotify",
    ]
    # an absent channel keeps its place
    assert "8  mic" in result.output


def test_who_waits():
    result = invoke("simulate", str(EXAMPLE), *(arg for app in "abcdefg" for arg in ("--playing", app)))
    assert result.output.splitlines()[-1] == "waiting for a slot of auto: g"
    result = invoke("simulate", str(EXAMPLE), "--mode", "gaming", "--person", "Bob", "--person", "Al")
    assert "2  people:Bob" in result.output
    assert result.output.splitlines()[-1] == "waiting for a slot of people: Al"


def test_the_table():
    result = invoke("simulate", str(EXAMPLE), "--table")
    assert result.output.splitlines()[0].split() == ["when", "1", "2", "3-6", "7", "8"]


def test_problems(tmp_path: Path):
    for options, message in [
        (("--state", "cal"), "--state cal: no state of"),
        (("--state", "gaming"), "--state gaming: no state of {}, a mode goes to --mode"),
        (("--mode", "call"), "--mode call: no mode of {} (default, gaming)"),
        (("--absent", "call"), "--absent call: no channel or pool of channels of"),
        (("--absent", "people"), "--absent people: no channel or pool of channels of {}, use --playing or --person"),
    ]:
        result = invoke("simulate", str(EXAMPLE), *options)
        assert result.exit_code == 1
        assert message.format(EXAMPLE) in result.output
    broken = tmp_path / "broken.toml"
    broken.write_text('[slots]\n1 = "nothing"\n')
    result = invoke("simulate", str(broken))
    assert result.exit_code == 1
    assert "slots.1[0]: nothing is no channel or pool" in result.output


def test_a_replay(tmp_path: Path):
    log = tmp_path / "log.jsonl"
    lines = [
        to_line(0, Observation()),
        to_line(10, Observation(processes=frozenset({"reaper"}))),
        to_line(12, Observation()),
        to_line(40, Observation()),
    ]
    log.write_text("\n".join(lines) + "\n")
    result = invoke("simulate", str(EXAMPLE), "--replay", str(log))
    assert result.exit_code == 0
    output = result.output.splitlines()
    assert output[0].endswith("  gaming on (reaper runs)")
    assert "0.0 h replayed, 4 slot changes, 2 flaps" in output
    assert "gaming on for 12 s" in output
    assert output[-1].endswith(": slot 7: voip and back to auto")


def test_observe_records_until_interrupted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(simulate_command, "read_state", lambda name: AudioState(streams=(stream(1, "mpv", "mpv"),)))
    monkeypatch.setattr(simulate_command, "running_processes", lambda: frozenset({"reaper", "bash"}))
    monkeypatch.setattr(simulate_command, "read_voip", lambda path: None)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(simulate_command.time, "sleep", sleep)
    log = tmp_path / "log.jsonl"
    result = invoke("observe", str(log), "--interval", "5")
    assert result.exit_code == 0
    ((_, observation),) = read_log(log)
    assert observation.playing == ("mpv",)
    assert observation.processes == {"reaper"}
    assert sleeps == [5, 5]


def test_observe_without_a_sound_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fail(name: str) -> AudioState:
        raise SoundServerError("no sound server")

    monkeypatch.setattr(simulate_command, "read_state", fail)
    monkeypatch.setattr(simulate_command, "running_processes", frozenset)
    monkeypatch.setattr(simulate_command, "read_voip", lambda path: None)
    result = invoke("observe", str(tmp_path / "log.jsonl"))
    assert result.exit_code == 1
    assert "no sound server" in result.output


def test_an_absent_pool_of_channels(tmp_path: Path):
    config = tmp_path / "pool.toml"
    config.write_text(
        '[channel.a]\ntype = "output"\ntags = ["x"]\n[pool.both]\nchannels = ["#x"]\n'
        '[slots]\n1 = ["a if present", "-"]\n'
    )
    assert invoke("simulate", str(config)).output.startswith("1  a\n")
    assert invoke("simulate", str(config), "--absent", "both").output.startswith("1  -\n")
