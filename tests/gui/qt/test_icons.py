"""
The icons of the theme (`gui/qt/theme/icons.py`).
"""

import qtawesome as qta
from PyQt6.QtWidgets import QApplication, QPushButton

from xtouch_daemon.gui.qt.theme.icons import icon, refresh_icons, set_icon
from xtouch_daemon.gui.qt.theme.style import apply_theme
from xtouch_daemon.gui.qt.theme.tokens import ThemeMode


def test_an_icon_is_drawn_once_per_name_and_color(qapp: QApplication):
    cache = qta._instance().icon_cache  # pyright: ignore[reportPrivateUsage]
    first = icon("plus")
    size = len(cache)

    # the same icon again, and again after a new theme drew all of them: qtawesome keeps one of each
    assert icon("plus").cacheKey() == first.cacheKey()
    button = QPushButton()
    set_icon(button, "plus")
    for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
        apply_theme(mode)
        refresh_icons(button)
    assert len(cache) <= size + 1
    assert icon("plus", "red").cacheKey() != first.cacheKey()
    button.deleteLater()
