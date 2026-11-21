"""
The scenes of the previews of the controls: what the options of a part of a strip do on the device, frame by frame.
"""

from typing import Any

import pytest

from xtouch_daemon.config.bindings import ValueBinding
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.gui.domain.demos import GROUPS, LEVEL, Frame, Strip, group_of, scene
from xtouch_daemon.gui.domain.looks import ring_leds
from xtouch_daemon.hardware import protocol
from xtouch_daemon.strips.knobs import RING_CENTER

BEHAVIOR = BehaviorConfig(max_volume=130, reset_volume=100, unity_at=77)


def strip(strip_type: str = "output", **values: Any) -> Strip:
    return Strip(strip_type, values, BEHAVIOR)


def captions(frames: tuple[Frame, ...]) -> list[str]:
    return [frame.caption for frame in frames]


def test_the_options_are_grouped_by_the_part_of_the_strip():
    assert [group for group, _ in GROUPS] == ["controls", "encoder", "display", "buttons", "fader", "slots"]
    assert group_of("encoder") == "encoder"
    assert group_of("lit_when_idle") == "display"
    assert group_of("rec") == "buttons"
    assert group_of("meter_point") == "fader"
    assert group_of("tags") == "slots"
    # what the strip controls is the rest
    assert group_of("device") == "controls"
    assert group_of("choices") == "controls"


def test_a_volume_encoder_turns_the_volume_and_a_push_resets_it():
    frames = scene("encoder", strip("apps", encoder="volume"))
    assert captions(frames) == [
        "Plays",
        "Turned right: 65 %",
        "Turned right: 70 %",
        "Turned right: 75 %",
        "Pushed: back to 100 %",
    ]
    rings = [frame.state.ring for frame in frames]
    # the ring fills as the volume goes up
    assert rings[:4] == sorted(rings[:4])
    assert {frame.state.ring_mode for frame in frames} == {"wrap"}
    assert frames[1].state.text == ("Label", "65%")


def test_without_encoder_the_default_of_the_type():
    # an output's encoder sets the balance, from the center of the ring
    frames = scene("encoder", strip("output"))
    assert captions(frames)[0] == "Centered"
    assert frames[0].state.ring == RING_CENTER
    assert ring_leds(frames[2].state.ring, frames[2].state.ring_mode) == frozenset(range(RING_CENTER, RING_CENTER + 3))
    assert captions(frames)[-1] == "Pushed: centered"
    assert frames[1].state.text[1] == "R 20%"


@pytest.mark.parametrize(
    ("mode", "first", "last"),
    [
        ("pick", "Turned: application 1 of 4", "Pushed: pinned, it stays after it stopped"),
        ("media", "Turned right: 5 s later in the track (30 s)", "Pushed: paused"),
        ("homeassistant", "Turned: the number in Home Assistant is 40", "Pushed: an event in Home Assistant"),
    ],
)
def test_the_other_encoders(mode: str, first: str, last: str):
    frames = scene("encoder", strip("apps", encoder=mode))
    assert captions(frames)[0] == first
    assert captions(frames)[-1] == last


def test_the_display_goes_dark_without_anything_to_control_unless_lit_when_idle():
    frames = scene("display", strip("apps", label="Browser", color="blue"))
    assert captions(frames) == [
        "Plays: label and volume",
        "Fader moved: the new volume",
        "Muted",
        "Nothing to control: dark",
    ]
    assert frames[0].state.color == "blue"
    assert frames[0].state.text == ("Browser", "60%")
    assert frames[2].state.text == ("Browser", "muted")
    assert frames[-1].state.color == "off"
    assert frames[-1].state.text == ("Browser", "idle")

    lit = scene("display", strip("output", label="Phones", color="cyan", lit_when_idle=True))
    assert lit[-1].caption == "Nothing to control: lit (lit_when_idle)"
    assert lit[-1].state.color == "cyan"
    assert lit[-1].state.text == ("Phones", "off")


def test_the_labels_by_default():
    assert strip("output").label == "Output"
    assert strip("auto").label == "Firefox"
    assert strip("output", label="A very long label").label == "A very "[: protocol.LCD_CELL_WIDTH]
    assert strip("voip", person=["Bob", "bob-phone"]).label == "Bob"
    assert strip("voip").label == "Alice"


def test_people_talk_in_their_color_and_go_dark_when_away():
    frames = scene("display", strip("voip", person=["Bob"], color="white", talking_color="yellow"))
    assert captions(frames) == ["There, quiet", "Talks", "Muted by you", "Away"]
    assert frames[1].state.color == "yellow"
    assert frames[1].state.text == ("Bob", "talks")
    assert frames[3].state.color == "off"


def test_a_home_assistant_display_shows_its_value():
    frames = scene("display", strip("homeassistant", label="Light"))
    assert frames[1].state.text == ("Light", "72%")


def test_each_led_lights_in_the_situations_of_its_indicator():
    frames = scene("buttons", strip("output", device=["speaker"], rec="recording", solo="playing"))
    assert captions(frames) == [
        "Audio plays: Solo",
        "An application records: Rec, Solo",
        "The default device: Select",
        "Muted: Solo, Mute",
        "Nothing plays: all dark",
        # then what the buttons do: Select makes the device the default
        "Select pressed (makes it the default): Solo, Select",
    ]
    # without select, Select stays dark; applications are never the default
    assert scene("buttons", strip("output", device=["speaker"], select=False))[2].caption == (
        "The default device: all dark"
    )
    apps = scene("buttons", strip("apps", rec="default"))
    assert "The default device" not in " ".join(captions(apps))
    assert all(frame.state.leds["rec"] == "off" for frame in apps)


def test_a_button_runs_a_program_of_your_own():
    frames = scene("buttons", strip("output", solo={"press": {"run": "reset now"}}, select={"press": {"run": []}}))
    assert captions(frames)[-1] == "Solo pressed (runs reset): all dark"


BRIGHTNESS = {"set": "sysctrl brightness -b {value}", "min": 0.1, "max": 1.0, "format": "{value:.0%}"}


def test_the_encoder_of_a_custom_channel_sets_the_value_of_its_fader():
    frames = scene("encoder", strip("custom", label="Screen", fader=BRIGHTNESS))
    assert [frame.state.text for frame in frames] == [("Screen", "55%"), ("Screen", "56%"), ("Screen", "57%")]
    assert captions(frames)[0] == "Turned right: 55%, set by sysctrl"
    assert frames[0].state.ring <= frames[2].state.ring
    # one of its own, with its step and push
    own = {**BRIGHTNESS, "step": 0.1, "push": 1.0}
    frames = scene("encoder", strip("custom", label="Screen", fader=BRIGHTNESS, encoder=own))
    assert [frame.state.text[1] for frame in frames] == ["55%", "65%", "75%", "100%"]
    assert captions(frames)[-1] == "Pushed: 100%"
    # nothing to set
    assert captions(scene("encoder", strip("custom"))) == ["Turned: nothing, the encoder is not bound"]
    homeassistant = scene("encoder", strip("custom", encoder="homeassistant"))
    assert captions(homeassistant)[-1] == "Pushed: an event in Home Assistant"


def test_an_audio_encoder_bound_to_a_program_steps_by_the_encoder_step():
    frames = scene("encoder", strip("output", encoder={"set": "light {value}", "format": "{value:.0f}"}))
    assert [frame.state.text[1] for frame in frames] == ["50", "51", "52"]
    # a broken table: the default of the type
    assert captions(scene("encoder", strip("output", encoder={"set": "light"})))[0] == "Centered"


def test_a_fader_bound_to_a_program_shows_its_value():
    frames = scene("fader", strip("custom", label="Screen", fader=BRIGHTNESS, meter={"watch": "cpu-load --watch"}))
    assert captions(frames) == [
        "Bottom: 10%, set by sysctrl; meter: each number cpu-load prints",
        "Middle: 55%, set by sysctrl; meter: each number cpu-load prints",
        "Top: 100%, set by sysctrl; meter: each number cpu-load prints",
    ]
    assert [frame.state.fader for frame in frames] == [0.0, 0.5, 1.0]
    assert {frame.state.meter for frame in frames} == {LEVEL}
    assert captions(scene("fader", strip("custom"))) == ["The fader stays down: it is not bound"]
    assert scene("fader", strip("custom"))[0].state.meter == 0
    # an audio fader too; its meter from Home Assistant
    frames = scene("fader", strip("output", fader={"set": "light {value}"}, meter="homeassistant"))
    assert captions(frames)[0] == "Bottom: 0, set by light; meter: the level Home Assistant sets"


def test_a_bound_meter_of_an_audio_fader_shows_its_level():
    frames = scene("fader", strip("output", meter={"watch": "/usr/bin/cpu-load"}, meter_point="post_fader"))
    assert captions(frames)[0] == "Bottom: 0 %; meter: each number cpu-load prints"
    assert {frame.state.meter for frame in frames} == {LEVEL}
    frames = scene("fader", strip("output", fader="homeassistant", meter="homeassistant"))
    assert (
        captions(frames)[0] == "The fader at 20 %: the number in Home Assistant; meter: the level Home Assistant sets"
    )


def test_the_lcd_of_a_custom_channel_shows_its_value_or_its_lines():
    frames = scene("display", strip("custom", label="Screen", fader=BRIGHTNESS))
    assert [frame.state.text for frame in frames] == [("Screen", "55%"), ("Screen", "75%")]
    assert {frame.state.color for frame in frames} == {"white"}
    frames = scene("display", strip("custom", lcd={"watch": "playerctl status --follow"}, color="homeassistant"))
    assert captions(frames) == ["The second line: each line playerctl prints, lit in the color Home Assistant sets"]
    assert captions(scene("display", strip("custom", color={"watch": "x"}))) == [
        "Shows the label: no value, no lcd, lit in the color x prints"
    ]
    # the targets: the first one's name, the next one after Select
    targets = [{"name": "Left", "value": "DP-1"}, {"name": "Right", "value": "DP-2"}]
    frames = scene("display", strip("custom", fader=BRIGHTNESS, targets=targets))
    assert [frame.state.text[0] for frame in frames] == ["Left", "Left", "Right"]
    assert captions(frames)[-1] == "The next target: Right"
    assert len(scene("display", strip("custom", fader=BRIGHTNESS, targets=targets, together=True))) == 2


def test_the_lcd_of_an_audio_strip_can_be_bound():
    frames = scene("display", strip("output", lcd="homeassistant", color={"watch": "color-of-the-day"}))
    assert captions(frames)[:3] == [
        "Plays: label and volume",
        "The second line: the text Home Assistant sets",
        "Lit in the color color-of-the-day prints",
    ]
    assert frames[1].state.text == ("Output", "HA text")
    assert frames[0].state.color == "white"


def test_the_buttons_of_a_custom_channel_do_nothing_unless_told():
    frames = scene("buttons", strip("custom"))
    assert captions(frames) == ["Nothing pressed: all dark"]
    custom = strip(
        "custom",
        mute={"press": {"run": "mute-the-screen"}, "led": {"watch": "screen-muted --follow"}},
        solo={"led": "homeassistant"},
        rec={"led": {"watch": []}},
    )
    assert captions(scene("buttons", custom)) == [
        "Nothing pressed: all dark",
        "screen-muted prints on: Mute",
        "Home Assistant turns an LED on: Solo",
        "Mute pressed (runs mute-the-screen): all dark",
    ]


def test_the_fader_shows_the_volume_of_its_places():
    frames = scene("fader", strip("output", min_volume=20, max_volume=150))
    assert captions(frames) == [
        "Bottom: 20 %; meter: the level before it",
        "0 dB mark: 100 %; meter: the level before it",
        "Top: 150 %; meter: the level before it",
        "Muted; meter: still the level",
    ]
    assert [frame.state.fader for frame in frames[:3]] == [0.0, 0.77, 1.0]
    # before the fader: the same level wherever it is
    assert {frame.state.meter for frame in frames} == {LEVEL}
    assert frames[0].state.touched


def test_after_the_fader_the_meter_follows_it():
    frames = scene("fader", strip("apps", meter_point="post_fader", max_volume=100))
    assert captions(frames) == ["Bottom: 0 %; meter: follows it", "Top: 100 %; meter: follows it", "Muted; meter: dark"]
    assert [frame.state.meter for frame in frames] == [0, LEVEL, 0]
    assert frames[-1].state.leds["mute"] == "on"


def test_the_meter_point_comes_from_behavior_and_the_meter_may_be_off():
    behavior = BehaviorConfig(meter_point="post_fader")
    assert Strip("output", {}, behavior).meter_point == "post_fader"
    frames = scene("fader", strip("input", meter=False))
    assert frames[0].caption == "Bottom: 0 %; no meter"
    assert {frame.state.meter for frame in frames} == {0}
    # an input goes silent when muted, before the meter
    assert frames[-1].caption == "Muted; meter: dark"


def test_a_fader_for_home_assistant_sets_a_number():
    frames = scene("fader", strip("apps", fader="homeassistant"))
    assert captions(frames)[0] == "The fader at 20 %: the number in Home Assistant"
    assert scene("fader", strip("homeassistant"))[1].state.fader == 0.5


def test_a_fader_bound_to_an_entity_shows_the_range_of_its_domain():
    frames = scene("fader", strip("custom", label="Desk", fader={"entity": "light.desk"}))
    assert captions(frames) == [
        "Bottom: 0, sets light.desk",
        "Middle: 127.5, sets light.desk",
        "Top: 255, sets light.desk",
    ]
    # a range of its own, a format; a meter of an entity
    own = {"entity": "number.amp", "min": 10, "max": 60, "format": "{value:.0f} W"}
    frames = scene("fader", strip("custom", fader=own, meter={"entity": "sensor.power", "max": 500}))
    assert captions(frames)[2] == "Top: 60 W, sets number.amp; meter: sensor.power, from 0 to 500"
    # a domain without a value of its own, by its service: 0 to 100
    service = {"entity": "sensor.x", "service": "script.set", "data": {"v": "{value}"}}
    assert captions(scene("fader", strip("custom", fader=service)))[2] == "Top: 100, sets sensor.x"


def test_an_encoder_bound_to_an_entity_turns_it():
    frames = scene("encoder", strip("custom", encoder={"entity": "media_player.tv", "push": 0.5, "step": 0.05}))
    assert captions(frames)[:2] == [
        "Turned right: 0.5, sets media_player.tv",
        "Turned right: 0.55, sets media_player.tv",
    ]
    assert captions(frames)[-1] == "Pushed: 0.5"
    # an entity is no program: a table of one is not taken for the other
    assert strip("custom", fader={"entity": "light.desk"}).binding("fader", ValueBinding) is None


def test_the_display_and_the_leds_show_entities():
    frames = scene(
        "display",
        strip(
            "custom",
            label="Room",
            lcd={"entity": "climate.room", "attribute": "temperature"},
            color={"entity": "input_select.c"},
        ),
    )
    assert captions(frames)[0] == "The second line: temperature of climate.room, lit in the color input_select.c names"
    assert frames[0].state.text == ("Room", "state")
    lit = scene("buttons", strip("custom", select={"led": {"entity": "light.desk"}}))
    assert captions(lit)[-1] == "light.desk is on: Select"
