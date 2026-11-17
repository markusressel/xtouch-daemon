"""
Channels, states and slots in the daemon (the prototype): the strips follow the resolver, the auto strips keep their
applications across a new mixer, modes by hand and by the chord, held strips, reloads.
"""

import asyncio
import json
import logging
from pathlib import Path

import pytest

from tests.support.audio import FakeBackend, output, source, stream
from tests.support.daemon import Notifications, quiet_mixer, until
from tests.support.hardware import RecordingSurface
from tests.support.tasks import settle
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.live.messages import Reply, VoipState, fingerprint
from xtouch_daemon.runtime import daemon as daemon_module
from xtouch_daemon.runtime.daemon import Daemon
from xtouch_daemon.runtime.slots import SlotRunner

SLOTS = """
[switching]
banner = 0

[channel.out]
type = "output"
device = "speaker"
label = "Speaker"
color = "cyan"

[channel.game]
type = "apps"
match = ["mygame"]
label = "Game"

[channel.mic]
type = "input"
device = "mic"
label = "Mic"

[pool.auto]
hold = 0

[state.gaming]
mode = true
label = "Gaming"
processes = ["mygame"]
delay_off = 0

[state.call]
processes = ["mumble"]
delay_off = 0

[slots]
1 = ["game if gaming", "out"]
2 = [{ show = "auto", color = "blue" }]
3 = ["mic if call", "auto"]
"""

STATE = AudioState(
    outputs=(output("speaker", 50),),
    inputs=(source("mic"),),
    streams=(stream(1, "Spotify", "spotify"),),
    default_output="speaker",
)


class Processes:
    def __init__(self) -> None:
        self.running: set[str] = set()

    def __call__(self) -> frozenset[str]:
        return frozenset(self.running)


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_module, "SLOTS_INTERVAL", 0.002)
    monkeypatch.setattr(daemon_module, "PROCESS_INTERVAL", 0.0)


def make(path: Path, surface: RecordingSurface, processes: Processes, states: tuple[AudioState, ...] = (STATE,)):
    return Daemon(
        parse_config(path.read_text()),
        FakeBackend(states),
        surface,
        path,
        mixer_factory=quiet_mixer,
        processes=processes,
    )


def labels(surface: RecordingSurface, count: int = 3) -> list[str]:
    return [strip.text[0] for strip in surface.strips[:count]]


async def test_the_strips_follow_the_states_and_auto_keeps_its_application(
    tmp_path: Path, surface: RecordingSurface, notifications: Notifications, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS)
    processes = Processes()
    daemon = make(path, surface, processes)
    task = asyncio.create_task(daemon.run())
    await until(lambda: labels(surface) == ["Speaker", "Spotify", ""])
    first = daemon.mixer
    first.assigner.toggle_pin(0)

    processes.running.add("mumble")
    await until(lambda: labels(surface) == ["Speaker", "Spotify", "Mic"])
    assert daemon.mixer is not first
    # the auto strip of slot 2 keeps its application, and its pin
    assert daemon.mixer.assigner.pinned == {0}
    processes.running.add("mygame")
    await until(lambda: labels(surface) == ["Game", "Spotify", "Mic"])
    assert daemon.slots is not None
    assert daemon.slots.mode == "gaming"
    assert daemon.snapshot().layout == "gaming"
    assert daemon.snapshot().layouts == ("default", "gaming", "auto")
    assert "State gaming on (mygame runs)" in caplog.text
    assert "Slots: 1 game" in caplog.text

    daemon.stop()
    await task


async def test_modes_by_hand_and_by_the_chord(
    tmp_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS.replace("banner = 0", "banner = 0.05"))
    daemon = make(path, surface, Processes())
    task = asyncio.create_task(daemon.run())
    await until(lambda: labels(surface, 1) == ["Speaker"])

    assert daemon.request_layout("gaming") == Reply("layout", True, "gaming")
    assert labels(surface, 1) == ["Game"]
    assert "Gaming" in "".join(strip.shown_text[0] for strip in surface.strips)
    assert daemon.request_layout("+1") == Reply("layout", True, "default")
    assert daemon.request_layout("nope") == Reply("layout", False, "There is no mode nope (auto, default, gaming)")
    assert daemon.request_layout("auto") == Reply("layout", True, "default")

    def press(strip: int, pressed: bool = True) -> None:
        surface.on_event(protocol.ButtonPressed(strip, Button.SOLO, pressed))

    press(0)
    press(3)
    press(7)
    assert daemon.slots is not None
    assert daemon.slots.mode == "gaming"

    daemon.stop()
    await task


async def test_nothing_changes_under_a_finger(
    tmp_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS)
    processes = Processes()
    daemon = make(path, surface, processes)
    task = asyncio.create_task(daemon.run())
    await until(lambda: labels(surface, 1) == ["Speaker"])

    surface.on_event(protocol.FaderTouched(0, True))
    processes.running.add("mygame")
    await until(lambda: daemon.slots is not None and daemon.slots.mode == "gaming")
    await asyncio.sleep(0.02)
    assert labels(surface, 1) == ["Speaker"]
    surface.on_event(protocol.FaderTouched(0, False))
    await until(lambda: labels(surface, 1) == ["Game"])

    daemon.stop()
    await task


async def test_a_reload_shows_the_slots_of_the_new_file_at_once(
    tmp_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS)
    daemon = make(path, surface, Processes())
    daemon.mixer.on_state(STATE)

    path.write_text(SLOTS.replace('"Speaker"', '"Boxes"'))
    assert daemon.reload()
    assert labels(surface, 1) == ["Boxes"]
    # back to strips and layouts
    path.write_text('[[strip]]\ntype = "output"\ndevice = "speaker"\nlabel = "Plain"\n')
    assert daemon.reload()
    assert daemon.slots is None
    assert labels(surface, 1) == ["Plain"]
    daemon.mixer.close()
    await settle()


def test_the_fingerprint_tells_configurations_of_slots_apart() -> None:
    assert fingerprint(parse_config(SLOTS)) != fingerprint(parse_config(SLOTS.replace("mygame", "othergame")))


async def test_the_processes_are_scanned_every_few_seconds(
    tmp_path: Path, surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_module, "PROCESS_INTERVAL", 60.0)
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS)
    scans: list[int] = []
    daemon = Daemon(
        parse_config(SLOTS),
        FakeBackend(),
        surface,
        path,
        mixer_factory=quiet_mixer,
        processes=lambda: scans.append(1) or frozenset(),
    )
    daemon.mixer.on_state(STATE)
    daemon.request_layout("gaming")
    daemon.request_layout("default")
    assert len(scans) == 1
    daemon.mixer.close()
    await settle()


SHARED = SLOTS.replace("[pool.auto]\nhold = 0\n", '[pool.auto]\nhold = 0\n\n[pool.people]\nshare = "auto"\n')
VOICE = VoipState("bridge", True, "mumble", "Lobby", 1, ("Bob",))


def test_the_homes_of_people_last_across_a_restart(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    homes = tmp_path / "state" / "people-slots.json"
    config = parse_config(SHARED)
    now = [100.0]
    runner = SlotRunner(config, homes, clock=lambda: now[0], wall_clock=lambda: now[0] + 1000)
    runner.step(STATE, frozenset(), VOICE, frozenset(), 100)
    assert json.loads(homes.read_text()) == {"Bob": [8, 1100.0]}
    written = homes.stat().st_mtime_ns
    runner.step(STATE, frozenset(), VOICE, frozenset(), 100.2)
    assert homes.stat().st_mtime_ns == written  # nothing changed
    # a restart: the clock of the steps starts anew, the home is as old as it was
    again = SlotRunner(config, homes, clock=lambda: 5.0, wall_clock=lambda: 1200.0)
    assert again.simulation.homes == {"Bob": (8, 5.0 - 100)}
    # files that can't be read or written
    homes.write_text("{")
    assert SlotRunner(config, homes).simulation.homes == {}
    blocked = tmp_path / "file"
    blocked.write_text("")
    SlotRunner(config, blocked / "people-slots.json").step(STATE, frozenset(), VOICE, frozenset(), 1)
    assert "Can't read the slots of the people" in caplog.text
    assert "Can't keep the slots of the people" in caplog.text
