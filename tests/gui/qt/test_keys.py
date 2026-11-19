"""
The keys of the menu Edit on the entries of the pages: Del removes, Ctrl+C, Ctrl+X and Ctrl+V copy, cut and paste
them as TOML, Ctrl+D duplicates; in a field they edit its text. Help shows the keys.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QWidget
from pytestqt.qtbot import QtBot

from xtouch_daemon.gui.domain.slot_stacks import rows
from xtouch_daemon.gui.qt.window.main_window import MainWindow

CTRL = Qt.KeyboardModifier.ControlModifier


def clipboard() -> str:
    board = QApplication.clipboard()
    assert board is not None
    return board.text()


def focus(qtbot: QtBot, widget: QWidget) -> None:
    widget.setFocus()
    qtbot.waitUntil(widget.hasFocus)


def shown(window: MainWindow, slot: int) -> list[str]:
    return [row.show for row in rows(window.document.values, slot)]


def test_keys_copy_remove_paste_and_duplicate_a_candidate(qtbot: QtBot, window: MainWindow):
    page = window.slots_page
    stack = page.lists[1]
    focus(qtbot, stack)
    stack.setCurrentRow(0)
    assert all(action.isEnabled() for action in window.entry_actions)

    qtbot.keyClick(stack, Qt.Key.Key_C, CTRL)
    # as in the list of the slot in the file
    assert clipboard() == '"browser if call"'
    qtbot.keyClick(stack, Qt.Key.Key_Delete)
    assert shown(window, 2) == ["auto"]
    qtbot.keyClick(stack, Qt.Key.Key_V, CTRL)
    # after the one picked
    assert shown(window, 2) == ["auto", "browser"]
    assert page.candidate == 1
    qtbot.keyClick(stack, Qt.Key.Key_D, CTRL)
    assert shown(window, 2) == ["auto", "browser", "browser"]
    assert page.candidate == 2
    window.undo()
    assert shown(window, 2) == ["auto", "browser"]


def test_keys_edit_the_text_of_a_field(qtbot: QtBot, window: MainWindow):
    window.show_page("channels")
    page = window.channels_page
    focus(qtbot, page.list)
    qtbot.keyClick(page.list, Qt.Key.Key_C, CTRL)
    assert clipboard().startswith('[channel.out]\ntype = "output"')
    qtbot.keyClick(page.list, Qt.Key.Key_V, CTRL)
    assert page.selection == ("channel", "out_2")

    focus(qtbot, page.id_edit)
    assert not any(action.isEnabled() for action in window.entry_actions)
    qtbot.keyClick(page.id_edit, Qt.Key.Key_Home)
    qtbot.keyClick(page.id_edit, Qt.Key.Key_Delete)
    assert page.id_edit.text() == "ut_2"
    assert "out_2" in window.document.get(("channel",))


def test_keys_cut_duplicate_and_remove_states(qtbot: QtBot, window: MainWindow):
    window.show_page("states")
    page = window.states_page
    focus(qtbot, page.list)
    qtbot.keyClick(page.list, Qt.Key.Key_D, CTRL)
    assert page.selection == "call_2"
    qtbot.keyClick(page.list, Qt.Key.Key_Backspace)
    assert "call_2" not in window.document.get(("state",))
    qtbot.keyClick(page.list, Qt.Key.Key_X, CTRL)
    assert "call" not in window.document.get(("state",), {})
    assert clipboard() == "[state.call]\nvoice_chat = true\n"
    qtbot.keyClick(page.list, Qt.Key.Key_V, CTRL)
    assert page.selection == "call"


def test_help_shows_the_keys(qtbot: QtBot, window: MainWindow):
    window.show_keys()
    texts = [label.text() for popover in window.findChildren(QFrame) for label in popover.findChildren(QLabel)]
    assert "Keyboard shortcuts" in texts
    assert any("F2" in text and "Rename" in text for text in texts)
