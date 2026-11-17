"""
Recording observations of the real system, and reading them back.
"""

import socket
import tempfile
import threading
from pathlib import Path

import pytest

from tests.support.audio import output, stream
from tests.support.slots import example
from xtouch_daemon.audio.model import AudioState, Capture
from xtouch_daemon.live.codec import encode, encode_reply
from xtouch_daemon.live.messages import Reply, Snapshot, VoipState
from xtouch_daemon.slots import replay as replay_module
from xtouch_daemon.slots.inputs import Observation
from xtouch_daemon.slots.recording import (
    Observer,
    from_line,
    only_watched,
    read_log,
    read_voip,
    record,
    stream_name,
    to_line,
    watched_processes,
)
from xtouch_daemon.slots.replay import replay

VOIP = VoipState("bridge", True, "mumble", "Lobby", 1, ("Bob",))


def audio(*apps: str) -> AudioState:
    return AudioState(
        outputs=(output("speaker"),),
        streams=tuple(stream(index, app, app) for index, app in enumerate(apps)),
        captures=(
            Capture(1, "Discord", "discord", "mic", None, corked=False),
            Capture(2, "OBS", "obs", "mic", None, corked=True),
        ),
    )


def test_an_observation_of_the_readings_keeps_the_order_applications_started_in():
    observer = Observer()
    first = observer.observe(audio("spotify"), frozenset({"reaper"}), VOIP, 0)
    assert first == Observation(
        playing=("spotify",),
        recording=("Discord",),
        voice_chat=True,
        people=("Bob",),
        processes=frozenset({"reaper"}),
        devices=frozenset({"speaker", "speaker description"}),
    )
    assert observer.observe(audio("mpv", "spotify"), frozenset(), None, 1).playing == ("spotify", "mpv")
    # one that stopped and starts again is new
    assert observer.observe(audio("mpv"), frozenset(), None, 2).playing == ("mpv",)
    assert observer.observe(audio("spotify", "mpv"), frozenset(), None, 3).playing == ("mpv", "spotify")
    alone = VoipState("bridge", True, "mumble", "Lobby", 0)
    assert not observer.observe(audio(), frozenset(), alone, 4).voice_chat


def test_names_of_streams_and_processes():
    assert stream_name("Firefox", "firefox") == "Firefox"
    assert stream_name("WEBRTC VoiceEngine", "discord") == "WEBRTC VoiceEngine (discord)"
    assert stream_name("mpv", "") == "mpv"
    watched = watched_processes(("mygame",))
    assert "reaper" in watched
    assert watched[-1] == "mygame"
    processes = frozenset({"reaper", "bash", "", "/opt/brave/brave --type=gpu --crash-id=42", "mygame.exe"})
    assert only_watched(processes, watched) == {"reaper", "brave", "mygame.exe"}


def test_lines_and_logs(tmp_path: Path):
    observation = Observation(playing=("a",), processes=frozenset({"x"}), homeassistant=frozenset({"night"}))
    assert from_line(to_line(1.5, observation)) == (1.5, observation)
    log = tmp_path / "log.jsonl"
    log.write_text(to_line(1, observation) + "\n\n" + to_line(2, Observation()) + "\n")
    assert read_log(log) == [(1.0, observation), (2.0, Observation())]


def test_a_line_only_when_something_changed(tmp_path: Path):
    readings = iter([audio("a"), audio("a"), audio("a", "b")])
    times = iter([10.0, 12.0, 14.0])
    waits: list[float] = []
    log = tmp_path / "log.jsonl"
    record(
        log,
        read_audio=lambda: next(readings),
        read_processes=frozenset,
        read_voice=lambda: None,
        clock=lambda: next(times),
        wait=waits.append,
        interval=2,
        samples=3,
    )
    assert [at for at, _ in read_log(log)] == [10.0, 14.0]
    assert waits == [2, 2, 2]


def test_the_voice_chat_of_the_running_daemon():
    with tempfile.TemporaryDirectory(prefix="xto-") as directory:
        path = Path(directory) / "live.sock"
        assert read_voip(path) is None
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            server.listen()
            snapshot = Snapshot("config.toml", True, True, None, (), voip=VOIP)

            def serve(lines: list[bytes]) -> None:
                connection, _ = server.accept()
                with connection:
                    connection.sendall(b"".join(lines))

            for lines, expected in [
                ([encode_reply(Reply("layout", True)), encode(snapshot)], VOIP),
                ([encode_reply(Reply("layout", True))], None),
            ]:
                thread = threading.Thread(target=serve, args=(lines,))
                thread.start()
                assert read_voip(path) == expected
                thread.join()


def test_a_replay_tells_changes_flaps_and_time_on():
    log = [
        (0.0, Observation()),
        (10.0, Observation(processes=frozenset({"reaper"}))),
        (12.0, Observation()),
        (40.0, Observation(processes=frozenset({"reaper"}))),
        (100.0, Observation()),
        (200.0, Observation()),
    ]
    report = replay(example(), log)
    texts = [event.text for event in report.events]
    assert texts[:4] == ["gaming on (reaper runs)", "default off", "slot 1: out -> game", "slot 7: auto -> voip"]
    # gaming ends 10 s after reaper (its delay_off), at 22 s: slot 1 goes back within a minute
    assert "slot 1: game -> out" in texts
    assert [flap.text for flap in report.flaps][:1] == ["slot 1: game and back to out"]
    assert report.changes[1] == 4
    assert report.on_time["gaming"] == 12 + 70
    assert report.summary()[0] == f"0.1 h replayed, {sum(report.changes.values())} slot changes, 4 flaps"
    assert "gaming on for 82 s" in report.summary()
    assert replay(example(), [(0.0, Observation(processes=frozenset({"reaper"}))), (600.0, Observation())]).summary()[
        2:
    ] == ["gaming on for 10 min"]


def test_a_replay_steps_at_deadlines_between_observations():
    report = replay(example(), [(0.0, Observation(voice_chat=True)), (0.5, Observation()), (100.0, Observation())])
    # call (the baseline) stays 30 s after the voice chat ended: off at 30.5, between the observations
    assert [event.at for event in report.events if event.text == "call off"] == [30.5]


def test_a_replay_steps_at_most_so_often_between_observations(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(replay_module, "MAX_STEPS_BETWEEN", 0)
    report = replay(example(), [(0.0, Observation(voice_chat=True)), (0.5, Observation()), (100.0, Observation())])
    assert [event.at for event in report.events if event.text == "call off"] == [100.0]


def test_a_replay_of_nothing():
    assert replay(example(), []).summary()[0] == "0.0 h replayed, 0 slot changes, 0 flaps"
