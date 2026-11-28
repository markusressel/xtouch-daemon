"""
Channels, states and slots in the daemon (the prototype): the strips follow the resolver, the auto strips keep their
applications across a new mixer, modes by hand and by the chord, held strips, reloads.
"""

import asyncio
import dataclasses
import json
import logging
from datetime import datetime
from pathlib import Path

import pytest

from tests.support.audio import FakeBackend, output, source, stream
from tests.support.daemon import QUIET, Notifications
from tests.support.hardware import RecordingSurface
from tests.support.media import FakePlayers
from tests.support.tasks import settle
from tests.support.waiting import until
from tests.support.watches import ProgramCommands
from xtouch_daemon.audio.media import Player
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.daemon import lifecycle as daemon_module
from xtouch_daemon.daemon import rig as rig_module
from xtouch_daemon.daemon.binder import SlotMixer
from xtouch_daemon.daemon.lifecycle import Daemon
from xtouch_daemon.daemon.slots import SlotEngine
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.live.messages import (
    Reply,
    SetMode,
    SetOverride,
    SlotView,
    StateView,
    VoipState,
)
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

[pool.apps]
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
    monkeypatch.setattr(rig_module, "BATCH", 0.002)
    monkeypatch.setattr(rig_module, "PROCESS_INTERVAL", 0.002)
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
    view = daemon.snapshot().slots
    assert view is not None
    assert view.mode == "gaming"
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

    assert daemon.on_request(None, SetMode("gaming")) == Reply("mode", True, "gaming")
    assert labels(surface, 1) == ["Game"]
    assert "Gaming" in "".join(strip.shown_text[0] for strip in surface.strips)
    assert daemon.request_mode("+1") == Reply("mode", True, "default")
    assert daemon.request_mode("nope") == Reply("mode", False, "There is no mode nope (auto, default, gaming)")
    assert daemon.request_mode("auto") == Reply("mode", True, "default")

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
    # another VoIP provider, before the daemon runs: it starts with the daemon
    path.write_text(SLOTS + '\n[voip]\nprovider = "demo"\n')
    assert daemon.reload()
    assert labels(surface, 1) == ["Speaker"]
    assert daemon.voip.name == "demo"
    assert daemon._voip_task is None
    daemon.mixer.close()
    await settle()


SCREEN = """
[channel.screen]
type = "custom"
label = "Screen"
absent_after = 0
present = { watch = "screen --watch" }
"""


async def test_a_custom_channel_comes_and_goes_as_its_present_says(
    tmp_path: Path, surface: RecordingSurface, notifications: Notifications, monkeypatch: pytest.MonkeyPatch
) -> None:
    # without a step every few seconds: the slots look again because the channel went
    monkeypatch.setattr(rig_module, "PROCESS_INTERVAL", 3600)
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS.replace('1 = ["game if gaming", "out"]', '1 = ["screen if present", "out"]') + SCREEN)
    commands = ProgramCommands()
    daemon = Daemon(
        parse_config(path.read_text()),
        FakeBackend((STATE,)),
        surface,
        path,
        capture_command=QUIET,
        processes=Processes(),
        commands=commands,
    )
    task = asyncio.create_task(daemon.run())
    await until(lambda: labels(surface, 1) == ["Screen"])
    commands.print_to("screen --watch", "")
    await until(lambda: labels(surface, 1) == ["Speaker"])
    assert daemon.slots is not None
    assert daemon.slots.absent == {"screen"}
    daemon.stop()
    await task


async def test_a_reload_with_another_voip_provider_runs_it(
    tmp_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS)
    daemon = make(path, surface, Processes())
    task = asyncio.create_task(daemon.run())
    await until(lambda: labels(surface, 1) == ["Speaker"])
    first = daemon._voip_task
    assert daemon.voip.name == "bridge"
    assert first is not None

    path.write_text(SLOTS + '\n[voip]\nprovider = "demo"\nparticipants = ["Ann"]\n')
    assert daemon.reload()
    assert daemon.voip.name == "demo"
    await until(lambda: "Ann" in labels(surface, 8))
    await until(first.done)
    task.cancel()
    await settle()


async def test_the_slots_wait_for_the_sound_server(tmp_path: Path, surface: RecordingSurface) -> None:
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS)
    daemon = make(path, surface, Processes(), states=())
    steps: list[int] = []
    daemon.step = lambda: steps.append(1)  # type: ignore[method-assign]
    task = asyncio.create_task(daemon.run())
    daemon.wake_slots()
    await asyncio.sleep(0.05)
    assert steps == []
    task.cancel()
    await settle()


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
    daemon.request_mode("gaming")
    daemon.request_mode("default")
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


async def test_the_slots_in_home_assistant(
    tmp_path: Path, surface: RecordingSurface, notifications: Notifications, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.support.mqtt import FakeBroker
    from xtouch_daemon import mqtt as mqtt_module
    from xtouch_daemon.config.sections import MqttConfig
    from xtouch_daemon.mqtt import MqttBridge

    monkeypatch.setattr(mqtt_module, "RECONNECT_DELAY", 0.001)
    broker = FakeBroker()
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS + '[mqtt]\nhost = "broker"\n')
    bridge = MqttBridge(MqttConfig(host="broker"), client_factory=broker.client)
    daemon = Daemon(
        parse_config(path.read_text()),
        FakeBackend((STATE,)),
        surface,
        path,
        capture_command=QUIET,
        bridge=bridge,
        processes=Processes(),
    )
    task = asyncio.create_task(daemon.run())
    entities = daemon.slot_entities
    assert entities is not None
    await until(lambda: broker.last(entities.slots[2].state_topic) == "app:Spotify")
    # a reload: entities of the new configuration
    assert daemon.reload()
    assert daemon.slot_entities is not entities
    # the broker goes away and comes back: everything again
    count = len(broker.published)
    broker.disconnect()
    await until(lambda: len(broker.published) > count + 20)
    daemon.stop()
    await task


async def test_the_live_view_shows_the_slots_and_sets_modes_and_overrides(
    tmp_path: Path, surface: RecordingSurface
) -> None:
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS)
    processes = Processes()
    daemon = make(path, surface, processes)
    assert daemon.slots is not None
    assert daemon.snapshot().slots is None
    task = asyncio.create_task(daemon.run())
    await until(lambda: labels(surface, 1) == ["Speaker"])
    gui = object()

    view = daemon.snapshot().slots
    assert view is not None
    assert (view.mode, view.mode_pick) == ("default", None)
    assert view.slots[0] == SlotView(
        1, 1, "out", None, None, ("game if gaming: doesn't hold (gaming is off)", "shows out")
    )
    assert view.slots[1].pool == "auto"
    assert view.slots[1].member == "app:Spotify"
    call = next(state for state in view.states if state.name == "call")
    assert call == StateView("call", False, False, call.since, None, "auto", call.history)
    # its changes of the day, as Unix times: off since the first step
    (first,) = call.history
    assert call.since is not None
    # to the second, as `since`
    assert first[1] is False
    assert abs(first[0] - datetime.fromisoformat(call.since).timestamp()) <= 1
    assert next(state for state in view.states if state.name == "gaming").mode

    assert daemon.on_request(gui, SetMode("gaming")) == Reply("mode", True, "gaming")
    view = daemon.snapshot().slots
    assert view is not None
    assert (view.mode, view.mode_pick) == ("gaming", "gaming")
    assert daemon.on_request(gui, SetMode("nope")) == Reply(
        "mode", False, "There is no mode nope (auto, default, gaming)"
    )
    assert daemon.on_request(gui, SetMode("auto")) == Reply("mode", True, "default")

    assert daemon.on_request(gui, SetOverride("call", "on")) == Reply("override", True, "on")
    view = daemon.snapshot().slots
    assert view is not None
    assert next(state for state in view.states if state.name == "call").override == "on"
    assert labels(surface)[2] == "Mic"
    assert daemon.on_request(gui, SetOverride("gaming", "on")) == Reply(
        "override", False, "There is no state gaming (call)"
    )
    assert daemon.on_request(gui, SetOverride("call", "maybe")) == Reply(
        "override", False, "maybe is no override (auto, on, off)"
    )
    daemon.stop()
    await task


def test_how_the_live_view_names_members() -> None:
    from xtouch_daemon.daemon.slots import _member_text
    from xtouch_daemon.slots.inputs import Channel, Person

    assert _member_text(App("Spotify")) == "app:Spotify"
    assert _member_text(Person("1", "Ann")) == "person:Ann"
    assert _member_text(Person("1", "Ann", "ann")) == "ann"
    assert _member_text(Channel("web")) == "web"
    assert _member_text(None) is None


async def test_the_snapshot_tells_the_channels_with_sound(
    tmp_path: Path, surface: RecordingSurface, notifications: Notifications
) -> None:
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS)
    # the speaker plays, the game is paused, nothing records from the microphone
    playing = AudioState(
        outputs=(output("speaker", 50, running=True),),
        inputs=(source("mic"),),
        streams=(stream(1, "MyGame", "mygame", corked=True),),
        default_output="speaker",
    )
    daemon = make(path, surface, Processes(), (playing,))
    task = asyncio.create_task(daemon.run())
    await until(lambda: daemon.snapshot().sounding == ("out",))
    daemon.stop()
    await task


async def test_a_paused_player_keeps_its_application_on_its_slot(tmp_path: Path, surface: RecordingSurface) -> None:
    path = tmp_path / "slots.toml"
    path.write_text(SLOTS)
    spotify = Player("org.mpris.MediaPlayer2.spotify", None)
    players = FakePlayers(spotify)
    daemon = Daemon(
        parse_config(path.read_text()),
        FakeBackend((STATE,)),
        surface,
        path,
        capture_command=QUIET,
        processes=Processes(),
        players=players,
    )
    task = asyncio.create_task(daemon.run())
    await until(lambda: labels(surface) == ["Speaker", "Spotify", ""])
    assert players.on_change == daemon.wake_slots

    # paused, Spotify ends its stream: its player keeps it on its slot
    players.paused = frozenset({spotify})
    daemon.on_state(dataclasses.replace(STATE, streams=()))
    await settle()
    assert labels(surface)[1] == "Spotify"
    # stopped: the player tells, and the slot lets it go
    players.paused = frozenset()
    daemon.wake_slots()
    await until(lambda: labels(surface)[1] != "Spotify")

    daemon.stop()
    await task
