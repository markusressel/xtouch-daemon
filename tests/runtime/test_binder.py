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
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware.strip import Strip, VirtualStrip
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.runtime import binder as binder_module
from xtouch_daemon.runtime.binder import SlotMixer
from xtouch_daemon.runtime.desk import Desk
from xtouch_daemon.strips.apps import AutoStrip
from xtouch_daemon.strips.voip import VoipStrip
from xtouch_daemon.voip.demo import DemoProvider

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

[pool.auto]
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
    assert mixer.voip_names[3] == "Alice"
    assert mixer.voip_names[7] == "Ann"
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
        async def set_entities(
            self, entities: Mapping[MQTTEntity, str | None], keep: frozenset[str] = frozenset(), preview: bool = False
        ) -> None:
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


def test_a_slot_mixer_needs_a_configuration_of_slots(surface: RecordingSurface) -> None:
    config = parse_config('[[strip]]\ntype = "auto"\n[voip]\nprovider = "demo"\n')
    with pytest.raises(AssertionError):
        SlotMixer(surface, FakeBackend(()), config, None, Desk(surface), DemoProvider(()))  # type: ignore[arg-type]


async def test_a_voip_strip_is_on_its_slot(surface: RecordingSurface) -> None:
    rig = Rig(surface, parse_config(CONFIG))
    rig.step(STATE)
    alice = rig.mixer.channels["alice"]
    assert isinstance(alice, VoipStrip)
    assert isinstance(alice.strip, VirtualStrip)
    assert isinstance(alice.strip.target, Strip)
    rig.mixer.close()
