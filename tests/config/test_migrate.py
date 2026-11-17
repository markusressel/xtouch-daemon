"""
`migrate-config`: strips and layouts written as channels, states and slots.
"""

import pytest

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import example_config, parse_config
from xtouch_daemon.config.migrate import migrate

OLD = """[behavior]
auto_hold = 4
collapse_hold = 2
ignore = ["speech-dispatcher", "@browsers"]

[mqtt]
host = "broker"

[switching]
hold = 5
chord = [1, 8]

[[strip]]
type = "output"
device = "speaker"
label = "Speaker"
color = "cyan"

[[strip]]
type = "apps"
match = ["@voip"]
label = "VoIP"
launch = ["mumble"]
collapse = true

[[strip]]
type = "auto"
launch = ["spotify"]
fader = "homeassistant"

[[strip]]
type = "voip"
color = "blue"
launch = ["mumble", "mumble://x"]

[[strip]]
type = "voip"
person = ["Ann", "ann-phone"]

[[strip]]
type = "homeassistant"
label = "Lamp"

[[strip]]
type = "empty"

[[strip]]
type = "input"
label = "Mic"

[[layout]]
name = "gaming"
label = "Gaming"
processes = ["@steam-games"]
priority = 2
meter_point = "post_fader"

[[layout.strip]]
type = "inherit"

[[layout.strip]]
type = "apps"
match = ["@games"]
label = "Game"

[[layout.strip]]
type = "inherit"
strip = 8

[[layout.strip]]
type = "homeassistant"
label = "Desk"

[[layout]]
name = "voice"
apps = ["mumble"]

[[layout.strip]]
type = "inherit"
layout = "gaming"
strip = 2
"""

NEW = """[mqtt]
host = "broker"

[switching]
chord = [1, 8]

[channel.speaker]
type = "output"
device = "speaker"
label = "Speaker"
color = "cyan"

[channel.voip]
type = "apps"
match = ["@voip"]
label = "VoIP"
launch = ["mumble"]
absent_after = 2

[channel.ann]
type = "person"
person = ["Ann", "ann-phone"]

[channel.strip_6]
type = "homeassistant"
label = "Lamp"

[channel.mic]
type = "input"
label = "Mic"

[channel.game]
type = "apps"
match = ["@games"]
label = "Game"

[channel.strip_4]
type = "homeassistant"
label = "Desk"

[pool.auto]
hold = 4
exclude = ["speech-dispatcher", "@browsers"]

[people]
color = "blue"

[state.gaming]
mode = true
label = "Gaming"
processes = ["@steam-games"]
priority = 2
delay_off = 5

[state.voice]
mode = true
apps = ["mumble"]
delay_off = 5

[slots]
1 = ["game if voice", "speaker"]
2 = [{show = "game", when = "gaming", meter_point = "post_fader"}, "auto if voice", "voip if present", "auto"]
3 = [{show = "mic", when = "gaming", meter_point = "post_fader"}]
4 = "strip_4 if gaming"
5 = [{show = "auto", when = "gaming", meter_point = "post_fader"}, "auto if voice", "ann"]
6 = [{show = "auto", when = "gaming", meter_point = "post_fader"}, "auto if voice", "strip_6"]
7 = [{show = "auto", when = "gaming", meter_point = "post_fader"}, "auto if voice", "-"]
8 = [{show = "auto", when = "gaming", meter_point = "post_fader"}, "auto if voice", "mic"]

[controls]
3 = {fader = "homeassistant", select = {launch = ["spotify"]}, id = "strip_3", when = "not gaming and not voice"}
4 = {select = {launch = ["mumble", "mumble://x"]}, when = "not gaming and not voice"}
"""


def test_strips_and_layouts_become_channels_states_and_slots() -> None:
    migration = migrate(OLD)
    assert migration.text == NEW
    assert migration.notes == (
        "strip 2: collapse: voip stays on its slot while present, auto otherwise (nothing shifts; a pool of channels "
        "fills slots in order)",
        "strip 6: channel strip_6, named after its entities; rename it to something that says what it is",
        "strip 3 of layout gaming: inherit: strip 8",
        "strip 4 of layout gaming: channel strip_4, named after its entities; rename it to something that says what "
        "it is",
        "strip 1 of layout voice: inherit: strip 2 of layout gaming",
        "switching.hold: now delay_off of each mode",
        "The layouts are modes: select.<namespace>_mode replaces select.<namespace>_layout in Home Assistant (change "
        "automations that use it); the layout kept for the next start is not carried over",
        "voip strips: the people share the slots of auto now, from the right; their look is in [people]",
    )
    config = parse_config(migration.text)
    assert config.slots is not None


def test_the_example_keeps_its_comments() -> None:
    migration = migrate(example_config())
    assert migration.text.startswith("# xtouch-daemon configuration")
    assert migration.notes == ("Comments about strips and layouts are still in the file: delete or rewrite them",)
    assert parse_config(migration.text).slots is not None


def test_only_files_with_strips_and_layouts() -> None:
    with pytest.raises(ConfigError, match="has channels, states and slots already"):
        migrate('[channel.out]\ntype = "output"\n[slots]\n1 = "out"\n')
    with pytest.raises(ConfigError, match="has errors"):
        migrate("[behavior]\nmax_volume = 300\n")


EDGE = """[mqtt]
host = "b"

[behavior]
max_volume = 120

[switching]
banner = 1

[[strip]]
type = "auto"
encoder = "homeassistant"
collapse = true
id = "knob"

[[strip]]
type = "voip"
color = "red"

[[strip]]
type = "voip"
color = "blue"

[[strip]]
type = "voip"
person = ["Bob"]

[[strip]]
type = "output"
id = "desk"
fader = "homeassistant"

[[strip]]
type = "output"
label = "1st"
meter_point = "post_fader"

[[strip]]
type = "output"
label = "Auto"

[[strip]]
type = "apps"
match = ["x"]
label = "X"
launch = ["x"]
launch_when_running = true
collapse = true

[[strip]]
type = "input"
label = "Late"

[[strip]]
type = "auto"

[[layout]]
name = "a"
meter_point = "post_fader"

[[layout.strip]]
type = "inherit"
strip = 6

[[layout.strip]]
type = "auto"
launch = ["y"]
launch_when_running = true

[[layout.strip]]
type = "output"
choices = [{ device = "a" }, { device = "b" }]

[[layout.strip]]
type = "output"
id = "desk"
device = "other"
fader = "homeassistant"
"""


def test_ids_people_controls_and_strips_without_a_slot() -> None:
    migration = migrate(EDGE)
    text = migration.text
    assert '[channel.auto_2]\ntype = "output"\nlabel = "Auto"\n' in text
    assert '[channel.output_6]\ntype = "output"\nlabel = "1st"\nmeter_point = "post_fader"\n' in text
    assert '[channel.bob]\ntype = "person"\nperson = "Bob"\n' in text
    assert "launch_when_running = true" in text
    assert '[people]\ncolor = "red"\n' in text
    assert '1 = "output_6 if a"\n' in text
    assert '8 = [{show = "auto", when = "a", meter_point = "post_fader"}, "x if present", "auto"]\n' in text
    assert '1 = {encoder = "homeassistant", id = "knob", when = "not a"}\n' in text
    assert '2 = {select = {launch = ["y"], launch_when_running = true}, when = "a"}\n' in text
    assert "[behavior]\nmax_volume = 120\n" in text
    assert "delay_off" not in text
    assert migration.notes[:4] == (
        "strip 1: collapse is gone for auto: the slot shows auto, nothing shifts",
        "strip 3: color differs from the other voip strips: [people] has one",
        "strip 8: collapse: x stays on its slot while present, auto otherwise (nothing shifts; a pool of channels "
        "fills slots in order)",
        "strip 9: no slot (the device has 8): channel late is not shown; put it on a slot or in a pool",
    )
    assert (
        "strip 4 of layout a: its entities in Home Assistant are now *_desk_2_* (another strip had *_desk_*); change "
        "automations that use them"
    ) in migration.notes
    assert parse_config(text).slots is not None


def test_the_default_hold_of_modes_is_not_written() -> None:
    migration = migrate(
        '[switching]\nhold = 10\n[[strip]]\ntype = "auto"\nlaunch = ["z"]\n'
        '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\n'
    )
    assert "delay_off" not in migration.text
    assert '1 = {select = {launch = ["z"]}}\n' in migration.text
    assert "[slots]" in migration.text
