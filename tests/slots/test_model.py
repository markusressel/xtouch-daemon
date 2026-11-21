"""
Reading channels, pools, states and slots, and every check of them.
"""

import pytest

from tests.support.slots import example, scene
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.slots.model import AUTO, Candidate, ChannelConfig, Launch, PoolConfig

CHANNELS = """
[channel.out]
type = "output"

[channel.spotify]
type = "apps"
match = ["spotify"]
tags = ["media"]

[channel.radio]
type = "apps"
match = ["radio"]
tags = ["media"]

[state.call]
apps = ["discord"]

[state.gaming]
mode = true
processes = ["reaper"]
"""


def test_the_example_reads():
    read = example()
    assert read.modes == ("gaming",)
    assert [str(candidate) for candidate in read.stacks[2]] == ["browser", "auto"]
    # a stack that ends in a pool can't run out, a slot without an entry is auto
    assert [str(candidate) for candidate in read.stacks[7]] == ["voip if call", "auto"]
    assert read.stacks[4][0].options == {"rec": "recording"}
    assert read.stacks[3][0].show == "game"
    assert read.stacks[5] == (Candidate(AUTO),)
    assert read.channels["out"].devices[2] == "bluez_output.*"


def test_stacks_in_all_forms():
    read = scene(
        CHANNELS
        + """
[slots]
1 = "out"
2 = ["-"]
3 = ["- if call", "spotify"]
4 = [{ show = "auto", when = "call", encoder = "pick", max_volume = 150 }, { show = "spotify", color = "red" }]
"""
    )
    # a channel can lose its slot, a condition can fail: those stacks end in auto
    assert [str(c) for c in read.stacks[1]] == ["out", "auto"]
    assert [str(c) for c in read.stacks[2]] == ["-"]
    assert [str(c) for c in read.stacks[3]] == ["- if call", "spotify", "auto"]
    assert read.stacks[4][0].options == {"encoder": "pick", "max_volume": 150}
    assert read.stacks[4][1].options == {"color": "red"}


@pytest.mark.parametrize(
    ("added", "problem"),
    [
        ('[slots]\n9 = "out"', "slots.9: a slot is a number from 1 to 8"),
        ('[slots]\n1 = ["- if present", "out"]', 'slots.1[0]: "present": present of - (nothing) means nothing'),
        ("[state.bad]\nwhen = 'call or'", 'state.bad.when: "call or": the condition ends too early (at 8)'),
        ('[slots]\n1 = "outt"', "slots.1[0]: outt is no channel or pool"),
        ('[slots]\n1 = "out if cal"', 'slots.1[0]: "cal": unknown state cal (did you mean call?)'),
        ('[slots]\n1 = "out if xyz"', 'slots.1[0]: "xyz": unknown state xyz'),
        ('[slots]\n1 = "out if call and"', 'slots.1[0]: "call and": the condition ends too early (at 9)'),
        ('[slots]\n1 = "out if present(nothing)"', 'slots.1[0]: "present(nothing)": nothing is no channel or pool'),
        ("[slots]\n1 = [{ when = 'call' }]", "slots.1[0]: a candidate in table form needs show"),
        ("[slots]\n1 = [{ show = '-', color = 'red' }]", "slots.1[0]: - (nothing) takes no options"),
        (
            "[slots]\n1 = [{ show = 'out', encoder = 'volume' }]",
            "slots.1[0]: encoder is no option of a place for out (it belongs to the channel)",
        ),
        ("[slots]\n1 = [{ show = 'auto', colour = 'red' }]", "slots.1[0]: colour is no option of a place for auto"),
        ("[channel.Big]\ntype = 'output'", "channel.Big: an id is lower case letters, digits and _"),
        ("[channel.state_x]\ntype = 'output'", "channel.state_x: state_x is reserved"),
        ("[state.default]\nmanual = 1", "state.default.manual: Extra inputs are not permitted"),
        ("[state.present]\nprocesses = ['x']", "state.present: present is reserved"),
        ("[channel.people]\ntype = 'output'", "channel.people: people is a built-in pool"),
        ("[channel.auto]\ntype = 'output'", "channel.auto: auto is a built-in pool"),
        (
            "[slots]\n1 = [{ show = 'auto', talking_color = 'red' }]",
            "slots.1[0]: talking_color is no option of a place",
        ),
        ("[slots]\n1 = [{ show = 'auto', id = 'knob' }]", "slots.1[0]: id is no option of a place for auto (a control"),
        ("[slots]\n1 = [{ show = 'auto', encoder = 'homeassistant' }]", 'encoder = "homeassistant" is a control of'),
        ("[controls]\n1 = { fader = 'homeassistant', id = 'out' }", "controls.1.id: out is also a channel, pool or"),
        ("[controls]\n1 = { fader = 'homeassistant', id = 'Knob' }", "controls.1.id: Knob: an id is lower case"),
        ("[controls]\n1 = { fader = 'homeassistant', id = 'slot_2' }", "controls.1.id: slot_2 is reserved"),
        (
            "[controls]\n1 = { fader = 'homeassistant', id = 'knob' }\n2 = { encoder = 'homeassistant', id = 'knob' }",
            "controls.2.id: knob is also the id of controls of slot 1",
        ),
        ("[controls]\n9 = { fader = 'homeassistant' }", "controls.9: a slot is a number from 1 to 8"),
        ("[controls]\n1 = { when = 'call' }", "controls.1: claims nothing"),
        ("[controls]\n1 = [{ rec = 'homeassistant' }, { when = 'call' }]", "controls.1[1]: claims nothing"),
        ("[controls]\n1 = [{ rec = 'homeassistant' }, { rec = 'x' }]", "controls.1[1].rec: x is no action"),
        ("[controls]\n1 = [{ rec = 'homeassistant', size = 3 }]", "controls.1.size: Extra inputs are not permitted"),
        ("[controls]\n1 = { fader = 'volume' }", "controls.1.fader: Input should be 'homeassistant'"),
        ("[controls]\n1 = { select = 'jump' }", "controls.1.select: jump is no action"),
        ("[controls]\n1 = { solo = 'toggle:nope' }", "controls.1.solo: toggle:nope: no state or mode nope"),
        ("[controls]\n1 = { solo = 'mode:call' }", "controls.1.solo: mode:call: no mode call"),
        ("[controls]\n1 = { rec = 'homeassistant', when = 'cal' }", 'controls.1.when: "cal": unknown state cal'),
        ("[controls]\n1 = { rec = 'homeassistant', when = 'call and' }", "controls.1.when: "),
        ("[controls]\n1 = { rec = 'homeassistant', when = 'present(out)' }", "present is only for candidates"),
        (
            "[controls]\n1 = { rec = 'homeassistant' }\n[slots]\n1 = [{ show = 'out', rec = 'mute' }]",
            "slots.1[0]: rec: the slot's controls claim it ([controls])",
        ),
        ("[people]\ncolor = 'red'", "people: the section is [pool.people] now"),
        ("[pool.people]\nlaunch = ['mumble']", "pool.people: launch: the strips of people have none"),
        ("[pool.people]\nlaunch_when_running = true", "pool.people: launch: the strips of people have none"),
        ("[pool.people]\nlabel = 'Friend'", "pool.people: label: only on a person channel"),
        (
            "[controls]\n1 = { select = { launch = [] } }",
            "controls.1.select.launch: Tuple should have at least 1",
        ),
        (
            "[controls]\n1 = { select = { launch = ['x'] }, id = 'knob' }",
            "controls.1.id: names Home Assistant entities",
        ),
        ("[state.out]\nprocesses = ['x']", "state.out: out is also a channel; channels, pools and states share"),
        ("[state.both]\nwhen = 'call'\napps = ['x']", "state.both: when is not together with"),
        ("[state.loop]\nwhen = 'present'", 'state.loop.when: "present": present is only for candidates'),
        ("[state.loop]\nwhen = 'present(out)'", 'state.loop.when: "present(out)": present is only for candidates'),
        ("[pool.media]\nchannels = ['#music']", "pool.media.channels: no channel has the tag music"),
        ("[pool.media]\nchannels = ['tape']", "pool.media.channels: tape is no channel"),
        ("[state.music]\nchannels = ['tape']", "state.music.channels: tape is no channel"),
        ("[channel.app]\ntype = 'apps'", "channel.app: an apps channel needs match"),
        ("[channel.who]\ntype = 'person'", "channel.who: a person channel needs person"),
        (
            "[channel.a]\ntype = 'person'\nperson = 'Al'\n[channel.b]\ntype = 'person'\nperson = ['Bo', 'al']",
            "channel.b: al is also a person of channel a",
        ),
        (
            "[state.a]\nwhen = 'b'\n[state.b]\nwhen = 'not a'",
            "states that refer to each other: a -> b -> a",
        ),
    ],
)
def test_problems(added: str, problem: str):
    with pytest.raises(ConfigError) as error:
        scene(CHANNELS + added)
    assert problem in str(error.value)


def test_tags_stand_for_their_channels_in_the_order_of_the_file():
    read = scene(CHANNELS + "[pool.media]\nchannels = ['out', '#media', 'spotify']")
    media = read.pools["media"]
    assert isinstance(media, PoolConfig)
    assert read.members_of(media.channels) == ("out", "spotify", "radio")


def test_the_devices_and_people_of_channels():
    assert ChannelConfig(type="output").devices == ()
    assert ChannelConfig(type="output", device="speaker").devices == ("speaker",)
    assert ChannelConfig(type="output", device=("a", "b")).devices == ("a", "b")
    assert ChannelConfig(type="person", person="Al").people == ("Al",)
    assert ChannelConfig(type="person", person=("Al", "Bo")).people == ("Al", "Bo")
    assert ChannelConfig(type="output").people == ()


def test_controls_of_slots():
    read = scene(
        CHANNELS
        + """
[controls]
4 = { encoder = "homeassistant", id = "desk_knob" }
7 = { select = { launch = ["mumble", "mumble://example.org"] }, when = "not call" }
2 = { solo = "toggle:call", rec = "mode:gaming", select = "mode:default" }
# by mode: the first that holds; both may name the same entities
3 = [
    { encoder = "homeassistant", id = "strip_3", when = "gaming" },
    { fader = "homeassistant", encoder = "homeassistant", id = "strip_3" },
]
1 = { select = "toggle:gaming" }
"""
    )
    assert read.controls[4][0].claimed == ("encoder",)
    assert read.controls[7][0].select == Launch(launch=("mumble", "mumble://example.org"))
    assert read.control_conditions[(7, 0)].text == "not call"
    assert read.controls[2][0].claimed == ("select", "rec", "solo")
    assert [controls.claimed for controls in read.controls[3]] == [("encoder",), ("fader", "encoder")]
    assert read.control_conditions[(3, 0)].text == "gaming"
    assert (3, 1) not in read.control_conditions
