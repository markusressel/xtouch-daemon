"""
The world of a situation for a virtual twin: what the sound server and the voice chat show for it.
"""

from xtouch_daemon.config.files import parse_config
from xtouch_daemon.slots.inputs import SoundDevice
from xtouch_daemon.slots.outcomes import Situation
from xtouch_daemon.slots.world import DEFAULT_INPUT, DEFAULT_OUTPUT, Names, concrete, world

CONFIG = """
[channel.out]
type = "output"
label = "Out"

[channel.buds]
type = "output"
device = "bluez_output.*"
label = "Buds"

[channel.mic]
type = "input"
label = "Mic"

[pool.music]
kind = "apps"
match = ["spotify"]

[slots]
1 = "out"
2 = "buds"
3 = "mic"
4 = "music"
5 = "apps"
6 = "people"
"""


def make(situation: Situation, names: Names | None = None):
    scene = parse_config(CONFIG, "test").slots.scene
    return world(scene, situation, names or Names())


def test_real_names_come_first_then_made_up_ones():
    made = make(
        Situation("default", frozenset(), frozenset(), people=3, apps=3), Names(("Firefox (firefox)",), ("Ann",))
    )
    assert (made.audio.streams[0].app, made.audio.streams[0].binary) == ("Firefox", "firefox")
    assert len(made.audio.streams) == 3
    assert made.people[0] == "Ann"
    assert len(made.people) == 3


def test_nothing_is_there_unless_the_situation_says_so():
    made = make(Situation("default", frozenset(), frozenset()))
    assert made.audio.streams == ()
    assert made.people == ()


def test_channels_without_devices_take_the_default_devices():
    made = make(Situation("default", frozenset(), frozenset()))
    assert made.audio.default_output == DEFAULT_OUTPUT
    assert made.audio.default_input == DEFAULT_INPUT
    assert [device.name for device in made.audio.outputs] == [DEFAULT_OUTPUT, "bluez_output.1"]


def test_a_device_of_a_channel_is_there_while_not_flipped():
    there = make(Situation("default", frozenset(), frozenset()))
    assert concrete("bluez_output.*") in [device.name for device in there.audio.outputs]
    gone = make(Situation("default", frozenset(), frozenset({"buds"})))
    assert concrete("bluez_output.*") not in [device.name for device in gone.audio.outputs]


def test_real_devices_are_stand_ins():
    made = make(
        Situation("default", frozenset(), frozenset(), devices=1),
        Names(devices=(SoundDevice("usb_headset", "USB Headset", "output"),)),
    )
    assert "usb_headset" in [device.name for device in made.audio.outputs]


def test_a_pattern_becomes_a_node_name():
    assert concrete("bluez_output.*") == "bluez_output.1"
    assert concrete("a?b") == "axb"
