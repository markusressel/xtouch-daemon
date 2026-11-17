"""
The document of a file of channels, states and slots: options by path, the TOML text with its comments, problems
with paths, old files migrated on open, undo.
"""

from pathlib import Path

import pytest

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.domain.history import History
from xtouch_daemon.gui.domain.slots_document import SlotsDocument, path_of, problems_of

TEXT = """# my desk
[channel.out]
type = "output"   # the speakers
label = "Speaker"

[[channel.out.choices]]
label = "Phones"
device = "phones"

[[channel.out.choices]]
label = "Boxes"
device = "boxes"

[state.call]
voice_chat = true

[slots]
1 = "out"                       # always
2 = ["out if call", "auto"]
3 = [{ show = "auto", color = "blue" }]
"""


def document(tmp_path: Path, text: str = TEXT) -> SlotsDocument:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return SlotsDocument.open(path)


def test_options_by_path_and_the_text_keeps_its_comments(tmp_path: Path) -> None:
    doc = document(tmp_path)
    assert doc.get(("channel", "out", "label")) == "Speaker"
    assert doc.get(("slots", "2", 1)) == "auto"
    assert doc.get(("channel", "nope", "label"), "-") == "-"
    assert not doc.modified
    assert doc.render() == TEXT
    doc.set(("channel", "out", "label"), "Boxes")
    doc.set(("slots", "4"), ["out if call", "-"])
    doc.set(("channel", "mic"), {"type": "input", "label": "Mic"})
    doc.set(("state", "gaming", "mode"), True)
    doc.set(("controls", "5"), {"select": "toggle:call"})
    doc.set(("channel", "out", "choices", 1, "label"), "Box")
    assert doc.modified
    text = doc.render()
    assert '# my desk\n[channel.out]\ntype = "output"   # the speakers\nlabel = "Boxes"' in text
    assert '1 = "out"                       # always' in text
    assert '3 = [{ show = "auto", color = "blue" }]' in text
    assert '4 = ["out if call", "-"]' in text
    assert '[channel.mic]\ntype = "input"\nlabel = "Mic"' in text
    assert "[state.gaming]\nmode = true" in text
    assert '5 = {select = "toggle:call"}' in text
    # an array of tables stays one
    assert '[[channel.out.choices]]\nlabel = "Box"' in text
    assert doc.validate().problems == []
    # a new table of an array of tables, a new table in a list
    doc.set(("channel", "out", "choices"), [*doc.get(("channel", "out", "choices")), {"label": "TV", "device": "tv"}])
    doc.set(("slots", "5"), [{"show": "out", "color": "red"}])
    text = doc.render()
    assert '[[channel.out.choices]]\nlabel = "TV"\ndevice = "tv"' in text
    assert '5 = [{show = "out", color = "red"}]' in text


def test_removing_and_renaming(tmp_path: Path) -> None:
    doc = document(tmp_path)
    doc.unset(("state", "call", "voice_chat"))
    # the state is gone with its last option
    assert doc.get(("state",)) is None
    doc.unset(("slots", "2", 0))
    assert doc.get(("slots", "2")) == ["auto"]
    doc.unset(("nothing", "here"))
    doc.unset(("slots", "2", 5))
    doc.unset(("channel", "out", "choices", 1))
    assert len(doc.get(("channel", "out", "choices"))) == 1
    doc.set(("channel", "mic"), {"type": "input"})
    doc.rename(("channel", "out"), "speaker")
    assert list(doc.get(("channel",))) == ["speaker", "mic"]
    text = doc.render()
    assert "[state" not in text
    assert "[channel.speaker]" in text
    assert text.count("[[channel.speaker.choices]]") == 1


def test_problems_have_the_paths_of_their_options(tmp_path: Path) -> None:
    doc = document(tmp_path)
    doc.set(("slots", "2", 0), "nope if call")
    doc.set(("state", "call", "delay_off"), "x")
    validation = doc.validate()
    assert validation.config is None
    # the options of a section are checked first
    assert [problem.path for problem in validation.problems] == [("state", "call", "delay_off")]
    doc.unset(("state", "call", "delay_off"))
    assert doc.validate().at("slots") == [Problem(("slots", "2", 0), "nope is no channel or pool", "invalid")]
    assert path_of("controls.2.select") == ("controls", "2", "select")
    assert path_of("slots.3[0]") == ("slots", "3", 0)
    error = ConfigError("config has errors:\n  slots.3[0] (radio): a problem\n  something else")
    assert problems_of(error) == [
        Problem(("slots", "3", 0), "a problem", "invalid"),
        Problem((), "something else", "invalid"),
    ]
    assert problems_of(ConfigError("config is not valid TOML: x")) == [
        Problem((), "config is not valid TOML: x", "invalid")
    ]
    doc.set(("channel", "a"), {"type": "apps", "label": "A"})
    assert "an apps channel needs match" in [p.message for p in doc.validate().at("channel", "a")]


def test_saving_writes_only_a_valid_file(tmp_path: Path) -> None:
    doc = document(tmp_path)
    doc.set(("slots", "2", 0), "nope")
    with pytest.raises(ConfigError):
        doc.save()
    doc.set(("slots", "2", 0), "out if call")
    config = doc.save()
    assert config.slots.scene.stacks[2][0].show == "out"
    assert not doc.modified
    assert "out if call" in doc.path.read_text()
    doc.set(("slots", "1"), "-")
    doc.revert()
    assert doc.get(("slots", "1")) == "out"


def test_without_a_file_the_example(tmp_path: Path) -> None:
    doc = SlotsDocument.open(tmp_path / "new" / "config.toml")
    assert not doc.exists
    assert doc.get(("channel", "out", "type")) == "output"
    doc.save()
    assert doc.exists
    assert (tmp_path / "new" / "config.toml").exists()


def test_unreadable_files(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="is not valid TOML"):
        document(tmp_path, "[nope")
    with pytest.raises(ConfigError, match="can't read"):
        SlotsDocument.open(tmp_path)


def test_undo(tmp_path: Path) -> None:
    doc = document(tmp_path)
    history = History(doc)
    doc.set(("channel", "out", "label"), "Box")
    history.record()
    doc.set(("channel", "out", "label"), "Boxes")
    history.record()
    doc.set(("slots", "1"), "-")
    history.record()
    history.undo()
    assert doc.get(("slots", "1")) == "out"
    history.undo()
    # typing into one option is one step
    assert doc.get(("channel", "out", "label")) == "Speaker"
    history.redo()
    assert doc.get(("channel", "out", "label")) == "Boxes"
