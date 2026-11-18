"""
Lists of names with presets in the configuration: expanded, and kept as written.
"""

import pytest

from tests.support.config import errors_of
from xtouch_daemon.config import presets
from xtouch_daemon.config.audio_strips import AppsStripConfig
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.slots.model import AppsConfig

PRESETS_CONFIG = """\
[pool.apps]
exclude = ["@music", "notification"]

[channel.web]
type = "apps"
match = ["@browsers", "netsurf"]
label = "Browser"

[state.gaming]
mode = true
apps = ["@games"]
processes = ["@steam-games", "lutris"]
"""


def test_presets_stand_for_their_names_and_keep_how_they_are_written():
    config = parse_config(PRESETS_CONFIG)
    strip = config.slots.channels["web"]
    assert isinstance(strip, AppsStripConfig)
    assert strip.match[0] == "firefox"
    assert strip.match[-1] == "netsurf"
    assert strip.written("match") == ("@browsers", "netsurf")
    # states and pools keep them as written, the slots expand them
    scene = config.slots.scene
    apps = scene.pools["apps"]
    assert isinstance(apps, AppsConfig)
    assert apps.exclude == ("@music", "notification")
    assert scene.states["gaming"].processes == ("@steam-games", "lutris")


def test_lists_without_presets_are_written_as_they_are():
    strip = parse_config('[channel.b]\ntype = "apps"\nmatch = ["brave"]\nlabel = "B"\n').slots.channels["b"]
    assert isinstance(strip, AppsStripConfig)
    assert strip.written("match") == ("brave",)
    # what the models compare: the same file is the same configuration
    assert parse_config(PRESETS_CONFIG) == parse_config(PRESETS_CONFIG)


def test_the_processes_of_an_apps_strip_are_those_of_its_presets():
    strip = AppsStripConfig(type="apps", match=("@steam-games", "mumble"), label="Games")
    assert strip.process_names == ("reaper", "mumble")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[channel.b]\ntype = "apps"\nmatch = ["@browser"]\nlabel = "B"',
            "channel.b.match: @browser is no preset; the presets are @browsers, @voip, @steam-games, @games, "
            "@music, @video",
        ),
        ('[state.x]\nprocesses = ["@nope"]', "state.x.processes: @nope is no preset; "),
        ('[pool.apps]\nexclude = ["@"]', "pool.apps.exclude: @ is no preset; "),
    ],
)
def test_an_unknown_preset_is_an_error_of_its_option(text: str, message: str):
    assert f"\n  {message}" in errors_of(text)


def test_a_preset_in_a_list_it_is_not_for_says_where_it_fits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(presets, "PRESETS", {"toys": presets.Preset("toys", "Toys", streams=("rattle",))})
    message = errors_of('[state.x]\nprocesses = ["@toys"]\napps = ["@toys"]')
    assert (
        "state.x.processes: @toys is not for `processes` of states; use it in `match` of apps channels, `apps` of "
        "states and `exclude` of `[pool.apps]`" in message
    )
    assert "state.x.apps" not in message


def test_a_strip_given_as_a_model_keeps_its_presets():
    strip = AppsStripConfig(type="apps", match=("@voip",), label="VoIP")
    assert AppsStripConfig.model_validate(strip).written("match") == ("@voip",)


def test_the_meter_point_of_a_channel_wins_over_the_behavior():
    config = parse_config(
        '[behavior]\nmeter_point = "post_fader"\n'
        '[channel.out]\ntype = "output"\n'
        '[channel.mic]\ntype = "input"\nmeter_point = "pre_fader"\n'
    )
    assert BehaviorConfig().meter_point == "pre_fader"
    channels = config.slots.channels
    assert config.meter_point(channels["out"]) == "post_fader"
    assert config.meter_point(channels["mic"]) == "pre_fader"
