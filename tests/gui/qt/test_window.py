"""
The frame of the main window: its menus, and the window Device, docked or on its own, which it keeps for the next
start.
"""

from collections.abc import Callable

import pytest
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QKeySequence, QResizeEvent
from PyQt6.QtWidgets import QApplication, QScrollArea, QToolBar, QWidget
from pytestqt.qtbot import QtBot

from tests.support.gui import Dialogs, MakeWindow, pick, show_channel
from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.qt.fields.menu import open_menu
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.pages.base import EDGE, Flip
from xtouch_daemon.gui.qt.preview.geometry import BUTTON_TOP, BUTTONS_BOTTOM
from xtouch_daemon.gui.qt.preview.part_view import CROPS
from xtouch_daemon.gui.qt.theme.settings import load_window_state
from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.gui.qt.window.splitter import PaneSplitter


def menu_titles(window: MainWindow) -> list[str]:
    return [action.text() for action in window.menu_bar.actions()]


def test_the_menus_have_what_is_used_now_and_then(window: MainWindow, isolated: Dialogs):
    assert menu_titles(window) == ["&File", "&Edit", "&View", "&Help"]
    # with the keys of what is used often
    assert QKeySequence(QKeySequence.StandardKey.Save) in window.save_action.shortcuts()
    assert QKeySequence(QKeySequence.StandardKey.Undo) in window.undo_action.shortcuts()
    assert not window.save_action.isEnabled()
    assert not window.undo_action.isEnabled()

    window.document.set(("behavior", "encoder_step"), 3)
    window.editor.edited()

    assert window.save_action.isEnabled()
    assert window.revert_action.isEnabled()
    assert window.undo_action.isEnabled()
    window.undo_action.trigger()
    assert not window.document.modified
    assert window.redo_action.isEnabled()
    window.redo_action.trigger()
    assert window.document.modified
    window.revert_action.trigger()
    assert not window.document.modified


def test_the_documentation_opens_in_the_browser(window: MainWindow, monkeypatch: pytest.MonkeyPatch):
    opened: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", opened.append)
    help_menu = window.menu_bar.actions()[-1].menu()
    assert help_menu is not None
    help_menu.actions()[0].trigger()
    assert opened == [QUrl(docs.DOCS_URL)]


def test_quit_closes_the_window(qtbot: QtBot, window: MainWindow):
    # Alt and the letter of the menu open it, in the window
    qtbot.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
    panel = open_menu(window)
    assert panel is not None
    assert panel.menu.title() == "&File"
    pick(qtbot, panel, "Quit")
    assert not window.isVisible()


def test_the_window_device_is_on_every_page(window: MainWindow):
    dock = window.device_dock
    assert dock.widget() is window.device_view
    assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.TopDockWidgetArea
    for page in ("slots", "channels", "settings"):
        window.show_page(page)
        assert window.device_view.isVisible()
    # View, Device closes and opens it
    toggle = dock.toggleViewAction()
    assert toggle is not None
    assert toggle.text() == "&Device"
    toggle.trigger()
    assert not dock.isVisible()
    toggle.trigger()
    assert dock.isVisible()


def test_where_the_window_device_is_stays_for_the_next_start(make_window: MakeWindow, isolated: Dialogs):
    window = make_window()
    assert load_window_state() is None
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, window.device_dock)
    window.close()
    assert load_window_state() is not None

    after = make_window()
    QApplication.processEvents()
    assert after.dockWidgetArea(after.device_dock) == Qt.DockWidgetArea.RightDockWidgetArea


def test_the_bars_stay_where_they_are(window: MainWindow):
    # the header and the footer can't be moved or hidden like the bars of a toolbar
    assert window.contextMenuPolicy() == Qt.ContextMenuPolicy.PreventContextMenu
    for name in ("header", "footer"):
        bar = window.findChild(QToolBar, name)
        assert bar is not None
        assert not bar.isMovable()
        toggle = bar.toggleViewAction()
        assert toggle is not None
        assert not toggle.isVisible()


def test_a_long_hint_over_the_drawing_never_makes_the_window_wider(window: MainWindow):
    # a window manager that tiles gives the window its width: wider content would be cut off on the right
    window.show()
    before = window.minimumSizeHint().width()
    window.device_view.mode_hint.setText("Drag a strip to move its slot · Play: opens the virtual device " * 4)
    assert window.minimumSizeHint().width() == before
    assert before < 600


def test_a_form_wider_than_its_pane_is_laid_out_once(window: MainWindow, monkeypatch: pytest.MonkeyPatch):
    # a narrow window: the rows of the color and the buttons want more than the pane has with their names beside
    window.resize(800, 600)
    resizes: list[str] = []
    for kind in (Flip, OptionRow):
        original = kind.resizeEvent

        def counted(widget: QWidget, event: QResizeEvent | None, original: Callable[..., None] = original) -> None:
            resizes.append(type(widget).__name__)
            # a layout that goes back and forth stops here, rather than never
            if len(resizes) < 2000:
                original(widget, event)

        monkeypatch.setattr(kind, "resizeEvent", counted)
    show_channel(window, "browser")
    show_channel(window, "out")
    # narrower: the form is laid out again (as with a new theme)
    window.resize(780, 600)
    QApplication.processEvents()

    # the area widened its content to the least width of the rows beside their names, at which they asked for it
    # again: the layout went back and forth without end
    assert len(resizes) < 1000
    pane = window.channels_page.splitter.widget(1)
    assert isinstance(pane, QScrollArea)
    content, viewport = pane.widget(), pane.viewport()
    assert content is not None
    assert viewport is not None
    # nothing is cut off on the right
    assert content.width() == viewport.width()


@pytest.mark.parametrize("page", ["slots", "channels", "states"])
def test_the_scroll_bar_of_the_right_pane_sits_at_the_edge_of_the_window(make_window: MakeWindow, page: str):
    window = make_window()
    window.resize(1280, 900)
    window.show_page(page)
    QApplication.processEvents()
    (splitter,) = window.pages[page].findChildren(PaneSplitter)
    pane = splitter.widget(1)
    assert pane is not None
    right = pane.mapToGlobal(pane.rect().topRight()).x()
    configuration = window.stack.mapToGlobal(window.stack.rect().topRight()).x()
    assert right == configuration
    # the rows above the panes keep their distance from the edge
    first = window.pages[page].layout_.itemAt(0)
    assert first is not None
    widget = first.widget()
    if widget is not None and widget is not splitter:
        assert widget.contentsMargins().right() == EDGE


def test_the_drawing_of_a_part_has_round_corners(make_window: MakeWindow):
    window = make_window()
    show_channel(window, "out")
    preview = next(iter(window.channels_page.form_previews["output"].values()))
    corners = preview.drawing.corners
    assert corners.size() == preview.drawing.size()
    image = preview.drawing.grab().toImage()
    # the corner is the card, the middle the strip
    assert image.pixelColor(0, 0).name() == current_colors().raised
    assert image.pixelColor(image.width() // 2, image.height() // 2).name() != current_colors().raised


def test_the_drawing_of_the_buttons_has_room_under_select():
    # the name printed under SELECT, and a margin as above REC: the round edge doesn't cover it
    crop = CROPS["buttons"]
    assert crop.bottom() - BUTTONS_BOTTOM == BUTTON_TOP - crop.top()
