"""
Small controls for values: a switch for booleans, color swatches, toggles for the numbers of strips.
"""

from PyQt6.QtCore import QPointF, QRectF, QSize, QSizeF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPolygonF
from PyQt6.QtWidgets import QAbstractButton, QButtonGroup, QHBoxLayout, QPushButton, QWidget

from xtouch_daemon.gui.domain.schema import Option
from xtouch_daemon.gui.qt.theme.style import current_colors, set_role
from xtouch_daemon.gui.qt.theme.tokens import CONTROL_HEIGHT, LCD_COLORS, LCD_TEXT, LCD_TEXT_OFF, Space


class Switch(QAbstractButton):
    """
    A toggle switch, as tall as a field. Off is an outlined track with a small knob, on a filled one with a large
    knob, so the state shows by shape and position, not only by color.
    """

    TRACK = QSize(40, 24)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # repaints on entering and leaving, for the hover state
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:
        return QSize(self.TRACK.width(), CONTROL_HEIGHT)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        colors = current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.4)
        track = QRectF(QPointF(0, 0), QSizeF(self.TRACK))
        track.moveCenter(QRectF(self.rect()).center())
        radius = track.height() / 2
        on = self.isChecked()
        if on:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors.accent_hover if self.underMouse() else colors.accent))
        else:
            painter.setPen(QPen(QColor(colors.text_muted if self.underMouse() else colors.control_border), 2))
            painter.setBrush(QColor(colors.sunken))
        painter.drawRoundedRect(track.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
        knob = QPointF(track.right() - radius if on else track.left() + radius, track.center().y())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors.on_accent if on else colors.control_border))
        painter.drawEllipse(knob, 8 if on else 6, 8 if on else 6)
        if self.hasFocus():
            # a ring around the knob: it stays inside the widget, which keeps the switch aligned with the fields
            painter.setPen(QPen(QColor(colors.on_accent if on else colors.accent), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(knob, radius - 2, radius - 2)


class Swatch(QAbstractButton):
    """A color of an LCD: a dot of the backlight, ringed and ticked when it is the one."""

    SIZE = 32

    def __init__(self, name: str, parent: QWidget | None = None, meaning: str = ""):
        super().__init__(parent)
        self.name = name
        self.setCheckable(True)
        self.setToolTip(f"{name}: {meaning}" if meaning else name)
        self.setAccessibleName(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFixedSize(self.SIZE, self.SIZE)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        colors = current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QRectF(self.rect()).center()
        if self.isChecked() or self.hasFocus() or self.underMouse():
            ring = colors.accent if self.isChecked() or self.hasFocus() else colors.text_muted
            painter.setPen(QPen(QColor(ring), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 14, 14)
        backlight = QColor(LCD_COLORS[self.name])
        painter.setPen(QPen(QColor(colors.control_border), 1))
        painter.setBrush(backlight)
        painter.drawEllipse(center, 10, 10)
        if self.name == "off":
            # a dark LCD: a slash through it
            painter.setPen(QPen(QColor(LCD_TEXT_OFF), 1.5, cap=Qt.PenCapStyle.RoundCap))
            painter.drawLine(center + QPointF(-5, 5), center + QPointF(5, -5))
        if self.isChecked():
            # a tick as well, for those who can't tell the ring by its color
            tick = LCD_TEXT if backlight.lightnessF() > 0.5 else "#ffffff"
            pen = QPen(QColor(tick), 2, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(
                QPolygonF([center + QPointF(-4.5, 0), center + QPointF(-1.5, 3), center + QPointF(4.5, -3.5)])
            )


class ColorPicker(QWidget):
    """The colors of an LCD as round swatches."""

    picked = pyqtSignal(str, arguments=["color"])

    def __init__(self, option: Option):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Space.XS)
        self.group = QButtonGroup(self)
        self.swatches: dict[str, Swatch] = {}
        for name in option.choices:
            swatch = Swatch(name, self, option.meaning(name))
            self.group.addButton(swatch)
            self.swatches[name] = swatch
            layout.addWidget(swatch)
            swatch.clicked.connect(lambda _=False, name=name: self.picked.emit(name))
        layout.addStretch()

    def show_value(self, name: str) -> None:
        if name in self.swatches:
            self.swatches[name].setChecked(True)
            return
        # a value that is no color: none is checked, the problem says why
        self.group.setExclusive(False)
        for swatch in self.swatches.values():
            swatch.setChecked(False)
        self.group.setExclusive(True)


class NumberToggles(QWidget):
    """Some of the numbers from `minimum` to `maximum`, as buttons that stay pressed (e.g. faders)."""

    changed = pyqtSignal(list, arguments=["numbers"])

    def __init__(self, minimum: int, maximum: int):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.buttons: dict[int, QPushButton] = {}
        for number in range(minimum, maximum + 1):
            button = QPushButton(str(number), self)
            set_role(button, "segment", "variant")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False: self.changed.emit(self.values))
            self.buttons[number] = button
            layout.addWidget(button)
        layout.addStretch()

    @property
    def values(self) -> list[int]:
        return [number for number, button in self.buttons.items() if button.isChecked()]

    def show_values(self, values: list[int]) -> None:
        for number, button in self.buttons.items():
            button.setChecked(number in values)
