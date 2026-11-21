"""
What a place takes for the options it leaves unset: those of its channel or pool, else those of the strip type.
"""

from typing import Any

import pytest

from xtouch_daemon.gui.domain.places import (
    Origin,
    Source,
    inherited,
    inherited_part,
    origin,
    place_help,
    program_text,
    value_text,
)

VALUES: dict[str, Any] = {
    "behavior": {"max_volume": 120, "meter_point": "post_fader"},
    "channel": {
        "out": {"type": "output", "device": "speaker", "label": "Speaker", "color": "cyan", "rec": "muted"},
        "mic": {"type": "input", "device": "mic", "meter": False, "solo": {"led": {"watch": ["busy", "-q"]}}},
        "lamp": {"type": "custom", "color": "homeassistant"},
        "broken": {"type": "nonsense"},
    },
    "pool": {
        "auto": {"color": "green", "max_volume": 110, "hold": 5},
        "music": {"kind": "apps", "match": ["spotify"]},
        "friends": {"kind": "people", "people": ["Alice"], "meter": "homeassistant"},
        "outs": {"channels": ["out"]},
    },
}


def at(show: str, values: dict[str, Any] = VALUES) -> Origin:
    """The origin of a place of `show`."""
    place = origin(values, show)
    assert place is not None
    return place


def test_a_channel_gives_its_options_and_the_rest_comes_from_its_type():
    place = at("out")
    assert place == Origin("out", Source.CHANNEL, "output", VALUES["channel"]["out"], VALUES["behavior"])
    assert (place.prefix, place.unset, place.back) == (
        "As on the channel",
        "Unset: as on the channel.",
        "Unset: as on the channel",
    )
    assert place.parts == "What the parts of `out` do is set on the channel."
    assert inherited(place, "label") == "Speaker"
    assert inherited(place, "color") == "cyan"
    assert inherited(place, "lit_when_idle") == "off"
    # the meter at the point of [behavior]
    assert inherited(place, "meter") == "post_fader"
    assert inherited_part(place, "rec", "led") == "muted"
    assert inherited_part(place, "solo", "led") == "off"
    # Select makes the device the default
    assert inherited_part(place, "select", "press") == "default"


def test_a_label_the_strip_makes_itself_is_not_known():
    place = at("mic")
    assert inherited(place, "label") is None
    assert inherited(place, "meter") == "off"
    assert inherited_part(place, "solo", "led") == "watch: busy -q"
    assert inherited_part(place, "rec", "led") == "recording"


def test_a_custom_channel_and_its_bindings():
    place = at("lamp")
    assert inherited(place, "color") == "homeassistant"
    # its buttons do nothing unless it says so
    assert inherited_part(place, "rec", "led") == "off"


@pytest.mark.parametrize("show", ["-", "nothing", "broken"])
def test_nothing_or_an_unknown_name_has_no_origin(show: str):
    assert origin(VALUES, show) is None


def test_a_pool_gives_its_look_and_the_rest_comes_from_its_type():
    place = at("auto")
    assert place == Origin("auto", Source.POOL, "auto", {"color": "green", "max_volume": 110}, VALUES["behavior"])
    assert (place.prefix, place.unset, place.back) == (
        "As in the pool",
        "Unset: as in `[pool.auto]`.",
        "Unset: as in pool auto",
    )
    assert place.parts == "What the parts of `auto` do is set in the pool."
    assert inherited(place, "color") == "green"
    assert inherited(place, "encoder") == "pick"
    assert inherited(place, "min_volume") == "0 %"
    assert inherited(place, "max_volume") == "110 %"
    assert inherited_part(place, "rec", "led") == "recording"

    apps = at("apps", {})
    # the volume of [behavior], else its default
    assert inherited(apps, "max_volume") == "130 %"
    assert inherited(apps, "meter") == "pre_fader"


def test_pools_of_your_own_and_devices():
    music = at("music")
    assert music.options == {}
    # no pick: applications of a pool of your own act as `apps` channels do
    assert inherited(music, "encoder", pick=False) == "media"
    friends = at("friends")
    assert (friends.strip, inherited(friends, "meter")) == ("voip", "homeassistant")
    devices = at("devices")
    assert inherited(devices, "encoder") == "balance"
    assert inherited_part(devices, "select", "press") == "default"
    assert inherited_part(devices, "select", "led") == "press"


def test_a_pool_of_channels_leaves_it_to_its_channels():
    place = at("outs")
    assert place == Origin("outs", Source.CHANNELS, "apps", {}, VALUES["behavior"])
    assert (place.prefix, place.unset, place.back) == (
        "As on each channel",
        "Unset: as on each channel of `outs`.",
        "Unset: as on each channel",
    )
    assert place.parts.startswith("Each channel of `outs` brings its own look")
    assert inherited(place, "color") is None
    assert inherited_part(place, "rec", "led") is None


def test_a_launch_of_select_on_a_channel():
    place = at("app", {"channel": {"app": {"type": "apps", "launch": ["firefox"]}}})
    assert inherited_part(place, "select", "press") == "launch"
    place = at("app", {"channel": {"app": {"type": "apps", "select": {"press": {"launch": "firefox -P"}}}}})
    assert inherited_part(place, "select", "press") == "launch: firefox -P"


def test_the_help_of_a_place():
    out = at("out")
    assert place_help(out, "rec", 3) == "What the LED of Rec shows while slot 3 shows `out`. Unset: as on the channel."
    assert place_help(out, "color", 3, "cyan") == (
        "The backlight of the LCD while slot 3 shows `out`. Unset: as on the channel: `cyan`."
    )
    devices = at("devices")
    assert place_help(devices, "encoder", 1) == (
        "What the encoder does while slot 1 shows a device of `devices`. Unset: as in `[pool.devices]`."
    )
    assert place_help(devices, "unknown", 1) == "Unset: as in `[pool.devices]`."


def test_values_for_people():
    assert value_text(True) == "on"
    assert value_text({"watch": ["cpu", "--load"]}) == "watch: cpu --load"
    assert program_text({"run": "notify-send hi"}) == "run: notify-send hi"
    assert program_text({}) == "launch: "
