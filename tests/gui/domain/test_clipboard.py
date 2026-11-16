"""
Copying a strip and pasting it at another place, also of another layout: as a copy or as an `inherit` strip.
"""

import tomllib
from pathlib import Path

from xtouch_daemon.gui.domain.clipboard import CopiedStrip, Paste
from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.domain.drafts import StripDraft

FILE = """\
[[strip]]
type = "output"
device = "alsa_output.analog"
label = "Speaker"

[[strip]]
type = "apps"
match = ["brave"]
label = "Browser"

[[layout]]
name = "gaming"

[[layout.strip]]
type = "voip"
"""


def document() -> ConfigDocument:
    return ConfigDocument(Path("/nonexistent/config.toml"), FILE, exists=True)


def test_a_copy_has_all_the_options_and_goes_its_own_way():
    doc = document()
    copied = doc.copy_strip(0)
    doc.paste_strip(1, copied, Paste.COPY)
    doc.set(("strip", 0, "label"), "Main")
    assert [strip.values for strip in doc.strips] == [
        {"type": "output", "device": "alsa_output.analog", "label": "Main"},
        {"type": "output", "device": "alsa_output.analog", "label": "Speaker"},
    ]
    # also when the copied one changes before it is pasted
    doc.paste_strip(0, copied, Paste.COPY)
    assert doc.strips[0].values["label"] == "Speaker"
    assert doc.validate().problems == []


def test_a_strip_of_one_layout_goes_to_another_one_as_an_inherit_strip():
    doc = document()
    copied = doc.copy_strip(1)
    doc.edit_layout(0)
    # after the last strip: the places in between are auto strips
    doc.paste_strip(3, copied, Paste.INHERIT)
    assert [strip.values for strip in doc.strips] == [
        {"type": "voip"},
        {"type": "auto"},
        {"type": "auto"},
        {"type": "inherit", "layout": "default", "strip": 2},
    ]
    assert doc.validate().problems == []
    assert tomllib.loads(doc.render())["layout"][0]["strip"][3] == {"type": "inherit", "layout": "default", "strip": 2}


def test_only_strips_of_a_layout_inherit_and_not_from_themselves():
    copied = CopiedStrip("gaming", 2, {"type": "voip"}, {})
    assert str(copied) == "strip 3 of the layout gaming"
    assert not copied.can_inherit("default", 0)
    assert not copied.can_inherit("gaming", 2)
    assert copied.can_inherit("gaming", 1)
    assert copied.can_inherit("music", 2)


def test_the_options_kept_of_other_types_come_along():
    kept = {"apps": {"match": ["brave"]}}
    copied = CopiedStrip.of("default", 0, StripDraft({"type": "output"}, origin=0, kept=kept))
    draft = copied.draft(Paste.COPY)
    assert draft == StripDraft({"type": "output"}, kept=kept)
    assert draft.kept is not kept
