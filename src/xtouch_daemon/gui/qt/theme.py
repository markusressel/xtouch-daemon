"""
The look of the GUI, like openhasp-config-manager's: the palette of a qt-themes theme (dark or light, remembered) and
one application stylesheet built from design tokens (colors, spacing, radii, type scale). Widgets set the
`role`/`variant` properties instead of style sheets of their own, and painted widgets take their colors from here.
qt-themes brings its own palette, so the GUI looks the same without a desktop environment's theming.

Every text color is chosen for a contrast of at least 4.5:1 (WCAG 2.2 AA) on the surfaces it is used on, and the
outlines of controls for at least 3:1, in both themes; the comments say which pairs were measured.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import qt_themes
import qtawesome as qta
from PyQt6.QtCore import QSettings, QTemporaryDir
from PyQt6.QtGui import QColor, QIcon, QPalette
from PyQt6.QtWidgets import QApplication, QWidget


class ThemeMode(StrEnum):
    DARK = "dark"
    LIGHT = "light"


# -- spacing, sizes and type: the same in both themes -------------------------------------------------------------


class Space:
    """The spacing scale, on a 4 px grid: margins and gaps use these, so the window lines up."""

    XS = 4
    S = 8
    M = 12
    L = 16
    XL = 24
    XXL = 32


class Radius:
    SMALL = 4
    """Menu items, tool buttons, scroll bars."""
    MEDIUM = 6
    """Buttons and fields."""
    LARGE = 8
    """Cards."""
    PILL = 12
    """Chips: half their height, so they are round at the ends."""


CONTROL_HEIGHT = 32
"""The height of buttons, fields and choices (incl. the border), so a row of them lines up."""


class TypeScale:
    """Font sizes relative to the font of the desktop, so the user's choice of size is kept."""

    CAPTION = 0.9
    TITLE = 1.6
    SECTION = 1.3


# -- colors ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThemeColors:
    """The color tokens of a theme. `surface` is the window, `raised` a card on it, `sunken` a field."""

    qt_theme: str
    surface: str
    raised: str
    sunken: str
    chrome: str
    """The header and the footer."""
    border: str
    """Decorative lines: cards, dividers (no contrast needed)."""
    control_border: str
    """The outline of fields, buttons and switches: 3:1 on surface, raised and sunken."""
    text: str
    text_muted: str
    """Hints and help: 4.5:1 on every surface."""
    placeholder: str
    """Placeholders show the defaults here, so they are text too: 4.5:1 on sunken."""
    accent: str
    accent_hover: str
    on_accent: str
    """Text and icons on an accent background: 4.5:1 on accent and accent_hover."""
    accent_tint: str
    """The background of a selected item (navigation, menu): text keeps 4.5:1 on it."""
    error: str
    warning: str
    success: str
    tone_good: str
    tone_warn: str
    tone_bad: str
    tone_neutral: str
    """The texts of the pills, 4.5:1 on their tinted backgrounds."""


THEMES = {
    # One Dark. text on raised 10.2:1; text_muted 6.5 (raised) / 5.9 (sunken); control_border 3.3 (raised) / 4.0
    # (sunken) / 3.6 (surface); on_accent 8.0 on accent, 9.4 on accent_hover; error 5.2..6.3; placeholder 5.2 on
    # sunken; the pill texts 4.9..6.4 on their tints
    ThemeMode.DARK: ThemeColors(
        qt_theme="one_dark_two",
        surface="#282c34",
        raised="#2e333d",
        sunken="#21252b",
        chrome="#21252b",
        border="#3b414d",
        control_border="#7a8294",
        text="#e6e6e6",
        text_muted="#a9b1bd",
        placeholder="#8f96a3",
        accent="#61afef",
        accent_hover="#7cbdf2",
        on_accent="#0d1117",
        accent_tint="#303e4e",
        error="#ef8891",
        warning="#e5c07b",
        success="#98c379",
        tone_good="#98c379",
        tone_warn="#e5c07b",
        tone_bad="#ef8891",
        tone_neutral="#b1b8c4",
    ),
    # GitHub light. text_muted 5.7 (surface) / 6.1 (white); control_border 3.2 / 3.5; on_accent 5.2 on accent, 5.9
    # on accent_hover; error 5.0, success 4.8, warning 4.6 on surface; the pill texts 4.9..6.5 on their tints
    ThemeMode.LIGHT: ThemeColors(
        qt_theme="github_light",
        surface="#f6f8fa",
        raised="#ffffff",
        sunken="#ffffff",
        chrome="#ffffff",
        border="#d0d7de",
        control_border="#818b98",
        text="#1f2328",
        text_muted="#59636e",
        placeholder="#59636e",
        accent="#0969da",
        accent_hover="#0860ca",
        on_accent="#ffffff",
        accent_tint="#dce8f6",
        error="#cf222e",
        warning="#9a6700",
        success="#1a7f37",
        tone_good="#116329",
        tone_warn="#7d4e00",
        tone_bad="#a40e26",
        tone_neutral="#59636e",
    ),
}

TINT_ALPHA = 30
"""How strongly a color tints a background (pills, chips, the problems button), of 255."""

LCD_COLORS = {
    "off": "#1a1c1f",
    "red": "#ff4d4d",
    "green": "#3ee06a",
    "yellow": "#ffd23f",
    "blue": "#5a86ff",
    "magenta": "#e64dff",
    "cyan": "#3fe0e6",
    "white": "#eef1f4",
}
"""The backlights of the LCDs, as bright as they look on the device; LCD_TEXT keeps 5.6:1 or more on each."""

LCD_TEXT = "#101215"
"""The text on a lit LCD: the device shows dark text on the backlight."""
LCD_TEXT_OFF = "#9aa0a6"
"""The text on a dark LCD: 6.5:1 on "off"."""


@dataclass(frozen=True)
class Hardware:
    """
    The colors of the device, the same in both themes: the preview shows the hardware, which is black. The labels
    printed on it keep 4.5:1 or more on the strip; the LEDs have their real colors.
    """

    panel_top: str = "#1b1e23"
    panel_bottom: str = "#0e1013"
    panel_edge: str = "#30343c"
    strip_top: str = "#22252b"
    strip_bottom: str = "#1a1d22"
    strip_edge: str = "#2f333b"
    print: str = "#c3c8d0"
    """Printed labels (the type of a strip, the buttons): 9.1:1 on the strip."""
    print_dim: str = "#9298a2"
    """Fine print (the scale of the fader): 5.3:1 on the strip."""
    rec: str = "#ff3b3b"
    solo: str = "#ffc928"
    mute: str = "#ff3b3b"
    select: str = "#34d65c"
    ring: str = "#ff9a2e"
    meter_low: str = "#34d65c"
    meter_mid: str = "#ffc928"
    meter_high: str = "#ff3b3b"
    led_off: str = "#30343c"
    key: str = "#2a2d33"
    """An unlit button: its LED color shows only as a tint."""
    key_print: str = "#e2e5e9"
    """The labels on the buttons, tinted in their color."""
    lcd_bezel: str = "#060708"
    knob_top: str = "#4b515b"
    knob_bottom: str = "#1d2025"
    knob_pointer: str = "#e8ebef"
    slot: str = "#050607"
    cap_top: str = "#d5d9df"
    cap_bottom: str = "#80868f"
    cap_line: str = "#1b1d21"
    badge: str = "#c9283a"
    badge_text: str = "#ffffff"
    """On the problems badge: 5.5:1."""


HARDWARE = Hardware()

_SETTINGS_KEY = "theme"
_current_mode = ThemeMode.DARK
_images: QTemporaryDir | None = None
"""The arrows of the stylesheet: it takes images only from files (removed when the program ends)."""


def current_colors() -> ThemeColors:
    return THEMES[_current_mode]


def current_mode() -> ThemeMode:
    return _current_mode


# -- zoom ----------------------------------------------------------------------------------------------------------

ZOOM_LEVELS = (0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
"""The zoom levels of the window, like those of a browser."""
_ZOOM_KEY = "zoom"


def load_zoom() -> float:
    """The zoom level chosen last, 1.0 at first (or for a value that is not one of ZOOM_LEVELS)."""
    value = QSettings().value(_ZOOM_KEY, 1.0)
    try:
        zoom = float(value)  # pyright: ignore[reportArgumentType]
    except TypeError, ValueError:
        return 1.0
    return zoom if zoom in ZOOM_LEVELS else 1.0


def save_zoom(zoom: float) -> None:
    QSettings().setValue(_ZOOM_KEY, zoom)


def zoom_step(zoom: float, steps: int) -> float:
    """The level `steps` levels above (or below) `zoom`, within ZOOM_LEVELS."""
    index = ZOOM_LEVELS.index(zoom) if zoom in ZOOM_LEVELS else ZOOM_LEVELS.index(1.0)
    return ZOOM_LEVELS[max(0, min(len(ZOOM_LEVELS) - 1, index + steps))]


def zoom_text(zoom: float) -> str:
    return f"{round(zoom * 100)} %"


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
    app.setStyleSheet(_stylesheet(colors, app.font().pointSizeF(), _arrows(colors)))


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
QLabel[role="error"] {{ color: {c.error}; }}
QLabel[role="pill"] {{ border-radius: {Radius.PILL - 2}px; padding: 3px {Space.M - 2}px; font-weight: 600; }}
QLabel[role="pill"][tone="good"] {{ background: {tint(c.success)}; color: {c.tone_good}; }}
QLabel[role="pill"][tone="bad"] {{ background: {tint(c.error)}; color: {c.tone_bad}; }}
QLabel[role="pill"][tone="warn"] {{ background: {tint(c.warning)}; color: {c.tone_warn}; }}
QLabel[role="pill"][tone="neutral"] {{ background: {tint(c.tone_neutral)}; color: {c.tone_neutral}; }}
"""
