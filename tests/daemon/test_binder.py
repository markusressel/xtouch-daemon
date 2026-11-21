"""
The slot mixer: a controller per channel, per application and per person, bound to the strips of the device as the
slots say; slots whose result stays the same are not touched.
"""

import asyncio
from collections.abc import Mapping

import pytest
from haad_mqtt_autodiscovery.entity import MQTTEntity
from haad_mqtt_autodiscovery.entity.select import MQTTSelect

from tests.support.audio import FakeBackend, output, source, stream
from tests.support.hardware import RecordingSurface
from tests.support.slots import Rig
from tests.support.tasks import settle
from tests.support.watches import ProgramCommands
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.daemon import binder as binder_module
from xtouch_daemon.daemon.binder import SlotMixer
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.hardware.strip import Strip, VirtualStrip
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.strips.apps import AutoStrip
from xtouch_daemon.strips.voip import VoipStrip

CONFIG = """
[voip]
provider = "demo"
participants = ["Ann", "Alice"]

[channel.out]
type = "output"
device = "speaker"
label = "Speaker"

[channel.game]
type = "apps"
match = ["mygame"]
label = "Game"

[channel.mic]
type = "input"
device = "mic"
label = "Mic"

[channel.alice]
type = "person"
person = "Alice"
label = "Alice"

[pool.apps]
hold = 0

[state.gaming]
processes = ["mygame"]
delay_off = 0

[slots]
1 = ["out if gaming", "mic"]
2 = ["game if gaming", "out"]
3 = [{ show = "auto", when = "gaming", max_volume = 50, color = "red" }, "auto"]
4 = "alice"
"""

STATE = AudioState(
    outputs=(output("speaker", 50),),
    inputs=(source("mic"),),
    streams=(stream(1, "Spotify", "spotify"),),
    default_output="speaker",
)


async def test_only_the_slots_that_changed_are_bound_again(
    surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(surface, parse_config(CONFIG))
    mixer = rig.mixer
    assert mixer.controllers == []
    rig.step(STATE)
    assert rig.labels()[:4] == ["Mic", "Speaker", "Spotify", "Alice"]
    assert rig.labels()[7] == "Ann"
    spotify = mixer.controllers[2]
    assert isinstance(spotify, AutoStrip)
    assert spotify.max_volume is None
    assert spotify.slot is not None

    redrawn: list[int] = []
    for index in (2, 3, 7):
        strip = surface.strips[index]
        monkeypatch.setattr(strip, "show_from", lambda view, index=index: redrawn.append(index))
    # gaming: the speaker moves from slot 2 to slot 1 (handled first), the game takes slot 2; Spotify stays where
    # it is, with the options of the other candidate of slot 3
    rig.step(STATE, frozenset({"mygame"}))
    assert rig.labels()[:3] == ["Speaker", "Game", "Spotify"]
    assert redrawn == []
    assert mixer.controllers[2] is spotify
    assert spotify.max_volume == 50
    assert spotify.look.color == "red"
    speaker = mixer.channels["out"].strip
    assert isinstance(speaker, VirtualStrip)
    assert speaker.target is surface.strips[0]
    mic = mixer.channels["mic"].strip
    assert isinstance(mic, VirtualStrip)
    assert mic.target is None
    monkeypatch.undo()

    # Spotify stops: its controller goes, slot 3 is dark
    rig.step(AudioState(outputs=STATE.outputs, inputs=STATE.inputs, default_output="speaker"))
    assert ("app", "Spotify") not in mixer.members
    assert rig.labels()[2] == ""
    # it plays again: a new controller
    rig.step(STATE, frozenset({"mygame"}))
    assert rig.labels()[2] == "Spotify"
    assert mixer.controllers[2] is not spotify

    mixer.close()
    assert all(controller.strip.target is None for controller in mixer.all_controllers)  # type: ignore[attr-defined]
    assert rig.desk.presenters == [None] * 8


async def test_the_channels_announce_their_entities_and_follow_the_processes(
    surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(binder_module, "PROCESS_INTERVAL", 0.001)
    announced: list[dict[MQTTEntity, str | None]] = []
    previews: list[bool] = []

    class RecordingBridge(MqttBridge):
        async def set_entities(self, entities: Mapping[MQTTEntity, str | None], preview: bool = False) -> None:
            announced.append(dict(entities))
            previews.append(preview)

    config = parse_config(
        CONFIG
        + '[channel.lamp]\ntype = "homeassistant"\n'
        + '[channel.voice]\ntype = "apps"\nmatch = ["mumble"]\nlaunch = ["mumble"]\nlabel = "Voice"\n'
        + '[mqtt]\nhost = "broker"\n'
    )
    assert config.mqtt is not None
    scans: list[int] = []

    def processes() -> frozenset[str]:
        scans.append(1)
        return frozenset({"bash"})

    shared = MQTTSelect("xtouch", "layout", "Layout", options=["default"])
    rig = Rig(
        surface,
        config,
        bridge=RecordingBridge(config.mqtt),
        shared_entities={shared: "default"},
        preview=True,
        processes=processes,
    )
    assert rig.mixer.watches_processes
    assert rig.mixer.processes == {"bash"}
    task = asyncio.create_task(rig.mixer.run())
    await asyncio.sleep(0.01)
    task.cancel()
    await settle()
    assert len(scans) > 1
    assert announced == [rig.mixer.channels["lamp"].entities | {shared: "default"}]
    assert previews == [True]
    rig.mixer.close()


async def test_a_voip_strip_is_on_its_slot(surface: RecordingSurface) -> None:
    rig = Rig(surface, parse_config(CONFIG))
    rig.step(STATE)
    alice = rig.mixer.channels["alice"]
    assert isinstance(alice, VoipStrip)
    assert isinstance(alice.strip, VirtualStrip)
    assert isinstance(alice.strip.target, Strip)
    rig.mixer.close()


async def test_a_slot_that_shows_another_candidate_flashes_what_and_why(surface: RecordingSurface) -> None:
    rig = Rig(surface, parse_config(CONFIG))
    rig.step(STATE, flash=1.0)
    # the first step: nothing to flash
    assert all(strip.overlay is None for strip in surface.strips)
    rig.step(STATE, frozenset({"mygame"}), flash=1.0)
    assert surface.strips[0].overlay == ("Speaker", "gaming".center(7))
    assert surface.strips[1].overlay == ("Game".center(7), "gaming".center(7))
    # the same application on the other candidate of slot 3 flashes too, the slots that stay don't
    assert surface.strips[2].overlay is not None
    assert surface.strips[3].overlay is None
    rig.step(STATE, flash=1.0)
    assert surface.strips[0].overlay == ("Mic".center(7), "not gam")
    assert rig.mixer._why(4, 0, 0) == ""
    rig.mixer.close()


CUSTOM = """
[voip]
provider = "demo"

[channel.out]
type = "output"
device = "speaker"
label = "Speaker"

[channel.screen]
type = "custom"
label = "Screen"
present = { watch = "screen --watch" }
fader = { set = "b {value}", watch = "b --watch", min = 0.1, max = 1.0 }

[channel.lamp]
type = "custom"
label = "Lamp"
absent_after = 0
present = { watch = "lamp --watch" }

[channel.clock]
type = "custom"
label = "Clock"
lcd = { watch = "date --watch" }

[pool.extras]
channels = ["lamp", "clock"]

[slots]
1 = ["screen if present", "out"]
2 = ["extras"]
3 = ["extras"]
"""


async def test_a_custom_channel_takes_part_in_the_slots_as_its_present_says(surface: RecordingSurface) -> None:
    commands = ProgramCommands()
    woken: list[str] = []
    rig = Rig(surface, parse_config(CUSTOM), commands=commands, on_presence=lambda: woken.append("woken"))
    rig.step(STATE)
    # nothing known yet: present, as a channel without `present` always is
    assert rig.labels()[:3] == ["Screen", "Lamp", "Clock"]
    commands.print_to("screen --watch", "")
    commands.print_to("lamp --watch", "")
    await settle()
    assert woken == ["woken", "woken"]
    assert rig.engine.absent == {"screen", "lamp"}
    rig.step(STATE)
    # the lamp goes at once (`absent_after = 0`): the pool hands out the clock; the screen stays 3 s
    assert rig.labels()[:3] == ["Screen", "Clock", ""]
    for _ in range(3):
        rig.step(STATE)
    assert rig.labels()[:3] == ["Speaker", "Clock", ""]
    commands.print_to("screen --watch", "DisplayPort-1")
    commands.print_to("lamp --watch", "on")
    await settle()
    assert rig.engine.absent == frozenset()
    rig.step(STATE)
    assert rig.labels()[:3] == ["Screen", "Lamp", "Clock"]
    # the same again tells nobody
    commands.print_to("lamp --watch", "on, still")
    await settle()
    assert len(woken) == 4
    rig.mixer.close()
    await commands.wait_closed()


async def test_a_reload_keeps_the_absence_until_the_new_watch_tells(surface: RecordingSurface) -> None:
    commands = ProgramCommands()
    rig = Rig(surface, parse_config(CUSTOM), commands=commands)
    commands.print_to("screen --watch", "")
    await settle()
    assert rig.engine.absent == {"screen"}
    rig.mixer.close()
    # the new configuration: the screen is still away until its watch says otherwise; the lamp has no `present` now
    rig.engine.absent |= {"lamp"}
    rig.mixer = SlotMixer(
        surface,
        FakeBackend(()),
        parse_config(CUSTOM.replace('present = { watch = "lamp --watch" }', "")),
        rig.engine,
        rig.desk,
        rig.voip,
        commands=commands,
    )
    assert rig.engine.absent == {"screen"}
    rig.mixer.close()
    await commands.wait_closed()


async def test_a_member_has_no_entities_in_home_assistant(
    surface: RecordingSurface, caplog: pytest.LogCaptureFixture
) -> None:
    # an application on an `auto` place whose meter and color are in Home Assistant: the entities are the channels'
    config = parse_config(
        '[voip]\nprovider = "demo"\n[mqtt]\nhost = "broker"\n[slots]\n'
        '1 = [{ show = "auto", meter = "homeassistant", color = "homeassistant" }]\n'
    )
    assert config.mqtt is not None
    rig = Rig(surface, config, bridge=MqttBridge(config.mqtt))
    rig.step(STATE)
    member = next(member for member in rig.mixer.members.values() if isinstance(member, AutoStrip))
    assert member.controls is None
    assert member.entities == {}
    # the log says why its parts show what they do while Home Assistant is not there
    assert 'meter = "homeassistant" works on the channel itself only' in caplog.text
    assert 'color = "homeassistant" works on the channel itself only' in caplog.text
    rig.mixer.close()


async def test_an_absent_custom_channel_on_a_fixed_slot_is_dark_and_does_nothing(surface: RecordingSurface) -> None:
    commands = ProgramCommands()
    config = parse_config(
        '[voip]\nprovider = "demo"\n'
        '[channel.screen]\ntype = "custom"\nlabel = "Screen"\nabsent_after = 0\n'
        'present = { watch = "screen --watch" }\n'
        'fader = { set = "b {value}", watch = "b --watch", min = 0.1, max = 1.0 }\n'
        'select = { press = { run = "x" }, led = "press" }\n'
        '[slots]\n1 = "screen"\n'
    )
    rig = Rig(surface, config, commands=commands)
    rig.step(STATE)
    commands.print_to("b --watch", "0.6")
    commands.print_to("screen --watch", "")
    await settle()
    rig.step(STATE)
    assert rig.engine.absent == {"screen"}
    strip = surface.strips[0]
    assert strip.color == Color.BLACK
    assert strip.text == ["Screen", "off"]
    assert strip.ring == (0, RingMode.DOT)
    assert strip.fader == 0
    assert all(led == Led.OFF for led in strip.leds.values())
    controller = rig.mixer.channels["screen"]
    assert controller.held_meter("pre_fader") is None
    # the hand changes nothing, nothing runs
    controller.on_fader(0.9)
    controller.on_encoder(3)
    controller.on_button(Button.SELECT, True)
    controller.on_button(Button.SELECT, False)
    await settle()
    assert commands.runs == []
    # back again, it shows its value
    commands.print_to("screen --watch", "DisplayPort-1")
    await settle()
    rig.step(STATE)
    assert strip.text == ["Screen", "0.6"]
    assert strip.color == Color.WHITE
    rig.mixer.close()
    await commands.wait_closed()
