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
    config = parse_config(CHANNELS + '[slots]\n1 = ["out", "-"]\n2 = "web"\n3 = "people"\n4 = "alice"\n')
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
    assert strips[(3, 0, None)].type == "voip"
    assert strips[(4, 0, "alice")].model_dump()["person"] == ("Alice",)
    # voip strips without [voip]: its defaults
    assert config.voip is not None
    assert config.behavior.auto_hold == 2
    assert "beep" in config.behavior.ignore
    assert "radio" in config.behavior.ignore
    assert "firefox" in config.behavior.ignore
    shown = showing(config, ((0, None, "out"), (0, "web", "radio"), *[(None, None, None)] * 6))
    assert [strip.type for strip in shown.strips[:3]] == ["output", "apps", "empty"]


def test_without_people_no_voip_section():
    config = parse_config('[channel.out]\ntype = "output"\n[slots]\n1 = ["out", "-"]\n2 = "-"\n3 = "-"\n')
    assert config.slots is not None
    assert config.voip is None
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
    ],
)
def test_problems(text: str, problem: str):
    with pytest.raises(ConfigError) as error:
        parse_config(text, "slots.toml")
    assert problem in str(error.value)
