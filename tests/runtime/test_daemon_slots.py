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
from tests.support.daemon import QUIET, Notifications, until
from tests.support.hardware import RecordingSurface
from tests.support.tasks import settle
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.live.messages import Reply, VoipState, fingerprint
from xtouch_daemon.runtime import daemon as daemon_module
from xtouch_daemon.runtime.binder import SlotMixer
from xtouch_daemon.runtime.daemon import Daemon
from xtouch_daemon.runtime.slots import SlotEngine
from xtouch_daemon.slots.inputs import App
from xtouch_daemon.slots.states import Override
from xtouch_daemon.strips.apps import AutoStrip

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
    monkeypatch.setattr(daemon_module, "SLOTS_BATCH", 0.002)
    monkeypatch.setattr(daemon_module, "PROCESS_INTERVAL", 0.002)


def make(path: Path, surface: RecordingSurface, processes: Processes, states: tuple[AudioState, ...] = (STATE,)):
    return Daemon(
        parse_config(path.read_text()),
        FakeBackend(states),
        surface,
        path,
        capture_command=QUIET,
        processes=processes,
    )


def app_of(engine: SlotEngine, index: int) -> str | None:
    """The application on a slot (from 0), as the sound server names it."""
    member = engine.member(index + 1)
    return engine.observer.apps.get(member.name) if isinstance(member, App) else None


def labels(surface: RecordingSurface, count: int = 3) -> list[str]:
    return [strip.text[0] for strip in surface.strips[:count]]


async def test_the_strips_follow_the_states_and_auto_keeps_its_application(
    tmp_path: Path,
    surface: RecordingSurface,
    notifications: Notifications,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO)
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS)
    processes = Processes()
    daemon = make(path, surface, processes)
    task = asyncio.create_task(daemon.run())
    await until(lambda: labels(surface) == ["Speaker", "Spotify", ""])
    first = daemon.mixer
    assert isinstance(first, SlotMixer)
    kept = first.controllers[:2]
    # the encoder of slot 2 pins its application: a request to the slots
    spotify = kept[1]
    assert isinstance(spotify, AutoStrip)
    slot = spotify.slot
    assert slot is not None
    slot.toggle_pin()
    assert daemon.slots is not None
    assert daemon.slots.pins == {2: App("Spotify")}
    assert slot.pinned

    redrawn: list[int] = []
    for index in (0, 1):
        monkeypatch.setattr(surface.strips[index], "show_from", lambda view, index=index: redrawn.append(index))
    processes.running.add("mumble")
    await until(lambda: labels(surface) == ["Speaker", "Spotify", "Mic"])
    # only slot 3 changed: slots 1 and 2 keep their controllers and are not drawn again (no blank texts)
    assert daemon.mixer is first
    assert first.controllers[:2] == kept
    assert redrawn == []
    # the auto strip of slot 2 keeps its application, and its pin
    assert daemon.slots.pins == {2: App("Spotify")}
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
    # and back to slots
    path.write_text(SLOTS)
    assert daemon.reload()
    assert labels(surface, 1) == ["Speaker"]
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
        capture_command=QUIET,
        processes=lambda: scans.append(1) or frozenset(),
    )
    daemon.mixer.on_state(STATE)
    daemon.request_layout("gaming")
    daemon.request_layout("default")
    assert len(scans) == 1
    daemon.mixer.close()
    await settle()


VOICE = VoipState("bridge", True, "mumble", "Lobby", 1, ("Bob",))


def test_the_order_of_people_lasts_across_a_restart(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    state = tmp_path / "state"
    people = state / "people.json"
    config = parse_config(SLOTS)
    runner = SlotEngine(config, state, clock=lambda: 100.0, wall_clock=lambda: 1100.0)
    runner.step(STATE, frozenset(), VOICE, frozenset(), 100)
    assert json.loads(people.read_text()) == [["Bob", 1100.0]]
    written = people.stat().st_mtime_ns
    runner.step(STATE, frozenset(), VOICE, frozenset(), 100.2)
    assert people.stat().st_mtime_ns == written  # nothing changed
    # a restart: the clock of the steps starts anew, Bob was seen as long ago as he was
    again = SlotEngine(config, state, clock=lambda: 5.0, wall_clock=lambda: 1200.0)
    assert again.simulation.known == {"Bob": 5.0 - 100}
    # files that can't be read or written
    people.write_text("{")
    assert SlotEngine(config, state).simulation.known == {}
    blocked = tmp_path / "file"
    blocked.write_text("")
    SlotEngine(config, blocked).step(STATE, frozenset(), VOICE, frozenset(), 1)
    assert "Can't read the order of the people" in caplog.text
    assert "Can't keep the order of the people" in caplog.text


def test_the_choices_last_across_a_restart(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    config = parse_config(SLOTS)
    engine = SlotEngine(config, tmp_path)
    engine.pick_mode("gaming")
    engine.set_override("call", Override.ON)
    assert json.loads((tmp_path / "slots.json").read_text()) == {"overrides": {"call": "on"}, "mode": "gaming"}
    again = SlotEngine(config, tmp_path)
    assert again.choices == ({"call": Override.ON}, "gaming")
    # the first step is the baseline: the kept choices survive it
    again.step(STATE, frozenset(), None, frozenset(), 0)
    assert again.mode == "gaming"
    assert again.simulation.states is not None
    assert again.simulation.states.values["call"]
    # back to auto: written as such
    again.pick_mode(None)
    again.set_override("call", Override.AUTO)
    assert json.loads((tmp_path / "slots.json").read_text()) == {"overrides": {}, "mode": None}
    # choices of states and modes the file no longer has are dropped
    (tmp_path / "slots.json").write_text('{"overrides": {"gone": "on", "gaming": "on"}, "mode": "gone"}')
    assert SlotEngine(config, tmp_path).choices == ({}, None)
    (tmp_path / "slots.json").write_text("{")
    assert SlotEngine(config, tmp_path).choices == ({}, None)
    assert "Can't read the overrides and the mode" in caplog.text
    blocked = tmp_path / "file"
    blocked.write_text("")
    SlotEngine(config, blocked).pick_mode("gaming")
    assert "Can't keep the overrides and the mode" in caplog.text
    # nowhere to keep them
    SlotEngine(config).pick_mode("gaming")


def test_a_reload_carries_the_states_the_members_and_the_choices_over() -> None:
    engine = SlotEngine(parse_config(SLOTS))
    spotify = AudioState(streams=(stream(1, "Spotify", "spotify"),))
    engine.step(spotify, frozenset({"mumble"}), None, frozenset(), 0)
    engine.pin(3, App("mpv"))
    engine.pin(2, App("spotify"))
    engine.pin(2, None)
    engine.set_override("call", Override.OFF)
    assert engine.pins == {3: App("mpv")}
    # the label of the output changes, a slot goes: call stays (off, overridden), Spotify keeps slot 2
    engine.reconfigure(parse_config(SLOTS.replace('"Speaker"', '"Boxes"').replace('3 = ["mic if call", "auto"]\n', "")))
    assert engine.choices == ({"call": Override.OFF}, None)
    assert engine.simulation.result is not None
    assert str(engine.simulation.result.slots[2]) == "auto:Spotify"
    engine.step(spotify, frozenset({"mumble"}), None, frozenset(), 0.1)
    assert str(engine.simulation.result.slots[2]) == "auto:Spotify"
    # a slot whose new stack lacks what it showed shows nothing until the next step; new states and channels
    engine.pick_mode("gaming")
    more = '[channel.extra]\ntype = "input"\n[state.other]\nprocesses = ["x"]\n'
    engine.reconfigure(parse_config(more + SLOTS.replace('1 = ["game if gaming", "out"]', '1 = "mic"')))
    assert engine.simulation.result is not None
    assert engine.simulation.result.slots[1].candidate is None
    assert engine.choices == ({"call": Override.OFF}, "gaming")
    engine.reconfigure(parse_config(SLOTS))
    assert engine.simulation.result.slots[1].candidate is None
    assert (deadline := engine.deadline()) is None or deadline >= 0


def test_the_encoder_of_an_auto_slot_picks_and_pins_through_the_engine() -> None:
    engine = SlotEngine(parse_config(SLOTS))
    requests: list[int] = []
    engine.on_request = lambda: requests.append(1)
    two = AudioState(streams=(stream(1, "Spotify", "spotify"), stream(2, "mpv", "mpv-bin")))
    slot = engine.slot(1)
    # nothing to pick before the first step
    slot.pick(1)
    assert slot.position() is None
    assert requests == []
    engine.step(two, frozenset(), None, frozenset(), 0)
    assert [app_of(engine, index) for index in (1, 2)] == ["Spotify", "mpv"]
    assert engine.candidates() == [App("Spotify"), App("mpv (mpv-bin)")]
    assert slot.position() == (0, 2)
    # the next one: slot 2 gets mpv once, slot 3 the other application
    slot.pick(1)
    assert engine.picks == {2: App("mpv (mpv-bin)")}
    engine.step(two, frozenset(), None, frozenset(), 0.1)
    assert engine.picks == {}
    assert [app_of(engine, index) for index in (1, 2)] == ["mpv", "Spotify"]
    # pinned, a pick keeps the pin on the new application; a push again unpins
    slot.toggle_pin()
    slot.pick(-1)
    assert engine.pins == {2: App("Spotify")}
    slot.toggle_pin()
    assert engine.pins == {}
    assert len(requests) == 4
    # a slot that shows no application: nothing to pin, and no position
    dark = engine.slot(0)
    dark.toggle_pin()
    assert not dark.pinned
    assert dark.position() is None
    assert app_of(engine, 0) is None
    # an empty slot of auto picks from the end backwards
    engine.slot(3).pick(-1)
    assert engine.picks[4] == App("mpv (mpv-bin)")


@pytest.mark.parametrize(
    ("action", "expected"),
    [("mode:gaming", ("gaming", ({}, "gaming"))), ("toggle:call", ("default", ({"call": Override.ON}, None)))],
)
async def test_the_chord_does_its_action(
    tmp_path: Path, surface: RecordingSurface, notifications: Notifications, action: str, expected: tuple
) -> None:
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS.replace("banner = 0", f'banner = 0\nchord = {{ strips = [1, 8], action = "{action}" }}'))
    daemon = make(path, surface, Processes())
    task = asyncio.create_task(daemon.run())
    await until(lambda: labels(surface, 1) == ["Speaker"])
    for pressed in (True, False):
        for strip in (0, 7):
            surface.on_event(protocol.ButtonPressed(strip, Button.SOLO, pressed))
    await until(lambda: daemon.slots is not None and daemon.slots.choices == expected[1])
    assert daemon.slots is not None
    assert daemon.slots.mode == expected[0] or action.startswith("toggle")
    daemon.stop()
    await task
