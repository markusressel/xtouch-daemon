"""
The look of the GUI, like openhasp-config-manager's: the palette of a qt-themes theme (dark or light, remembered) and
one application stylesheet for spacing and the semantic roles. Widgets set the `role`/`variant` properties instead
of style sheets of their own. qt-themes brings its own palette, so the GUI looks the same without a desktop
environment's theming.
"""

from dataclasses import dataclass
from enum import StrEnum

import qt_themes
import qtawesome as qta
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor, QIcon, QPalette
from PyQt6.QtWidgets import QApplication, QWidget


class ThemeMode(StrEnum):
    DARK = "dark"
    LIGHT = "light"


@dataclass(frozen=True)
class ThemeColors:
    qt_theme: str
    error: str
    warning: str
    success: str
    accent: str


THEMES = {
    ThemeMode.DARK: ThemeColors(
        qt_theme="one_dark_two", error="#e27881", warning="#e5c07b", success="#98c379", accent="#61afef"
    ),
    ThemeMode.LIGHT: ThemeColors(
        qt_theme="github_light", error="#cf222e", warning="#9a6700", success="#1a7f37", accent="#0969da"
    ),
}

LCD_COLORS = {
    "off": "#1a1c1f",
    "red": "#ff4d4d",
    "green": "#3ee06a",
    "yellow": "#ffd23f",
    "blue": "#4d7cff",
    "magenta": "#e64dff",
    "cyan": "#3fe0e6",
    "white": "#eef1f4",
}
"""The backlights of the LCDs, as bright as they look on the device."""

_SETTINGS_KEY = "theme"
_current_mode = ThemeMode.DARK


def current_colors() -> ThemeColors:
    return THEMES[_current_mode]


def current_mode() -> ThemeMode:
    return _current_mode


def load_theme_mode() -> ThemeMode:
    value = QSettings().value(_SETTINGS_KEY, ThemeMode.DARK.value)
    return ThemeMode(value) if value in ThemeMode._value2member_map_ else ThemeMode.DARK


def apply_theme(mode: ThemeMode) -> None:
    global _current_mode
    _current_mode = mode
    QSettings().setValue(_SETTINGS_KEY, mode.value)
    colors = THEMES[mode]
    qt_themes.set_theme(colors.qt_theme)
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    app.setStyleSheet(_stylesheet(app.palette(), colors))


def icon(name: str, color: str | None = None) -> QIcon:
    """A Material Design icon (qtawesome's mdi6), in the text color unless given."""
    palette = QApplication.palette()
    return qta.icon(
        f"mdi6.{name}",
        color=QColor(color) if color else palette.color(QPalette.ColorRole.WindowText),
        color_disabled=palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText),
    )


def set_role(widget: QWidget, value: str | bool, name: str = "role") -> None:
    """Sets a property the stylesheet styles by (`role`, `variant`, `problem`, `tone`) and styles the widget again."""
    widget.setProperty(name, value)
    style = widget.style()
    assert style is not None
    style.unpolish(widget)
    style.polish(widget)


def _rgba(color: QColor, alpha: int) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


def _stylesheet(palette: QPalette, colors: ThemeColors) -> str:
    text = palette.color(QPalette.ColorRole.WindowText)
    window = palette.color(QPalette.ColorRole.Window)
    base = palette.color(QPalette.ColorRole.Base)
    accent = QColor(colors.accent)
    return f"""
QPushButton {{ padding: 6px 14px; }}
QPushButton[variant="primary"] {{ background: {colors.accent}; color: white; font-weight: bold; border: none;
    border-radius: 6px; padding: 7px 16px; }}
QPushButton[variant="primary"]:disabled {{ background: {_rgba(accent, 60)}; color: {_rgba(text, 110)}; }}
QPushButton[variant="danger"] {{ color: {colors.error}; }}
QPushButton[variant="segment"]:checked {{ background: {colors.accent}; color: white; border-color: {colors.accent}; }}
QPushButton[variant="nav"] {{ text-align: left; padding: 8px 14px; border: none; background: transparent;
    border-radius: 6px; }}
QPushButton[variant="nav"]:hover {{ background: {_rgba(text, 20)}; }}
QPushButton[variant="nav"]:checked {{ background: {_rgba(text, 30)}; font-weight: bold; }}
QToolButton[variant="flat"] {{ border: none; background: transparent; padding: 3px; border-radius: 4px; }}
QToolButton[variant="flat"]:hover {{ background: {_rgba(text, 30)}; }}
QToolButton::menu-indicator {{ image: none; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ padding: 4px 6px; }}
QLineEdit[problem="true"], QSpinBox[problem="true"], QDoubleSpinBox[problem="true"], QComboBox[problem="true"],
QWidget[role="chips"][problem="true"] {{ border: 1px solid {colors.error}; }}
QWidget[role="bar"] {{ background: {_rgba(text, 10)}; }}
QWidget[role="chips"] {{ background: {base.name()}; border: 1px solid {_rgba(text, 50)}; border-radius: 4px; }}
QWidget[role="chip"] {{ background: {_rgba(text, 25)}; border-radius: 11px; }}
QWidget[role="chips"] QLineEdit {{ border: none; background: transparent; }}
QFrame[role="card"] {{ background: {_rgba(text, 8)}; border: 1px solid {_rgba(text, 35)}; border-radius: 10px; }}
QFrame[role="card"] QLabel {{ background: transparent; border: none; }}
QLabel[role="title"] {{ font-size: 15pt; font-weight: bold; }}
QLabel[role="section"] {{ font-size: 12pt; font-weight: bold; }}
QLabel[role="hint"] {{ color: {_rgba(text, 160)}; }}
QLabel[role="help"] {{ color: {_rgba(text, 150)}; font-size: 9pt; }}
QLabel[role="error"] {{ color: {colors.error}; }}
QLabel[role="pill"] {{ border-radius: 10px; padding: 2px 10px; font-weight: bold; }}
QLabel[role="pill"][tone="good"] {{ background: {_rgba(QColor(colors.success), 45)}; color: {colors.success}; }}
QLabel[role="pill"][tone="bad"] {{ background: {_rgba(QColor(colors.error), 45)}; color: {colors.error}; }}
QLabel[role="pill"][tone="warn"] {{ background: {_rgba(QColor(colors.warning), 45)}; color: {colors.warning}; }}
QLabel[role="pill"][tone="neutral"] {{ background: {_rgba(text, 25)}; color: {_rgba(text, 190)}; }}
QToolButton[role="problems"] {{ color: {colors.error}; font-weight: bold; padding: 4px 10px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {window.name()}; border: none; }}
"""
