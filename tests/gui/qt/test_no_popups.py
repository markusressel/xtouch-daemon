"""
Nothing of the window opens a popup window: it would grab the keyboard and the mouse (on X11 the whole display), and
the key of a screenshot tool would do nothing while it is open. `conftest.no_popups` watches every test; this one opens
every menu, drop-down and list of suggestions of the window.
"""

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QMenu, QWidget
from pytestqt.qtbot import QtBot

from tests.gui.qt.conftest import PopupWatch
from xtouch_daemon.gui.qt.fields.choice import Choice
from xtouch_daemon.gui.qt.fields.condition import ConditionEdit
from xtouch_daemon.gui.qt.fields.menu import MenuPanel, show_menu
from xtouch_daemon.gui.qt.fields.names import NameCompleter
from xtouch_daemon.gui.qt.window.main_window import MainWindow


def no_popup_shows() -> None:
    popups = [
        widget
        for widget in QApplication.topLevelWidgets()
        if widget.isVisible() and widget.windowType() == Qt.WindowType.Popup
    ]
    assert popups == []
    assert QApplication.activePopupWidget() is None


def open_all(panel: MenuPanel) -> int:
    """Opens each submenu of an open menu, and theirs; the number of menus opened."""
    opened = 1
    for row in panel.rows:
        if row.submenu is not None and row.enabled:
            panel.hover(row)
            assert panel.child is not None
            no_popup_shows()
            opened += open_all(panel.child)
    return opened


def test_no_menu_drop_down_or_suggestion_of_the_window_is_a_popup(
    qtbot: QtBot, window: MainWindow, no_popups: PopupWatch
) -> None:
    menus = 0
    for page in ("slots", "channels", "states", "settings"):
        window.show_page(page)
        for menu in window.findChildren(QMenu):
            anchor = menu.parentWidget()
            if isinstance(anchor, QMenu):
                continue  # a submenu: opened from its menu
            panel = show_menu(menu, anchor if isinstance(anchor, QWidget) else window)
            assert panel is not None
            no_popup_shows()
            menus += open_all(panel)
            panel.close()
        for choice in window.findChildren(Choice):
            if choice.isVisible():
                choice.showPopup()
                no_popup_shows()
                choice.hidePopup()
        for completer in window.findChildren(NameCompleter):
            completer.refresh()
            no_popup_shows()
            completer.list.close()
        for edit in window.findChildren(ConditionEdit):
            edit._offer(True)  # pyright: ignore[reportPrivateUsage]
            no_popup_shows()
            edit.suggestions.close()
    # the menu bar, the menus Add and Add source, a binding, the problems, with their submenus
    assert menus > 10
    assert no_popups.shown == []


def test_the_watch_sees_a_popup(qtbot: QtBot, no_popups: PopupWatch) -> None:
    menu = QMenu()
    menu.addAction("Entry")
    menu.popup(QPoint(10, 10))
    qtbot.waitUntil(menu.isVisible)
    menu.close()
    assert no_popups.shown == ["QMenu"]
    # seen: the guard of this test passes
    no_popups.shown.clear()
