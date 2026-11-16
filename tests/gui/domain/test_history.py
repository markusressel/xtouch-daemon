from pathlib import Path

from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.domain.history import History, changed_paths

FILE = '[aliases]\n"WEBRTC VoiceEngine" = "Discord"\n\n[[strip]]\ntype = "output"\nlabel = "Speaker"\n'


def document() -> ConfigDocument:
    return ConfigDocument(Path("/nonexistent.toml"), FILE, exists=True)


def test_the_paths_of_a_change():
    assert changed_paths({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 3]}) == {("b", 1)}
    assert changed_paths({"a": 1}, {"b": 1}) == {("a",), ("b",)}
    assert changed_paths([1], [1, 2]) == {()}
    assert changed_paths(("x", "y"), ("x", "z")) == {(1,)}
    assert changed_paths({"a": {"b": 1}}, {"a": {"b": 1}}) == set()


def test_edits_are_undone_and_redone():
    doc = document()
    history = History(doc)
    assert not history.can_undo
    history.record()
    assert not history.can_undo

    doc.set(("strip", 0, "label"), "Spe")
    history.record()
    # typing on: the same step
    doc.set(("strip", 0, "label"), "Speak")
    history.record()
    doc.remove_strip(0)
    history.record()
    # a list that changed its length is a step of its own, also a second time
    doc.add_strip()
    history.record()
    doc.add_strip()
    history.record()

    history.undo()
    history.undo()
    assert len(doc.strips) == 0
    history.undo()
    assert doc.strips[0].values["label"] == "Speak"
    history.undo()
    assert doc.strips[0].values["label"] == "Speaker"
    assert not history.can_undo

    history.redo()
    assert doc.strips[0].values["label"] == "Speak"
    # after an undo or redo the same option is a step of its own
    doc.set(("strip", 0, "label"), "Spea")
    history.record()
    assert not history.can_redo
    history.undo()
    assert doc.strips[0].values["label"] == "Speak"


def test_typing_an_alias_is_one_step():
    doc = document()
    history = History(doc)
    for name in ("B", "Br", "Brave"):
        doc.aliases[0] = (name, "Discord")
        history.record()

    history.undo()

    assert doc.aliases == [("WEBRTC VoiceEngine", "Discord")]


def test_a_new_type_and_the_options_it_keeps_are_one_step():
    doc = document()
    history = History(doc)

    doc.set_strip_type(0, "empty")
    history.record()
    doc.set_strip_type(0, "output")
    history.record()
    assert doc.strips[0].values == {"type": "output", "label": "Speaker"}

    history.undo()
    assert doc.strips[0].values == {"type": "empty"}
    assert doc.strips[0].kept == {"output": {"label": "Speaker"}}
    history.undo()
    assert doc.strips[0].values == {"type": "output", "label": "Speaker"}
    assert doc.strips[0].kept == {}
    history.redo()
    assert doc.strips[0].kept == {"output": {"label": "Speaker"}}
    history.redo()
    assert (doc.strips[0].values, doc.strips[0].kept) == ({"type": "output", "label": "Speaker"}, {})
    assert doc.render() == FILE
