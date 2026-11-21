"""The drop-down list that opens inside its window, without a grab of the keyboard and the mouse."""

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtWidgets import QApplication, QListView, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from xtouch_daemon.gui.qt.fields.choice import ROWS, Choice


def a_choice(qtbot: QtBot, items: list[str]) -> tuple[QWidget, Choice]:
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(400, 600)
    choice = Choice()
    choice.addItems(items)
    QVBoxLayout(window).addWidget(choice, 0, Qt.AlignmentFlag.AlignTop)
    window.show()
    qtbot.waitExposed(window)
    return window, choice


def the_list(window: QWidget) -> QListView:
    (view,) = [view for view in window.findChildren(QListView) if view.isVisible()]
    return view


def test_the_list_opens_inside_the_window_and_a_click_picks(qtbot: QtBot) -> None:
    window, choice = a_choice(qtbot, ["white", "red", "green"])
    picked: list[tuple[int, str]] = []
    choice.activated.connect(lambda row: picked.append((row, choice.itemText(row))))
    choice.showPopup()
    assert QApplication.activePopupWidget() is None
    view = the_list(window)
    assert view.window() is window
    assert view.currentIndex().row() == 0
    model = view.model()
    assert model is not None
    rect = view.visualRect(model.index(2, 0))
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())  # type: ignore[arg-type]
    assert choice.currentText() == "green"
    assert picked == [(2, "green")]
    assert not choice.is_open


def test_esc_or_a_second_click_closes_the_list_without_a_pick(qtbot: QtBot) -> None:
    window, choice = a_choice(qtbot, ["white", "red"])
    choice.showPopup()
    qtbot.keyClick(the_list(window), Qt.Key.Key_Escape)
    assert not choice.is_open
    assert choice.currentText() == "white"
    choice.showPopup()
    choice.showPopup()
    assert not choice.is_open
    qtbot.mouseClick(choice, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    assert choice.is_open
    qtbot.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(390, 590))
    assert not choice.is_open


def test_keys_pick_and_a_long_list_scrolls(qtbot: QtBot) -> None:
    window, choice = a_choice(qtbot, [f"item {number}" for number in range(ROWS + 5)])
    choice.showPopup()
    view = the_list(window)
    assert view.height() < view.sizeHintForRow(0) * (ROWS + 1)
    qtbot.keyClick(view, Qt.Key.Key_Down)
    qtbot.keyClick(view, Qt.Key.Key_Return)
    assert choice.currentText() == "item 1"
    assert not choice.is_open


def test_without_a_window_of_its_own_nothing_opens(qtbot: QtBot) -> None:
    choice = Choice()
    qtbot.addWidget(choice)
    choice.addItems(["white"])
    choice.showPopup()
    assert not choice.is_open


def test_the_row_under_the_mouse_is_marked_and_headings_are_not_picked(qtbot: QtBot) -> None:
    window, choice = a_choice(qtbot, ["Channels", "out", "mic"])
    model = choice.model()
    assert isinstance(model, QStandardItemModel)
    heading = model.item(0)
    assert heading is not None
    heading.setEnabled(False)
    choice.setCurrentIndex(2)
    choice.showPopup()
    view = the_list(window)
    view.entered.emit(model.index(1, 0))
    assert view.currentIndex().row() == 1
    view.entered.emit(model.index(0, 0))
    assert view.currentIndex().row() == 1
    view.clicked.emit(model.index(0, 0))
    assert choice.is_open
    qtbot.keyClick(view, Qt.Key.Key_Return)
    assert choice.currentText() == "out"
