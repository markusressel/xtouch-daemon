"""
Copying a strip with Ctrl+C or its menu, and pasting it with Ctrl+V or the menu of another strip, also of another
layout: there the window asks whether to inherit it or copy it.
"""

from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from tests.support.gui import Dialogs
from xtouch_daemon.gui.qt.window.main_window import MainWindow


def test_a_strip_is_copied_and_pasted_with_the_keys(qtbot: QtBot, window: MainWindow, isolated: Dialogs):
    strips = window.preview.strips
    # nothing copied yet, nothing to copy on a place without a strip
    qtbot.keyClick(strips[3], Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(strips[3], Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert len(window.document.strips) == 2
    assert not window.preview.can_paste

    qtbot.keyClick(strips[0], Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert window.status.text().startswith("Copied strip 1 of the layout default.")
    # in the default layout nothing inherits: no question
    qtbot.keyClick(strips[3], Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert isolated.shown == []
    assert [strip.type for strip in window.document.strips] == ["output", "apps", "auto", "output"]
    assert window.document.strips[3].values == window.document.strips[0].values
    assert window.selected == 3
    assert window.current_page == "strip"
    assert window.status.text() == "Strip 4 is a copy of strip 1 of the layout default now. Ctrl+Z undoes it."

    window.undo()
    assert [strip.type for strip in window.document.strips] == ["output", "apps"]


def test_a_strip_of_another_layout_is_inherited_or_copied(layouts: MainWindow, isolated: Dialogs):
    window = layouts
    window.preview.menu_for(1).actions()[3].trigger()  # Copy
    window.edit_layout(0)

    isolated.pick = "Inherit"
    window.preview.menu_for(1).actions()[4].trigger()  # Paste
    assert isolated.shown == ["Paste strip 2 of the layout default at strip 2:"]
    assert window.document.strips[1].values == {"type": "inherit", "layout": "default", "strip": 2}
    assert window.status.text() == "Strip 2 is an inherit strip of strip 2 of the layout default now. Ctrl+Z undoes it."

    isolated.pick = "Copy"
    window.preview.paste.emit(2)
    assert window.document.strips[2].values == window.document.default_strips[1].values

    # cancelled: nothing changes
    isolated.pick = None
    window.preview.paste.emit(0)
    assert window.document.strips[0].values == {"type": "inherit"}
    assert len(isolated.shown) == 3


def test_the_menu_of_a_place_without_a_strip_pastes_too(window: MainWindow):
    configure, paste = window.preview.menu_for(4).actions()
    assert configure.text() == "Configure strip 5"
    assert not paste.isEnabled()
    window.copy_strip(1)
    (_, paste) = window.preview.menu_for(4).actions()
    assert paste.isEnabled()
    paste.trigger()
    assert window.document.strips[4].type == "apps"
