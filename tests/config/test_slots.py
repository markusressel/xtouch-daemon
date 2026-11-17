"""
Files of channels, states and slots: the strips each slot can show, checked at load, and the configuration of a
result.
"""

import pytest

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.config.slots import showing

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
in_auto = false

[channel.alice]
type = "person"
person = "Alice"
color = "green"

[pool.web]
channels = ["#web"]
color = "blue"

[pool.auto]
exclude = ["beep"]
hold = 2
color = "white"
"""


def test_the_strips_of_every_candidate_and_member():
    config = parse_config(
        CHANNELS
        + '[people]\ncolor = "yellow"\norder = ["Bo"]\n'
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
    # people on auto slots: a person channel as itself, the others with the look of [people]
    assert strips[(4, 0, "alice")].model_dump()["person"] == ("Alice",)
    assert strips[(3, 0, "alice")].model_dump()["color"] == "green"
    assert config.slots.person("Bo").model_dump()["color"] == "yellow"
    # people share auto in every configuration: the voice chat with its defaults
    assert config.voip is not None
    assert config.behavior.auto_hold == 2
    assert "beep" in config.behavior.ignore
    assert "radio" in config.behavior.ignore
    assert "firefox" in config.behavior.ignore
    shown = showing(
        config,
        (
            (0, None, "out", None),
            (0, "web", "radio", None),
            (0, "people", None, "Bo"),
            (0, "people", "alice", None),
            *[(None, None, None, None)] * 4,
        ),
    )
    assert [strip.type for strip in shown.strips[:5]] == ["output", "apps", "voip", "voip", "empty"]
    assert shown.strips[2].model_dump()["person"] == ("Bo",)
    assert shown.strips[3].model_dump()["person"] == ("Alice",)


def test_nothing_ignored_without_apps_channels():
    config = parse_config('[channel.out]\ntype = "output"\n[slots]\n1 = ["out", "-"]\n2 = "-"\n3 = "-"\n')
    assert config.slots is not None
    assert config.slots.ignored() == ()


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('[[strip]]\ntype = "auto"\n[slots]\n1 = "auto"\n', "[slots] replaces [[strip]] and [[layout]]"),
        (
            CHANNELS.replace('label = "Out"', 'label = "Out"\nvolume = 3') + "[slots]\n",
            "channel.out: volume: Extra inputs are not permitted",
        ),
        (CHANNELS + '[slots]\n1 = [{ show = "out", color = "pink" }]\n', "slots.1[0]: color: Input should be"),
        ('[channel.app]\ntype = "apps"\nmatch = ["x"]\n[slots]\n1 = "app"\n', "channel.app: label: Field required"),
        ('[slots]\n1 = "nothing"\n', "slots.1[0]: nothing is no channel or pool"),
        ('[device]\nname = 3\n[slots]\n1 = "auto"\n', "device.name"),
        ('[people]\ncolor = "pink"\n[slots]\n', "people: color: Input should be"),
    ],
)
def test_problems(text: str, problem: str):
    with pytest.raises(ConfigError) as error:
        parse_config(text, "slots.toml")
    assert problem in str(error.value)
