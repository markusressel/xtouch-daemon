from pathlib import Path

import pytest

from tests.conftest import output, source, stream
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.domain.looks import StripLook, look, looks

STATE = AudioState(
    outputs=(output("speaker"), output("buds")),
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
        ({"type": "apps", "match": ["a", "b"], "label": "AB"}, ("apps", "AB", "a, b", "white")),
        ({"type": "apps", "match": []}, ("apps", "", "no applications", "white")),
        ({"type": "auto", "color": "blue"}, ("auto", "auto", "the next application that plays, e.g. Discord", "blue")),
        ({"type": "empty"}, ("empty", "", "a dark strip", "off")),
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
