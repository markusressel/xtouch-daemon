"""
Reading channels, pools, states and slots, and every check of them.
"""

import pytest

from tests.support.slots import example, scene
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.slots.model import AUTO, Candidate, ChannelConfig

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
    assert [str(candidate) for candidate in read.stacks[2]] == ["people if gaming and present", "browser", "auto"]
    # a stack that ends in a pool can't run out, a slot without an entry is auto
    assert [str(candidate) for candidate in read.stacks[7]] == ["voip if call or gaming", "auto"]
    assert read.stacks[3] == (Candidate(AUTO),)
    assert read.channels["out"].devices[2] == "bluez_output.*"


def test_stacks_in_all_forms():
    read = scene(
        CHANNELS
        + """
[slots]
1 = "out"
2 = ["-"]
3 = ["- if call", "spotify"]
4 = [{ show = "auto", when = "call", encoder = "homeassistant", id = "knob" }, { show = "spotify", color = "red" }]
"""
    )
    # a channel can lose its slot, a condition can fail: those stacks end in auto
    assert [str(c) for c in read.stacks[1]] == ["out", "auto"]
    assert [str(c) for c in read.stacks[2]] == ["-"]
    assert [str(c) for c in read.stacks[3]] == ["- if call", "spotify", "auto"]
    assert read.stacks[4][0].options == {"encoder": "homeassistant", "id": "knob"}
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
        ("[state.out]\nprocesses = ['x']", "state.out: out is also a channel; channels, pools and states share"),
        ("[state.both]\nwhen = 'call'\napps = ['x']", "state.both: Value error, when is not together with"),
        ("[state.loop]\nwhen = 'present'", 'state.loop.when: "present": present is only for candidates'),
        ("[state.loop]\nwhen = 'present(out)'", 'state.loop.when: "present(out)": present is only for candidates'),
        ("[pool.media]\nchannels = ['#music']", "pool.media.channels: no channel has the tag music"),
        ("[pool.people]\nshare = 'out'", "pool.people.share: only people share, and only the slots of auto"),
        ("[pool.auto]\nshare = 'auto'", "pool.auto.share: only people share"),
        ("[pool.people]\norder = ['Bob']", "pool.people.order: only for people that share the slots of auto"),
        ("[pool.media]\nchannels = ['tape']", "pool.media.channels: tape is no channel"),
        ("[state.music]\nchannels = ['tape']", "state.music.channels: tape is no channel"),
        ("[channel.app]\ntype = 'apps'", "channel.app: Value error, an apps channel needs match"),
        ("[channel.who]\ntype = 'person'", "channel.who: Value error, a person channel needs person"),
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
    assert read.members_of(read.pools["media"].channels) == ("out", "spotify", "radio")


def test_the_devices_and_people_of_channels():
    assert ChannelConfig(type="output").devices == ()
    assert ChannelConfig(type="output", device="speaker").devices == ("speaker",)
    assert ChannelConfig(type="output", device=("a", "b")).devices == ("a", "b")
    assert ChannelConfig(type="person", person="Al").people == ("Al",)
    assert ChannelConfig(type="person", person=("Al", "Bo")).people == ("Al", "Bo")
    assert ChannelConfig(type="output").people == ()
