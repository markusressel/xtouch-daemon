"""
The design tokens for QML: the singleton `Theme` (`import XTouch`), with the colors of the current theme, the spacing
scale, the radii, the sizes of controls and type, and the durations of the motion. A new theme changes the colors in
place; the bindings of QML follow (and animate where a `Behavior` asks for it).
"""

from typing import Any

from PyQt6.QtCore import QObject, QSettings, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtGui import QColor, QFont, QFontInfo, QGuiApplication

from xtouch_daemon.gui.qt.theme.tokens import (
    CONTROL_HEIGHT,
    HARDWARE,
    LCD_COLORS,
    THEMES,
    TINT_ALPHA,
    Motion,
    Radius,
    Space,
    ThemeColors,
    ThemeMode,
    TypeScale,
)

SETTINGS_KEY = "theme"


def load_mode() -> ThemeMode:
    """The theme chosen last, dark at first (or for a value that is none)."""
    value = QSettings().value(SETTINGS_KEY, ThemeMode.DARK.value)
    return ThemeMode(value) if value in ThemeMode._value2member_map_ else ThemeMode.DARK


def colors_of(colors: ThemeColors) -> dict[str, QColor]:
    return {name: QColor(value) for name, value in vars(colors).items() if name != "qt_theme"}


class Theme(QObject):
    """See the module. QML reads it as `Theme.colors.text`, `Theme.space.m`, `Theme.fade`."""

    modeChanged = pyqtSignal(arguments=[])
    motionChanged = pyqtSignal(arguments=[])

    def __init__(self, mode: ThemeMode | None = None) -> None:
        super().__init__()
        self._mode = load_mode() if mode is None else mode
        self._motion = Motion.enabled
        app = QGuiApplication.instance()
        font = app.font() if isinstance(app, QGuiApplication) else QFont()
        self._font_size = float(QFontInfo(font).pointSizeF()) or 10.0

    # -- the theme ------------------------------------------------------------------------------------------------

    @pyqtProperty(str, notify=modeChanged)
    def mode(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._mode.value

    @pyqtProperty(bool, notify=modeChanged)
    def dark(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._mode == ThemeMode.DARK

    @pyqtSlot(str)
    def setMode(self, mode: str) -> None:
        """Another theme, kept for the next start."""
        new = ThemeMode(mode)
        QSettings().setValue(SETTINGS_KEY, new.value)
        if new != self._mode:
            self._mode = new
            self.modeChanged.emit()

    @pyqtProperty("QVariantMap", notify=modeChanged)
    def colors(self) -> dict[str, QColor]:  # pyright: ignore[reportRedeclaration]
        return colors_of(THEMES[self._mode])

    @pyqtProperty("QVariantMap", constant=True)
    def hardware(self) -> dict[str, QColor]:  # pyright: ignore[reportRedeclaration]
        """The colors of the device, the same in both themes."""
        return {name: QColor(value) for name, value in vars(HARDWARE).items()}

    @pyqtProperty("QVariantMap", constant=True)
    def lcd(self) -> dict[str, QColor]:  # pyright: ignore[reportRedeclaration]
        """The backlights of the LCDs, by their names in the file."""
        return {name: QColor(value) for name, value in LCD_COLORS.items()}

    @pyqtProperty(float, constant=True)
    def tintAlpha(self) -> float:  # pyright: ignore[reportRedeclaration]
        """How strongly a color tints a background (pills, chips), 0..1."""
        return TINT_ALPHA / 255

    # -- sizes ----------------------------------------------------------------------------------------------------

    @pyqtProperty("QVariantMap", constant=True)
    def space(self) -> dict[str, int]:  # pyright: ignore[reportRedeclaration]
        """The spacing scale on a 4 px grid: `xs` 4, `s` 8, `m` 12, `l` 16, `xl` 24, `xxl` 32."""
        return {"xs": Space.XS, "s": Space.S, "m": Space.M, "l": Space.L, "xl": Space.XL, "xxl": Space.XXL}

    @pyqtProperty("QVariantMap", constant=True)
    def radius(self) -> dict[str, int]:  # pyright: ignore[reportRedeclaration]
        """`small` (menu items), `medium` (buttons, fields), `large` (cards), `pill` (chips)."""
        return {"small": Radius.SMALL, "medium": Radius.MEDIUM, "large": Radius.LARGE, "pill": Radius.PILL}

    @pyqtProperty(int, constant=True)
    def controlHeight(self) -> int:  # pyright: ignore[reportRedeclaration]
        """Of buttons, fields and choices, so a row of them lines up."""
        return CONTROL_HEIGHT

    @pyqtProperty("QVariantMap", constant=True)
    def fontSize(self) -> dict[str, float]:  # pyright: ignore[reportRedeclaration]
        """Point sizes relative to the font of the desktop: `body`, `caption`, `section`, `title`."""
        body = self._font_size
        return {
            "body": body,
            "caption": body * TypeScale.CAPTION,
            "section": body * TypeScale.SECTION,
            "title": body * TypeScale.TITLE,
        }

    # -- motion ---------------------------------------------------------------------------------------------------

    @pyqtProperty(bool, notify=motionChanged)
    def motion(self) -> bool:  # pyright: ignore[reportRedeclaration]
        """False: every change happens at once (tests, screenshots); the durations are 0 then."""
        return self._motion

    @motion.setter
    def motion(self, on: bool) -> None:
        if on != self._motion:
            self._motion = on
            self.motionChanged.emit()

    @pyqtProperty(int, notify=motionChanged)
    def fade(self) -> int:  # pyright: ignore[reportRedeclaration]
        """Ms of a change of the look: a color, a text, a page."""
        return Motion.FADE if self._motion else 0

    @pyqtProperty(int, notify=motionChanged)
    def resize(self) -> int:  # pyright: ignore[reportRedeclaration]
        """Ms of something that grows, shrinks or moves: a card, a row that comes or goes."""
        return Motion.RESIZE if self._motion else 0

    def values(self) -> dict[str, Any]:
        """Everything as plain values, for tests."""
        return {"mode": self.mode, "colors": self.colors, "space": self.space, "fade": self.fade}
