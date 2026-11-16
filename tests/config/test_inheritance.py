"""
`inherit` strips: from any layout and strip.
"""

import re

import pytest

from tests.support.config import errors_of
from xtouch_daemon.config.audio_strips import AppsStripConfig
from xtouch_daemon.config.files import (
    parse_config,
)
from xtouch_daemon.config.strips import HomeAssistantStripConfig

INHERIT = """
[mqtt]
host = "broker"

[voip]

[[strip]]
type = "output"
label = "Out"
collapse = true

[[strip]]
type = "apps"
match = ["spotify"]
label = "Music"
id = "music"
launch = ["spotify"]

[[strip]]
type = "homeassistant"

[[layout]]
name = "voice"

[[layout.strip]]
type = "voip"

[[layout.strip]]
type = "voip"
person = "Ann"

[[layout.strip]]
type = "inherit"
strip = "music"

[[layout]]
name = "games"

[[layout.strip]]
type = "inherit"
layout = "voice"
strip = 1

[[layout.strip]]
type = "inherit"
layout = "voice"
strip = 2

[[layout.strip]]
type = "inherit"
layout = "voice"
strip = 3

[[layout.strip]]
type = "inherit"
strip = 3

[[layout.strip]]
type = "inherit"
layout = "voice"
"""


def test_an_inherit_strip_takes_any_strip_of_any_layout() -> None:
    config = parse_config(INHERIT)
    voice, games = config.all_strips("voice"), config.all_strips("games")
    # the same strips, the same objects
    assert (voice[0], voice[1]) == (games[0], games[1])
    assert voice[0] is games[0]
    assert voice[1] is games[1]
    # with all their options: launch, collapse
    music = config.strips[1]
    assert voice[2] is games[2] is music
    assert isinstance(music, AppsStripConfig)
    assert music.launch == ("spotify",)
    assert config.inherited("games")[:3] == (
        "layout voice, strip 1",
        "layout voice, strip 2",
        "the default layout, strip 2",
    )
    # the homeassistant strip keeps the entities of its place in the default layout
    home_assistant = games[3]
    assert isinstance(home_assistant, HomeAssistantStripConfig)
    assert home_assistant.id == "strip_3"
    assert config.home_assistant_strips("games") == [(home_assistant, "strip_3")]
    # without strip: the same place, which voice has no strip for
    assert games[4].type == "auto"


def test_an_inherit_strip_in_the_default_layout_names_its_strip() -> None:
    config = parse_config(
        '[[strip]]\ntype = "inherit"\nlayout = "a"\n[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "output"\n'
    )
    assert config.all_strips()[0] is config.layout("a").strips[0]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\nlayout = "b"\n',
            r"layout\[1\].strip\[1\]: inherit from the layout b, which is not there",
        ),
        (
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\nstrip = 2\n',
            "inherit strip 2, but the default layout has 0 strips",
        ),
        (
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\nstrip = "x"\n',
            "inherit strip x, but the default layout has no strip with that id",
        ),
        (
            '[[strip]]\ntype = "auto"\nid = "x"\n[[strip]]\ntype = "auto"\nid = "x"\n'
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\nstrip = "x"\n',
            "inherit strip x, but the default layout has 2 strips with that id",
        ),
        (
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\nlayout = "b"\nstrip = 1\n'
            '[[layout]]\nname = "b"\n[[layout.strip]]\ntype = "inherit"\nlayout = "a"\nstrip = 1\n',
            r"inherit strips that refer to each other: layout\[1\].strip\[1\] -> layout\[2\].strip\[1\] -> "
            r"layout\[1\].strip\[1\]",
        ),
        (
            '[[layout]]\nname = "a"\n'
            + "".join(f'[[layout.strip]]\ntype = "inherit"\nlayout = "a"\nstrip = {n + 1}\n' for n in range(1, 10))
            + '[[layout.strip]]\ntype = "auto"\ncollapse = true\n',
            r"layout\[1\].strip\[1\]: more than 8 inherit strips refer to one another",
        ),
        (
            '[mqtt]\nhost = "b"\n[[strip]]\ntype = "homeassistant"\n'
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "homeassistant"\n'
            '[[layout.strip]]\ntype = "inherit"\nlayout = "default"\nstrip = 1\n',
            "strips in Home Assistant with the same id \\(layout a\\): strip_1",
        ),
    ],
)
def test_errors_of_inherit_strips(text: str, message: str) -> None:
    assert re.search(message, errors_of(text))
