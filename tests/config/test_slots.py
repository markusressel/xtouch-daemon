"""
Files of channels, states and slots: the strips each slot can show, checked at load, and the configuration of a
result.
"""

import pytest

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.slots.model import AppsConfig

CHANNELS = """
[channel.out]
type = "output"
label = "Out"

[channel.browser]
type = "apps"
match = ["@browsers"]
label = "Browser"
color = "magenta"
tags = ["web"]

[channel.radio]
type = "apps"
match = ["radio"]
label = "Radio"
tags = ["web"]
in_pool = false

[channel.alice]
type = "person"
person = "Alice"
color = "green"

[pool.web]
channels = ["#web"]
color = "blue"

[pool.apps]
exclude = ["beep"]
hold = 2

[pool.auto]
color = "white"
"""


def test_the_strips_of_every_candidate_and_member():
    config = parse_config(
        CHANNELS
        + '[pool.people]\ncolor = "yellow"\norder = ["Bo"]\n'
        + '[slots]\n1 = ["out", "-"]\n2 = "web"\n3 = [{ show = "auto", color = "red" }]\n4 = "alice"\n'
    )
    assert config.slots is not None
    strips = config.slots.strips
    assert strips[(1, 0, "out")].type == "output"
    assert strips[(1, 1, None)].type == "empty"
    # a pool of channels: dark without a member, the channel's strip with the pool's look with one
    assert strips[(2, 0, None)].type == "empty"
    assert strips[(2, 0, "radio")].model_dump()["color"] == "blue"
    # auto: its own strip, and the apps channels it takes as a whole
    assert strips[(5, 0, None)].model_dump()["color"] == "white"
    assert strips[(5, 0, "browser")].type == "apps"
    # a channel keeps its own color in a pool
    assert strips[(5, 0, "browser")].model_dump()["color"] == "magenta"
    # the options of a place are for applications without a channel: a channel looks as itself there
    assert strips[(3, 0, None)].model_dump()["color"] == "red"
    assert strips[(3, 0, "radio")].model_dump()["color"] == "white"
    # people on auto slots: a person channel as itself, the others with the look of [pool.people]
    assert strips[(4, 0, "alice")].model_dump()["person"] == ("Alice",)
    assert strips[(3, 0, "alice")].model_dump()["color"] == "green"
    assert config.slots.person("Bo").model_dump()["color"] == "yellow"
    # people share auto in every configuration: the voice chat with its defaults
    assert config.voip is not None
    # each channel on its own, for its controller
    assert config.slots.channels["out"].type == "output"
    assert config.slots.channels["alice"].model_dump()["person"] == ("Alice",)
    assert config.slots.channels["radio"].model_dump()["color"] == "white"


def test_a_place_sets_the_led_of_a_button_and_keeps_the_press_of_the_channel():
    config = parse_config(
        '[channel.out]\ntype = "output"\ntags = ["outs"]\nrec = { press = "cycle_modes" }\n'
        + '[pool.outs]\nchannels = ["#outs"]\nrec = "muted"\n'
        + '[slots]\n1 = [{ show = "out", rec = "playing" }]\n2 = "outs"\n'
    )
    assert config.slots is not None
    rec = config.slots.strips[(1, 0, "out")].model_dump()["rec"]
    assert (rec["press"], rec["led"]) == ("cycle_modes", "playing")
    # the look of a pool fills in the LED the channel leaves open
    rec = config.slots.strips[(2, 0, "out")].model_dump()["rec"]
    assert (rec["press"], rec["led"]) == ("cycle_modes", "muted")


def test_auto_never_takes_screen_readers_unless_exclude_says_otherwise():
    for text, exclude in (("", ("speech-dispatcher",)), ('[pool.apps]\nexclude = ["beep"]\n', ("beep",))):
        apps = parse_config(text).slots.scene.pools["apps"]
        assert isinstance(apps, AppsConfig)
        assert apps.exclude == exclude


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (
            CHANNELS.replace('label = "Out"', 'label = "Out"\nvolume = 3') + "[slots]\n",
            "channel.out: volume: Extra inputs are not permitted",
        ),
        (CHANNELS + '[slots]\n1 = [{ show = "out", color = "pink" }]\n', "slots.1[0]: color: Input should be"),
        (
            CHANNELS.replace('label = "Out"', 'label = "Out"\nmin_volume = 90\nmax_volume = 80') + "[slots]\n",
            "channel.out: min_volume (90) is not below max_volume (80)",
        ),
        (
            '[channel.ann]\ntype = "person"\nperson = "Ann"\nlaunch = ["mumble"]\n',
            "channel.ann: launch: the strips of people have none",
        ),
        (
            '[slots]\n1 = [{ show = "auto", min_volume = 50, max_volume = 40 }]\n',
            "slots.1[0]: min_volume (50) is not below max_volume (40)",
        ),
        ('[channel.app]\ntype = "apps"\nmatch = ["x"]\n[slots]\n1 = "app"\n', "channel.app: label: Field required"),
        ('[slots]\n1 = "nothing"\n', "slots.1[0]: nothing is no channel or pool"),
        ('[device]\nname = 3\n[slots]\n1 = "auto"\n', "device.name"),
        ('[pool.people]\ncolor = "pink"\n[slots]\n', "pool.people: color: Input should be"),
        (
            '[controls]\n8 = { solo = "cycle_modes" }\n',
            "controls.8.solo: the Solo buttons of the chord can't be claimed",
        ),
        (
            '[switching]\nchord = { strips = [2, 3], action = "homeassistant" }\n[slots]\n1 = "auto"\n',
            "switching.chord.action: homeassistant is no action (cycle_modes, mode:<id>, toggle:<state or mode>)",
        ),
        (
            '[switching]\nchord = { action = "mode:x" }\n[slots]\n1 = "auto"\n',
            "switching.chord.action: mode:x: no mode x",
        ),
        ("[switching]\nchord = { strips = [1, 2], what = 1 }\n", "chord: what: only strips and action"),
        ('[switching]\nchord = { action = "toggle:x" }\n', "switching.chord.action: toggle:x: no state or mode x"),
    ],
)
def test_problems(text: str, problem: str):
    with pytest.raises(ConfigError) as error:
        parse_config(text, "slots.toml")
    assert problem in str(error.value)


def test_the_chord_as_a_table():
    config = parse_config(
        '[switching]\nchord = { strips = [2, 7], action = "toggle:call" }\n'
        '[state.call]\nprocesses = ["mumble"]\n[slots]\n1 = "auto"\n'
    )
    assert config.switching.chord == (2, 7)
    assert config.switching.chord_action == "toggle:call"
    # without an action: the next mode
    config = parse_config('[switching]\nchord = { strips = [2, 3] }\n[slots]\n1 = "auto"\n')
    assert (config.switching.chord, config.switching.chord_action) == ((2, 3), "cycle_modes")


def test_the_meter_point_of_a_channel_is_its_own_or_the_one_of_behavior():
    config = parse_config(
        '[behavior]\nmeter_point = "post_fader"\n'
        '[channel.out]\ntype = "output"\n[channel.mic]\ntype = "input"\nmeter_point = "pre_fader"\n'
    )
    assert config.meter_point(config.slots.channels["out"]) == "post_fader"
    assert config.meter_point(config.slots.channels["mic"]) == "pre_fader"


def test_mute_can_flash_on_a_channel_on_the_people_and_in_a_place():
    slots = parse_config(
        """
[voip]
provider = "demo"

[channel.mic]
type = "input"
label = "Mic"
mute_led = "flash"

[channel.ann]
type = "person"
person = "Ann"
mute_led = "flash"

[pool.people]
mute_led = "flash"

[slots]
1 = "mic"
2 = ["people", { show = "mic", mute_led = "on" }]
""",
        "test",
    ).slots
    assert {name: getattr(strip, "mute_led", None) for name, strip in slots.channels.items()} == {
        "mic": "flash",
        "ann": "flash",
    }
    # someone without a channel has the look of the people
    assert getattr(slots.person("Zed"), "mute_led", None) == "flash"
    # the option of a place beats that of its channel
    assert slots.strips[(1, 0, "mic")].mute_led == "flash"  # pyright: ignore[reportAttributeAccessIssue]
    assert slots.strips[(2, 1, "mic")].mute_led == "on"  # pyright: ignore[reportAttributeAccessIssue]
