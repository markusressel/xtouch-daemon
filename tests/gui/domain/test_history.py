from pathlib import Path

from xtouch_daemon.gui.domain.history import History, changed_paths
from xtouch_daemon.gui.domain.slots_document import SlotsDocument

FILE = '[aliases]\n"WEBRTC VoiceEngine" = "Discord"\n\n[channel.out]\ntype = "output"\nlabel = "Speaker"\n'


def document() -> SlotsDocument:
    return SlotsDocument(Path("/nonexistent.toml"), FILE, exists=True)


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

    doc.set(("channel", "out", "label"), "Spe")
    history.record()
    # typing on: the same step
    doc.set(("channel", "out", "label"), "Speak")
    history.record()
    doc.set(("slots", "1"), ["out"])
    history.record()
    # a list that changed its length is a step of its own, also a second time
    doc.set(("slots", "1"), ["out", "auto"])
    history.record()
    doc.set(("slots", "1"), ["out", "auto", "-"])
    history.record()

    history.undo()
    history.undo()
    assert doc.get(("slots", "1")) == ["out"]
    history.undo()
    assert doc.get(("channel", "out", "label")) == "Speak"
    history.undo()
    assert doc.get(("channel", "out", "label")) == "Speaker"
    assert not history.can_undo

    history.redo()
    assert doc.get(("channel", "out", "label")) == "Speak"
    # after an undo or redo the same option is a step of its own
    doc.set(("channel", "out", "label"), "Spea")
    history.record()
    assert not history.can_redo
    history.undo()
    assert doc.get(("channel", "out", "label")) == "Speak"
    history.undo()
    assert doc.render() == FILE


def test_edits_of_several_values_are_steps_of_their_own():
    doc = document()
    history = History(doc)
    for label in ("A", "B"):
        doc.set(("channel", "out", "label"), label)
        doc.set(("aliases", "WEBRTC VoiceEngine"), label)
        history.record()

    history.undo()

    assert doc.get(("channel", "out", "label")) == "A"
