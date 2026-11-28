"""The window in Qt Quick: it loads, its rail shows the pages, the theme changes in place."""

from PyQt6.QtGui import QColor

from tests.support.quick import Ui
from xtouch_daemon.gui.qt.theme.tokens import THEMES, ThemeMode
from xtouch_daemon.gui.quick.engine import theme_of


def test_the_window_shows_the_slots_first(ui: Ui):
    assert ui.app.page == "slots"
    assert ui.shows("page_slots")
    assert not ui.shows("page_channels")


def test_the_rail_shows_another_page(ui: Ui):
    ui.click("rail_states")
    assert ui.app.page == "states"
    assert ui.shows("page_states")
    assert not ui.shows("page_slots")
    assert ui.item("rail_states").property("checked") is True


def test_a_new_theme_changes_the_window_in_place(ui: Ui):
    theme_of(ui.engine).setMode(ThemeMode.LIGHT.value)
    ui.settle()
    assert ui.window.property("color") == QColor(THEMES[ThemeMode.LIGHT].surface)
