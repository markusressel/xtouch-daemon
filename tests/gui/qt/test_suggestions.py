"""The lists of suggestions under a field, inside the window: names, and the words of a condition."""

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QFocusEvent
from PyQt6.QtWidgets import QApplication, QLineEdit, QListView, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt.fields.condition import ConditionEdit
from xtouch_daemon.gui.qt.fields.names import NameCompleter, completer_of


def a_window[T: QWidget](qtbot: QtBot, field: T) -> tuple[QWidget, T, QLineEdit]:
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(500, 500)
    layout = QVBoxLayout(window)
    layout.addWidget(field, 0, Qt.AlignmentFlag.AlignTop)
    other = QLineEdit()
    layout.addWidget(other)
    window.show()
    qtbot.waitExposed(window)
    return window, field, other


def shown(window: QWidget) -> list[str]:
    """The lines of the list that shows; [] for none."""
    views = [view for view in window.findChildren(QListView) if view.isVisible()]
    if not views:
        return []
    (view,) = views
    model = view.model()
    assert model is not None
    return [str(model.index(row, 0).data()) for row in range(model.rowCount())]


def test_names_are_offered_in_the_window_narrowed_and_picked_with_the_keys(qtbot: QtBot) -> None:
    forgotten: list[str] = []
    names = (
        Suggestion("speaker", "Speaker"),
        Suggestion("buds", "Buds", forget=lambda: forgotten.append("buds")),
        Suggestion("bus", "Bus"),
    )
    window, edit, other = a_window(qtbot, QLineEdit())
    completer = NameCompleter(edit, lambda: names)
    assert completer_of(edit) is completer
    assert completer_of(other) is None
    picked: list[str] = []
    completer.activated.connect(picked.append)
    # a click into the field opens it, under the field, and the field keeps the focus
    qtbot.mouseClick(edit, Qt.MouseButton.LeftButton)
    assert shown(window) == ["speaker", "buds", "bus"]
    assert QApplication.activePopupWidget() is None
    popover = completer.list.popover
    assert popover is not None
    assert popover.y() >= edit.y() + edit.height()
    # typing narrows it
    qtbot.keyClicks(edit, "bu")
    assert shown(window) == ["buds", "bus"]
    # Delete forgets one the daemon remembers; Down, Enter picks
    qtbot.keyClick(edit, Qt.Key.Key_Down)
    qtbot.keyClick(edit, Qt.Key.Key_Delete)
    assert forgotten == ["buds"]
    assert shown(window) == ["bus"]
    assert edit.text() == "bu"
    qtbot.keyClick(edit, Qt.Key.Key_Down)
    qtbot.keyClick(edit, Qt.Key.Key_Return)
    assert picked == ["bus"]
    assert edit.text() == "bus"
    assert shown(window) == []
    # Esc closes it; a click elsewhere too
    qtbot.keyClick(edit, Qt.Key.Key_Backspace)
    assert shown(window)
    qtbot.keyClick(edit, Qt.Key.Key_Escape)
    assert shown(window) == []
    qtbot.mouseClick(edit, Qt.MouseButton.LeftButton)
    assert shown(window)
    qtbot.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(490, 490))
    assert shown(window) == []


def test_a_click_picks_a_name_and_nothing_known_cannot_be_picked(qtbot: QtBot) -> None:
    window, edit, _ = a_window(qtbot, QLineEdit())
    completer = NameCompleter(edit, lambda: (Suggestion("speaker", "Speaker"),))
    picked: list[str] = []
    completer.activated.connect(picked.append)
    qtbot.keyClicks(edit, "x")
    assert shown(window) == ["Nothing known matches 'x'"]
    # nothing to pick: Enter is the field's
    qtbot.keyClick(edit, Qt.Key.Key_Down)
    qtbot.keyClick(edit, Qt.Key.Key_Return)
    assert picked == []
    assert shown(window) == []
    qtbot.keyClick(edit, Qt.Key.Key_Backspace)
    view = completer.list.view
    assert view is not None
    model = view.model()
    assert model is not None
    index = model.index(0, 0)
    view.entered.emit(index)
    assert completer.list.current() == index
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(index).center())  # type: ignore[arg-type]
    assert picked == ["speaker"]
    assert edit.text() == "speaker"


def test_the_list_closes_when_the_field_loses_the_focus(qtbot: QtBot) -> None:
    window, edit, other = a_window(qtbot, QLineEdit())
    NameCompleter(edit, lambda: (Suggestion("speaker", "Speaker"),))
    window.activateWindow()
    edit.setFocus()
    qtbot.mouseClick(edit, Qt.MouseButton.LeftButton)
    assert shown(window) == ["speaker"]
    QApplication.sendEvent(edit, QFocusEvent(QEvent.Type.FocusOut))
    assert shown(window) == []
    assert other is not None


def test_a_condition_offers_the_words_that_start_like_the_one_typed(qtbot: QtBot) -> None:
    window, edit, _ = a_window(qtbot, ConditionEdit())
    edit.set_names(["gaming", "game_night", "call"], ["voip"])
    qtbot.keyClicks(edit, "ga")
    assert shown(window) == ["game_night", "gaming"]
    # the first one is picked: Enter takes it in place of what was typed
    qtbot.keyClick(edit, Qt.Key.Key_Down)
    qtbot.keyClick(edit, Qt.Key.Key_Return)
    assert edit.text() == "gaming"
    assert shown(window) == []
    qtbot.keyClicks(edit, " and pre")
    assert shown(window) == ["present", "present(voip)"]
    qtbot.keyClick(edit, Qt.Key.Key_Tab)
    assert edit.text() == "gaming and present"
    # a whole word: nothing to offer; after it, Ctrl+Space offers them all
    edit.setText("call")
    edit.textEdited.emit("call")
    assert shown(window) == []
    qtbot.keyClick(edit, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert shown(window) == []
    edit.setText("call or ")
    qtbot.keyClick(edit, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert len(shown(window)) == 8
    qtbot.keyClick(edit, Qt.Key.Key_Escape)
    assert shown(window) == []
    qtbot.keyClick(edit, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    # Up stays on the first one, Page Down goes to the last one
    qtbot.keyClick(edit, Qt.Key.Key_Up)
    qtbot.keyClick(edit, Qt.Key.Key_PageDown)
    qtbot.keyClick(edit, Qt.Key.Key_Return)
    assert edit.text() == "call or present(voip)"
