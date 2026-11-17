"""
Applying a theme: the palette and one application stylesheet from the tokens, and the properties widgets are
styled by (`set_role`).
"""

from pathlib import Path

import qt_themes
from PyQt6.QtCore import QSettings, QTemporaryDir
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

from xtouch_daemon.gui.qt.theme.tokens import (
    CONTROL_HEIGHT,
    THEMES,
    TINT_ALPHA,
    Radius,
    Space,
    ThemeColors,
    ThemeMode,
    TypeScale,
)

_SETTINGS_KEY = "theme"
_current_mode = ThemeMode.DARK
_images: QTemporaryDir | None = None
"""The arrows of the stylesheet: it takes images only from files (removed when the program ends)."""


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
    app.setPalette(_palette(app.palette(), colors))
    stylesheet = _stylesheet(colors, app.font().pointSizeF(), _arrows(colors))
    # a style sheet polishes every widget again, which takes a while: not for the same one
    if stylesheet != app.styleSheet():
        app.setStyleSheet(stylesheet)


def _palette(palette: QPalette, colors: ThemeColors) -> QPalette:
    """The palette of the qt-themes theme with the tokens where it falls short, e.g. white text on light blue."""
    roles = QPalette.ColorRole
    for role, color in (
        (roles.Highlight, colors.accent),
        (roles.HighlightedText, colors.on_accent),
        (roles.Link, colors.accent),
        (roles.PlaceholderText, colors.placeholder),
        (roles.ToolTipBase, colors.raised),
        (roles.ToolTipText, colors.text),
    ):
        palette.setColor(role, QColor(color))
    return palette


def set_role(widget: QWidget, value: str | bool, name: str = "role") -> None:
    """
    Sets a property the stylesheet styles by (`role`, `variant`, `problem`, `tone`) and styles the widget again; the
    same value again does nothing, as styling again lays out the window again.
    """
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    assert style is not None
    style.unpolish(widget)
    style.polish(widget)


def tint(color: str, alpha: int = TINT_ALPHA) -> str:
    """A color as a translucent background, for the stylesheet."""
    value = QColor(color)
    return f"rgba({value.red()}, {value.green()}, {value.blue()}, {alpha})"


def _arrows(colors: ThemeColors) -> dict[str, str]:
    """Chevrons for spin boxes and choices, in the muted text color (enabled) and the border color (disabled)."""
    global _images
    if _images is None:
        _images = QTemporaryDir()
    paths = {"up": "M1 5l4-4 4 4", "down": "M1 1l4 4 4-4"}
    result: dict[str, str] = {}
    for direction, path in paths.items():
        for state, color in (("", colors.text_muted), ("-disabled", colors.border)):
            file = Path(_images.path()) / f"{direction}{state}-{color.lstrip('#')}.svg"
            file.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6">'
                f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" '
                'stroke-linejoin="round"/></svg>'
            )
            result[direction + state] = file.as_posix()
    return result


def _stylesheet(c: ThemeColors, font_size: float, arrows: dict[str, str]) -> str:
    def size(scale: float) -> str:
        return f"{font_size * scale:.1f}pt"

    # fields: border, padding and a line of text add up to CONTROL_HEIGHT; a 2 px border (focus, problem) takes its
    # extra pixel from the padding, so nothing moves
    pad = f"{Space.XS + 1}px {Space.S}px"
    pad_thick = f"{Space.XS}px {Space.S - 1}px"
    return f"""
QPushButton {{ background: {c.raised}; color: {c.text}; border: 1px solid {c.control_border};
    border-radius: {Radius.MEDIUM}px; padding: 0 {Space.L - 2}px; min-height: {CONTROL_HEIGHT - 2}px; }}
QPushButton:hover {{ background: {tint(c.text, 18)}; }}
QPushButton:pressed {{ background: {tint(c.text, 34)}; }}
QPushButton:focus {{ border-color: {c.accent}; }}
QPushButton:disabled {{ color: {c.placeholder}; border-color: {c.border}; background: transparent; }}
QPushButton[variant="primary"] {{ background: {c.accent}; color: {c.on_accent}; font-weight: 600;
    border-color: {c.accent}; }}
QPushButton[variant="primary"]:hover {{ background: {c.accent_hover}; border-color: {c.accent_hover}; }}
QPushButton[variant="primary"]:focus {{ border-color: {c.text}; }}
QPushButton[variant="primary"]:disabled {{ background: {c.border}; border-color: {c.border}; color: {c.placeholder};
    font-weight: normal; }}
QPushButton[variant="danger"] {{ color: {c.error}; }}
QPushButton[variant="danger"]:hover {{ background: {tint(c.error)}; border-color: {c.error}; }}
QPushButton[variant="segment"] {{ margin-right: {Space.XS}px; padding: 0 {Space.M}px; }}
QPushButton[variant="segment"]:checked {{ background: {c.accent}; color: {c.on_accent}; border-color: {c.accent};
    font-weight: 600; }}
QPushButton[variant="nav"] {{ text-align: left; padding: 0 {Space.M}px; min-width: {Space.XXL * 3}px;
    border: none; border-left: 3px solid transparent; border-radius: {Radius.MEDIUM}px; background: transparent; }}
QPushButton[variant="nav"]:hover {{ background: {tint(c.text, 18)}; }}
QPushButton[variant="nav"]:checked {{ background: {c.accent_tint}; border-left-color: {c.accent}; font-weight: 600; }}
QToolButton {{ border: 1px solid transparent; border-radius: {Radius.SMALL}px; padding: {Space.XS - 1}px;
    background: transparent; }}
QToolButton:hover {{ background: {tint(c.text, 24)}; }}
QToolButton:pressed, QToolButton:checked {{ background: {tint(c.text, 40)}; }}
QToolButton:focus {{ border-color: {c.accent}; }}
QToolButton::menu-indicator {{ image: none; }}
QToolButton[role="problems"] {{ color: {c.error}; background: {tint(c.error)}; font-weight: 600;
    border-radius: {Radius.MEDIUM}px; padding: {Space.XS + 2}px {Space.M}px; }}
QToolButton[role="problems"]:hover {{ background: {tint(c.error, 2 * TINT_ALPHA)}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {c.sunken}; color: {c.text};
    border: 1px solid {c.control_border}; border-radius: {Radius.MEDIUM}px; padding: {pad};
    selection-background-color: {c.accent}; selection-color: {c.on_accent}; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {c.text_muted}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QLineEdit[problem="true"], QSpinBox[problem="true"], QDoubleSpinBox[problem="true"], QComboBox[problem="true"] {{
    border: 2px solid {c.accent}; padding: {pad_thick}; }}
QLineEdit[problem="true"], QSpinBox[problem="true"], QDoubleSpinBox[problem="true"], QComboBox[problem="true"],
QWidget[role="chips"][problem="true"] {{ border-color: {c.error}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c.placeholder};
    border-color: {c.border}; }}
QSpinBox, QDoubleSpinBox {{ min-width: {Space.XXL * 3}px; padding-right: {Space.XL}px; }}
QAbstractSpinBox QLineEdit {{ border: none; padding: 0; background: transparent; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; width: {Space.XL - 4}px; border: none; border-left: 1px solid {c.border}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right;
    border-top-right-radius: {Radius.MEDIUM}px; margin: 1px 1px 0 0; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right;
    border-bottom-right-radius: {Radius.MEDIUM}px; margin: 0 1px 1px 0; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::down-button:hover {{ background: {tint(c.text, 24)}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({arrows["up"]}); width: 10px; height: 6px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({arrows["down"]}); width: 10px; height: 6px; }}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off,
QDoubleSpinBox::up-arrow:off {{ image: url({arrows["up-disabled"]}); }}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off,
QDoubleSpinBox::down-arrow:off {{ image: url({arrows["down-disabled"]}); }}
QComboBox {{ min-width: {Space.XXL * 5}px; padding-right: {Space.XL}px; }}
QComboBox::drop-down {{ subcontrol-origin: border; subcontrol-position: center right; width: {Space.XL}px;
    border: none; }}
QComboBox::down-arrow {{ image: url({arrows["down"]}); width: 10px; height: 6px; }}
QComboBox::down-arrow:disabled {{ image: url({arrows["down-disabled"]}); }}
QComboBox QAbstractItemView {{ background: {c.raised}; border: 1px solid {c.border}; padding: {Space.XS}px;
    selection-background-color: {c.accent_tint}; selection-color: {c.text}; outline: none; }}
QWidget[role="chips"] {{ background: {c.sunken}; border: 1px solid {c.control_border};
    border-radius: {Radius.MEDIUM}px; }}
QWidget[role="chips"][problem="true"] {{ border-width: 2px; }}
QWidget[role="chips"] QLineEdit {{ border: none; background: transparent; padding: {Space.XS}px 2px; }}
QWidget[role="chip"] {{ background: {tint(c.accent, 2 * TINT_ALPHA)}; border-radius: {Radius.PILL}px; }}
QLabel[role="chip"] {{ padding: 1px {Space.S}px; }}
QWidget[role="chip"][variant="preset"] {{ background: transparent; border: 1px solid {c.accent}; }}

QWidget[role="bar"] {{ background: {c.chrome}; border: 0 solid {c.border}; border-top-width: 1px;
    border-bottom-width: 1px; }}
QFrame[role="card"] {{ background: {c.raised}; border: 1px solid {c.border}; border-radius: {Radius.LARGE}px; }}
QFrame[role="card"] QLabel {{ background: transparent; border: none; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {c.surface}; border: none; }}
QToolTip {{ background: {c.raised}; color: {c.text}; border: 1px solid {c.border}; padding: {Space.XS}px {Space.S}px; }}
QMenu {{ background: {c.raised}; border: 1px solid {c.border}; padding: {Space.XS}px; }}
QMenu::item {{ padding: {Space.S - 2}px {Space.M}px; border-radius: {Radius.SMALL}px; }}
QMenu::item:selected {{ background: {c.accent_tint}; color: {c.text}; }}
QMenu::item:disabled {{ color: {c.text_muted}; }}
QScrollBar:vertical {{ background: transparent; width: {Space.M}px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: {Space.M}px; margin: 0; }}
QScrollBar::handle {{ background: {tint(c.text, 60)}; border-radius: {Radius.SMALL}px; margin: 3px; }}
QScrollBar::handle:hover {{ background: {tint(c.text, 110)}; }}
QScrollBar::handle:vertical {{ min-height: {Space.XXL}px; }}
QScrollBar::handle:horizontal {{ min-width: {Space.XXL}px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QLabel[role="title"] {{ font-size: {size(TypeScale.TITLE)}; font-weight: bold; }}
QLabel[role="section"] {{ font-size: {size(TypeScale.SECTION)}; font-weight: bold; }}
QLabel[role="hint"] {{ color: {c.text_muted}; }}
QLabel[role="help"] {{ color: {c.text_muted}; font-size: {size(TypeScale.CAPTION)}; }}
QLabel[role="meaning"] {{ font-size: {size(TypeScale.CAPTION)}; }}
QLabel[role="error"] {{ color: {c.error}; }}
QLabel[role="pill"] {{ border-radius: {Radius.PILL - 2}px; padding: 3px {Space.M - 2}px; font-weight: 600; }}
QLabel[role="pill"][tone="good"] {{ background: {tint(c.success)}; color: {c.tone_good}; }}
QLabel[role="pill"][tone="bad"] {{ background: {tint(c.error)}; color: {c.tone_bad}; }}
QLabel[role="pill"][tone="warn"] {{ background: {tint(c.warning)}; color: {c.tone_warn}; }}
QLabel[role="pill"][tone="neutral"] {{ background: {tint(c.tone_neutral)}; color: {c.tone_neutral}; }}
"""
