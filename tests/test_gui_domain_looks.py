import dataclasses
from pathlib import Path

import pytest

from tests.conftest import output, source, stream
from xtouch_daemon.audio.model import AudioState, Card, Profile
from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.domain.flow import flow_rows
from xtouch_daemon.gui.domain.looks import (
    FILE_FADER,
    StripLook,
    faces,
    file_state,
    look,
    looks,
    meter_leds,
    ring_leds,
)
from xtouch_daemon.live import Snapshot, StripState

STATE = AudioState(
    outputs=(output("speaker", card="onboard"), output("buds")),
    cards=(Card("onboard", "digital", (Profile("analog", "Analog"), Profile("digital", "Digital Output"))),),
    inputs=(source("mic"),),
    streams=(stream(1, "WEBRTC VoiceEngine", "Discord"), stream(2, "Paused", corked=True)),
    default_output="speaker",
)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"type": "output"}, ("output", "Output", "the default output: speaker description", "white")),
        ({"type": "input", "color": "red"}, ("input", "Input", "the default input", "red")),
        ({"type": "output", "device": "buds"}, ("output", "buds de", "buds description", "white")),
        ({"type": "output", "device": "gone"}, ("output", "Output", "gone (not there now)", "white")),
        ({"type": "output", "device": "buds", "label": "Buds"}, ("output", "Buds", "buds description", "white")),
        # the label of the profile the card is in names the strip
        (
            {
                "type": "output",
                "device": "speaker",
                "label": "Onboard",
                "profiles": [
                    "broken",
                    {"label": "Phones", "profile": "analog"},
                    {"label": "Speaker", "profile": "Digital Output"},
                ],
            },
            ("output", "Speaker", "speaker description", "white"),
        ),
        (
            {"type": "output", "device": "speaker", "label": "Onboard", "profiles": [{"label": "P", "profile": "x"}]},
            ("output", "Onboard", "speaker description", "white"),
        ),
        ({"type": "output", "device": "buds", "profiles": "x"}, ("output", "buds de", "buds description", "white")),
        ({"type": "apps", "match": ["a", "b"], "label": "AB"}, ("apps", "AB", "a, b", "white")),
        ({"type": "apps", "match": []}, ("apps", "", "no applications", "white")),
        ({"type": "auto", "color": "blue"}, ("auto", "auto", "the next application that plays, e.g. Discord", "blue")),
        ({"type": "empty"}, ("empty", "", "a dark strip", "off")),
        (
            {"type": "homeassistant", "id": "desk", "label": "Desk", "color": "green"},
            ("homeassistant", "Desk", "entities of Home Assistant (desk), automations decide what it does", "green"),
        ),
        (
            {"type": "homeassistant"},
            (
                "homeassistant",
                "",
                "entities of Home Assistant (strip_<position>), automations decide what it does",
                "white",
            ),
        ),
        ({"type": "fader"}, ("?", "", "no valid type", "off")),
        ({}, ("?", "", "no valid type", "off")),
        # a color that is none shows the default; the strip shows the problem
        ({"type": "auto", "color": "pink"}, ("auto", "auto", "the next application that plays, e.g. Discord", "white")),
        ({"type": "apps", "label": 3}, ("apps", "", "no applications", "white")),
    ],
)
def test_a_strip_looks_like_on_the_device(values: dict[str, object], expected: tuple[str, str, str, str]):
    assert look(values, STATE, {"WEBRTC VoiceEngine": "Discord"}) == expected


def test_an_auto_strip_without_applications():
    assert look({"type": "auto"}, AudioState(), {})[2] == "the next application that plays"


def test_every_strip_of_the_device_has_a_look(tmp_path: Path):
    doc = ConfigDocument(tmp_path / "c.toml", '[[strip]]\ntype = "output"\n[[strip]]\ntype = "apps"\n', exists=True)

    result = looks(doc, doc.validate(), STATE)

    assert len(result) == 8
    assert result[0] == StripLook("output", "Output", "the default output: speaker description", "white", True, 0)
    # match and label are missing
    assert result[1].problems == 2
    assert result[2:] == (StripLook("auto", "auto", result[2].detail, "white", False, 0),) * 6


def snapshot_of(strips: tuple[StripState, ...]) -> Snapshot:
    return Snapshot("abc", device=True, sound_server=True, mqtt=None, strips=strips)


def test_the_file_shows_a_label_on_its_color():
    state = file_state(StripLook("output", "Buds", "", "green", configured=True, problems=0))
    assert (state.color, state.text, state.ring, state.fader) == ("green", ("Buds", "100%"), 8, FILE_FADER)
    assert set(state.leds.values()) == {"off"}
    dark = file_state(StripLook("empty", "", "", "off", configured=True, problems=0))
    assert (dark.text, dark.ring, dark.fader) == (("", ""), 0, 0.0)


def test_the_preview_is_live_except_for_edited_strips(tmp_path: Path):
    doc = ConfigDocument(tmp_path / "c.toml", '[[strip]]\ntype = "output"\n', exists=True)
    strip_looks = looks(doc, doc.validate(), STATE)
    live = tuple(file_state(strip_look) for strip_look in strip_looks)
    edited = (True,) + (False,) * 7

    result = faces(strip_looks, snapshot_of(live), edited)
    assert [(face.live, face.edited) for face in result[:2]] == [(False, True), (True, False)]
    assert result[1].state is live[1]
    # the device runs the document (the live preview): all of them live, the edited one still marked
    previewed = faces(strip_looks, snapshot_of(live), edited, previewed=True)
    assert [(face.live, face.edited) for face in previewed[:2]] == [(True, True), (True, False)]
    assert previewed[0].state is live[0]
    # without the daemon, from the file; strips that wait for an application are dimmed
    offline = faces(strip_looks, None, (False,) * 8)
    assert not any(face.live for face in offline)
    assert [face.dimmed for face in offline[:2]] == [False, True]


@pytest.mark.parametrize(
    ("position", "mode", "lit"),
    [
        (0, "wrap", set()),
        (3, "dot", {3}),
        (15, "dot", {11}),
        (4, "wrap", {1, 2, 3, 4}),
        (8, "boost_cut", {6, 7, 8}),
        (4, "boost_cut", {4, 5, 6}),
        (1, "spread", {6}),
        (3, "spread", {4, 5, 6, 7, 8}),
        (11, "spread", set(range(1, 12))),
    ],
)
def test_a_ring_lights_like_the_device(position: int, mode: str, lit: set[int]):
    assert ring_leds(position, mode) == lit


def test_a_meter_lights_its_segments():
    assert [meter_leds(level) for level in range(15)] == [0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 7, 8]
    assert (meter_leds(-1), meter_leds(15)) == (0, 8)


@pytest.mark.parametrize(
    ("values", "detail"),
    [
        ({"type": "voip"}, "participants of the voice chat, a strip, the select button pages"),
        ({"type": "voip", "count": 3}, "participants of the voice chat, 3 strips, the select button pages"),
    ],
)
def test_a_voip_strip_shows_the_voice_chat(values: dict[str, object], detail: str):
    assert look(values, STATE, {}) == ("voip", "voip", detail, "white")


def test_an_inherit_strip_looks_like_the_one_of_the_default_layout(tmp_path: Path):
    text = (
        '[[strip]]\ntype = "output"\n'
        '[voip]\nprovider = "demo"\n'
        '[[layout]]\nname = "gaming"\n'
        '[[layout.strip]]\ntype = "inherit"\n'
        '[[layout.strip]]\ntype = "inherit"\n'
        '[[layout.strip]]\ntype = "voip"\ncolor = "cyan"\n'
    )
    doc = ConfigDocument(tmp_path / "c.toml", text, exists=True)
    doc.edit_layout(0)

    result = looks(doc, doc.validate(), STATE)

    assert result[0] == StripLook(
        "output", "Output", "like the default layout: the default output: speaker description", "white", True, 0
    )
    # the default layout has an auto strip there
    assert (result[1].kind, result[1].configured) == ("auto", True)
    assert result[1].detail.startswith("like the default layout: the next application that plays")
    assert (result[2].kind, result[2].color) == ("voip", "cyan")
    assert not result[3].configured


def test_a_strip_that_collapsed_shows_its_file_look_and_the_others_move_up(tmp_path: Path):
    text = '[[strip]]\ntype = "output"\ncollapse = true\n' + '[[strip]]\ntype = "apps"\nmatch = ["a"]\n' * 8
    doc = ConfigDocument(tmp_path / "c.toml", text, exists=True)
    strip_looks = looks(doc, doc.validate(), STATE)
    # every strip of the layout, also the ninth
    assert len(strip_looks) == 9
    live = tuple(file_state(strip_look) for strip_look in strip_looks[1:])
    shown = Snapshot("abc", True, True, None, live, placement=(1, 2, 3, 4, 5, 6, 7, 8))
    strips = [strip.values for strip in doc.strips]

    result = faces(strip_looks[:8], shown, (False,) * 8, rows=flow_rows(strips, shown))
    assert (result[0].live, result[0].dimmed) == (False, True)
    # the second strip is on the first one of the device
    assert result[1].live
    assert result[1].state is live[0]
    # without the placement of the daemon, strip by strip
    old = Snapshot("abc", True, True, None, live, placement=None)
    assert faces(strip_looks[:8], old, (False,) * 8, rows=flow_rows(strips, old))[0].state is live[0]


def test_a_strip_with_choices_looks_like_the_choice_of_the_default_device():
    choices = [{"label": "Phones", "device": "speaker"}, {"label": "Buds", "device": "buds"}]
    kind, label, detail, _ = look({"type": "output", "choices": choices}, STATE, {})
    assert (kind, label, detail) == ("output", "Phones", "Phones or Buds, Select switches")
    # the first one while none of them is the default, and one choice alone
    buds = dataclasses.replace(STATE, default_output="mic")
    assert look({"type": "output", "choices": choices[1:]}, buds, {})[1:3] == ("Buds", "Buds, Select switches")
