"""The condition field of the page Slots in Qt Quick: problems, suggestions, highlighting and committing."""

from PyQt6.QtCore import Qt

from tests.gui.quick.slots_helpers import click_row, page, polish
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.pages.slots_condition import offers, partial_of, problem_of, words_of

STATES = frozenset({"call", "gaming"})
TARGETS = frozenset({"browser"})


def test_a_problem_names_the_word_and_what_is_wrong():
    assert problem_of("", STATES, TARGETS, True) is None
    assert problem_of("call and not gaming", STATES, TARGETS, True) is None
    assert problem_of("call and nope", STATES, TARGETS, True) == (9, 4, "There is no state or mode nope.")
    assert problem_of("present(browser)", STATES, TARGETS, True) is None
    assert problem_of("present(nope)", STATES, TARGETS, True) == (8, 4, "There is no channel or pool nope.")
    assert problem_of("present(browser)", STATES, TARGETS, False) == (
        0,
        7,
        "present is only for candidates of slots.",
    )
    start, _, message = problem_of("call and", STATES, TARGETS, True) or (-1, 0, "")
    assert start >= 0
    assert message


def test_words_and_what_is_offered():
    words = words_of(STATES, TARGETS, True)
    assert "present(browser)" in words
    assert "present" not in words_of(STATES, TARGETS, False)
    assert partial_of("call and ga", 11) == "ga"
    assert partial_of("call and ga", 4) == "call"
    assert offers(words, "ga", False) == ["gaming"]
    assert offers(words, "", False) == []
    assert offers(words, "", True) == words
    assert offers(words, "gaming", False) == []
    assert offers(words, "xyz", True) == []


def field(ui: Ui):
    page(ui).pickRow(2, 0)
    polish(ui)
    return ui.item("when_field")


def test_typing_offers_states_and_enter_takes_the_word(ui: Ui):
    ui.app.editor.document.set(("slots", "2"), ["browser if call"])
    ui.app.editor.edited()
    field(ui)
    edit = ui.item("condition_edit")
    ui.focus(edit)
    edit.setProperty("text", "call and ")
    edit.setProperty("cursorPosition", 9)
    ui.type("de")
    polish(ui)
    ui.key(Qt.Key.Key_Return)
    assert edit.property("text") == "call and default"


def test_ctrl_space_offers_everything_and_escape_closes(ui: Ui):
    ui.app.editor.document.set(("slots", "2"), ["browser if call"])
    ui.app.editor.edited()
    field(ui)
    edit = ui.item("condition_edit")
    ui.focus(edit)
    edit.setProperty("text", "")
    polish(ui)
    ui.key(Qt.Key.Key_Escape)
    ui.key(Qt.Key.Key_Escape)
    ui.key(Qt.Key.Key_Return)
    assert edit.property("text") == ""
    ui.key(Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    polish(ui)
    ui.key(Qt.Key.Key_Return)
    assert edit.property("text") == words_of(["call", "default"], ["browser"], True)[0]


def test_enter_commits_the_condition_to_the_file(ui: Ui):
    doc = ui.app.editor.document
    doc.set(("slots", "2"), ["browser if call"])
    ui.app.editor.edited()
    field(ui)
    edit = ui.item("condition_edit")
    ui.focus(edit)
    edit.setProperty("text", "gaming")
    ui.key(Qt.Key.Key_Return)
    assert doc.get(("slots", "2")) == "browser if gaming"
    click_row(ui, 2, 0)
    assert page(ui).inspector["when"] == "gaming"


def test_a_problem_reddens_the_field(ui: Ui):
    ui.app.editor.document.set(("slots", "2"), ["browser if call"])
    ui.app.editor.edited()
    field(ui)
    edit = ui.item("condition_edit")
    ui.focus(edit)
    edit.setProperty("text", "call and nope")
    ui.settle()
    assert ui.item("when_field").property("problem") == "There is no state or mode nope."
