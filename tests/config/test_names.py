"""
Lists of names with presets in the configuration: expanded, and kept as written.
"""

import pytest

from tests.support.config import errors_of
from xtouch_daemon.config import presets
from xtouch_daemon.config.audio_strips import AppsStripConfig
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.sections import BehaviorConfig

PRESETS_CONFIG = """\
[behavior]
ignore = ["@music", "notification"]

[[strip]]
type = "apps"
match = ["@browsers", "netsurf"]
label = "Browser"

[[layout]]
name = "gaming"
apps = ["@games"]
processes = ["@steam-games", "lutris"]
"""


def test_presets_stand_for_their_names_and_keep_how_they_are_written():
    config = parse_config(PRESETS_CONFIG)
    (strip, *_) = config.all_strips()
    assert isinstance(strip, AppsStripConfig)
    assert strip.match[0] == "firefox"
    assert strip.match[-1] == "netsurf"
    assert strip.written("match") == ("@browsers", "netsurf")
    assert "spotify" in config.behavior.ignore
    assert config.behavior.written("ignore") == ("@music", "notification")
    (gaming,) = config.layouts
    assert gaming.apps == ("steam_app_", ".exe", "wine-preloader", "wine64-preloader")
    assert gaming.processes == ("reaper", "lutris")
    assert gaming.written("processes") == ("@steam-games", "lutris")


def test_lists_without_presets_are_written_as_they_are():
    config = parse_config('[[strip]]\ntype = "apps"\nmatch = ["brave"]\nlabel = "B"\n')
    strip = config.strips[0]
    assert isinstance(strip, AppsStripConfig)
    assert strip.written("match") == ("brave",)
    assert config.behavior.written("ignore") == ("speech-dispatcher",)
    # what the models compare: the same file is the same configuration
    assert parse_config(PRESETS_CONFIG) == parse_config(PRESETS_CONFIG)


def test_the_processes_of_an_apps_strip_are_those_of_its_presets():
    strip = AppsStripConfig(type="apps", match=("@steam-games", "mumble"), label="Games")
    assert strip.process_names == ("reaper", "mumble")
    # an inherited strip is the same strip
    config = parse_config(
        '[[strip]]\ntype = "apps"\nmatch = ["@voip"]\nlabel = "VoIP"\n'
        '[[layout]]\nname = "x"\n[[layout.strip]]\ntype = "empty"\n[[layout.strip]]\ntype = "inherit"\nstrip = 1\n'
    )
    inherited = config.all_strips("x")[1]
    assert isinstance(inherited, AppsStripConfig)
    assert inherited.written("match") == ("@voip",)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[[strip]]\ntype = "apps"\nmatch = ["@browser"]\nlabel = "B"',
            "strip[1].match: @browser is no preset; the presets are @browsers, @voip, @steam-games, @games, @music, "
            "@video",
        ),
        ('[[layout]]\nname = "x"\nprocesses = ["@nope"]', "layout[1].processes: @nope is no preset; "),
        ('[behavior]\nignore = ["@"]', "behavior.ignore: @ is no preset; "),
    ],
)
def test_an_unknown_preset_is_an_error_of_its_option(text: str, message: str):
    assert f"\n  {message}" in errors_of(text)


def test_a_preset_in_a_list_it_is_not_for_says_where_it_fits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(presets, "PRESETS", {"toys": presets.Preset("toys", "Toys", streams=("rattle",))})
    message = errors_of('[[layout]]\nname = "x"\nprocesses = ["@toys"]\napps = ["@toys"]')
    assert (
        "layout[1].processes: @toys is not for `processes` of layouts; use it in `match` of apps strips, `apps` of "
        "layouts and `behavior.ignore`" in message
    )
    assert "layout[1].apps" not in message


def test_a_strip_given_as_a_model_keeps_its_presets():
    strip = AppsStripConfig(type="apps", match=("@voip",), label="VoIP")
    config = Config.model_validate({"strip": [strip]})
    (again,) = config.strips
    assert isinstance(again, AppsStripConfig)
    assert again.written("match") == ("@voip",)
    assert AppsStripConfig.model_validate(strip).written("match") == ("@voip",)


METER_POINTS = """
[behavior]
meter_point = "post_fader"

[[strip]]
type = "output"

[[strip]]
type = "input"
meter_point = "pre_fader"

[[layout]]
name = "gaming"
meter_point = "pre_fader"

[[layout.strip]]
type = "inherit"
strip = 2

[[layout.strip]]
type = "inherit"
strip = 1

[[layout.strip]]
type = "apps"
label = "Game"
match = [".exe"]
meter_point = "post_fader"

[[layout]]
name = "plain"
"""


def test_the_meter_point_of_a_strip_wins_over_the_layout_which_wins_over_the_behavior():
    config = parse_config(METER_POINTS)
    assert BehaviorConfig().meter_point == "pre_fader"

    def points(layout: str) -> list[str]:
        return [config.meter_point(strip, layout) for strip in config.all_strips(layout)][:3]

    # the default layout has no option of its own: [behavior] is its
    assert points("default") == ["post_fader", "pre_fader", "post_fader"]
    # an inherited strip brings its own along, else it takes the one of the layout it is in
    assert points("gaming") == ["pre_fader", "pre_fader", "post_fader"]
    assert points("plain") == ["post_fader"] * 3
    # the auto strips that fill a layout up too
    assert config.meter_point(config.all_strips("gaming")[7], "gaming") == "pre_fader"
