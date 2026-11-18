"""
Material Design icons (qtawesome) that follow the theme.
"""

from pathlib import Path

import qtawesome as qta
from PyQt6.QtGui import QColor, QIcon, QPalette
from PyQt6.QtWidgets import QAbstractButton, QApplication, QWidget

from xtouch_daemon.gui.qt.theme.style import current_colors

_ICON_PROPERTY = "themed_icon"
APP_ICON = Path(__file__).parent / "images" / "icon.svg"
"""
The icon of the project: the device, as four of its strips. The original: the site (`just docs-icon`), the README and
the desktop file of the release (`packaging/build-release.sh`) take it from here.
"""


def app_icon() -> QIcon:
    return QIcon(str(APP_ICON))


def set_icon(button: QAbstractButton, name: str, color: str | None = None) -> None:
    """
    Gives a button an icon (see `icon`) that follows the theme (see `refresh_icons`): `color` is a token of
    `ThemeColors` (e.g. "error"), a fixed color (e.g. "white"), or None for the text color.
    """
    button.setIcon(icon(name, _color(color)))
    button.setProperty(_ICON_PROPERTY, (name, color))


def refresh_icons(root: QWidget) -> None:
    """Draws the icons of the buttons of `root` (see `set_icon`) again, in the colors of the theme applied since."""
    for button in root.findChildren(QAbstractButton):
        spec = button.property(_ICON_PROPERTY)
        if spec is not None:
            name, color = spec
            button.setIcon(icon(name, _color(color)))


def _color(color: str | None) -> str | None:
    return getattr(current_colors(), color, color) if color is not None else None


def icon(name: str, color: str | None = None) -> QIcon:
    """A Material Design icon (qtawesome's mdi6), in the text color unless given."""
    palette = QApplication.palette()
    return qta.icon(
        f"mdi6.{name}",
        color=QColor(color) if color else palette.color(QPalette.ColorRole.WindowText),
        color_disabled=palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText),
    )
