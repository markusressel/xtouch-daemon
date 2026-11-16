from pathlib import Path

from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.domain.inherit import layouts, referenced, strips
from xtouch_daemon.gui.domain.sources import Suggestion

TEXT = """
[[strip]]
type = "output"
label = "Out"

[[strip]]
type = "apps"
match = ["brave"]
id = "browser"

[[layout]]
name = "voice"
label = "Voice"

[[layout.strip]]
type = "homeassistant"
id = "lamp"

[[layout.strip]]
type = "inherit"
strip = "browser"

[[layout]]
name = "games"

[[layout.strip]]
type = "inherit"
layout = "voice"
strip = 2

[[layout.strip]]
type = "inherit"

[[layout.strip]]
type = "inherit"
layout = "nope"

[[layout.strip]]
type = "inherit"
strip = 9

[[layout.strip]]
type = "inherit"
strip = "nope"

[[layout.strip]]
type = "inherit"

[[layout.strip]]
type = "inherit"
layout = "games"
strip = 8

[[layout.strip]]
type = "inherit"
layout = "games"
strip = 7
"""


def document(tmp_path: Path) -> ConfigDocument:
    doc = ConfigDocument(tmp_path / "c.toml", TEXT, exists=True)
    doc.edit_layout(1)
    return doc


def test_an_inherit_strip_is_the_strip_it_refers_to(tmp_path: Path) -> None:
    doc = document(tmp_path)
    # through the inherit strip of voice to the browser of the default layout
    found = referenced(doc, 0)
    assert found is not None
    assert (found[0]["match"], found[1]) == (["brave"], "the default layout, strip 2")
    # the same place of the default layout
    assert referenced(doc, 1) == (doc.default_strips[1].values, "the default layout, strip 2")
    # what is not there
    assert [referenced(doc, index) for index in (2, 3, 4)] == [None, None, None]
    # beyond the strips of the default layout, the auto strip there
    assert referenced(doc, 5) == ({"type": "auto"}, "the default layout, strip 6")
    # a loop
    assert referenced(doc, 6) is None
    doc.edit_layout(0)
    assert referenced(doc, 0) is None


def test_the_layouts_and_strips_to_pick_from(tmp_path: Path) -> None:
    doc = document(tmp_path)
    assert layouts(doc) == (
        Suggestion("default", "the top-level strips"),
        Suggestion("voice", "Voice"),
        Suggestion("games", ""),
    )
    assert strips(doc, None) == (
        Suggestion("1", "output Out"),
        Suggestion("2", "apps"),
        Suggestion("browser", "the strip with this id, 2"),
    )
    assert strips(doc, "voice")[0] == Suggestion("1", "homeassistant")
    assert strips(doc, "nope") == ()


def test_a_layout_without_a_name_is_none_to_pick(tmp_path: Path) -> None:
    doc = ConfigDocument(tmp_path / "c.toml", '[[layout]]\nlabel = "New"\n', exists=True)
    assert layouts(doc) == (Suggestion("default", "the top-level strips"),)
