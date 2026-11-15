"""
The preview: the 8 strips as they look on the device, laid out like its hardware (encoder, LCD, buttons, meter,
fader). A click selects a strip, dragging a configured strip moves it.
"""

from dataclasses import dataclass, field
from math import cos, radians, sin

from PyQt6.QtCore import QByteArray, QMimeData, QPoint, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QWidget

from xtouch_daemon import protocol
from xtouch_daemon.gui.domain.looks import StripLook
from xtouch_daemon.gui.qt import theme

MIME_TYPE = "application/x-xtouch-daemon-strip"
KIND_NAMES = {"homeassistant": "Home Assistant", "?": "no type"}
WIDTH = 104
HEIGHT = 300

HW = theme.HARDWARE
BUTTONS = (("REC", HW.rec), ("SOLO", HW.solo), ("MUTE", HW.mute), ("SELECT", HW.select))
METER_SEGMENTS = 8
STRIP_RADIUS = 8
PANEL_RADIUS = 14
DIM = 0.19
"""How bright a dimmed backlight is: LCD_TEXT_DIM keeps 6:1 on every color."""
LCD_TEXT_DIM = "#c8ccd2"
KEY_TINT = 0.2
"""How much of its LED color an unlit button shows; its label (LABEL_TINT of the color) keeps 6.3:1 on it."""
LABEL_TINT = 0.25
LED_OFF_TINT = 0.18
UNCONFIGURED_OPACITY = 0.8
"""Strips after the configured ones are drawn fainter: their texts keep 4.6:1 (LCD) to 6.6:1 (printed)."""


@dataclass(frozen=True)
class Face:
    """What a strip shows on the device: what the painting draws."""

    lcd: tuple[str, str]
    color: str
    backlight: float
    """1 lit, 0 dark, in between dimmed."""
    ring: int
    """The lit LEDs of the ring, 0..RING_MAX."""
    fader: float
    """0 at the bottom, 1 at the top."""
    leds: frozenset[str] = field(default_factory=frozenset)
    """The names of the lit buttons."""
    meter: int = 0
    """The lit segments of the meter, 0..METER_SEGMENTS."""


def _mix(color: QColor, base: QColor, amount: float) -> QColor:
    """`amount` of `color` over `base`."""
    return QColor.fromRgbF(
        color.redF() * amount + base.redF() * (1 - amount),
        color.greenF() * amount + base.greenF() * (1 - amount),
        color.blueF() * amount + base.blueF() * (1 - amount),
    )


def _paint_led(painter: QPainter, center: QPointF, radius: float, color: str, lit: bool) -> None:
    """A round LED: lit with a glow around it, or dark with a hint of its color."""
    led = QColor(color)
    if lit:
        glow = QRadialGradient(center, radius * 2.6)
        glow.setColorAt(0, QColor(led.red(), led.green(), led.blue(), 110))
        glow.setColorAt(1, QColor(led.red(), led.green(), led.blue(), 0))
        painter.setBrush(glow)
        painter.drawEllipse(center, radius * 2.6, radius * 2.6)
    painter.setBrush(led if lit else _mix(led, QColor(HW.led_off), LED_OFF_TINT))
    painter.drawEllipse(center, radius, radius)


class StripView(QWidget):
    """One strip of the device."""

    clicked = pyqtSignal(int, arguments=["index"])
    moved = pyqtSignal(int, int, arguments=["source", "target"])
    """A strip was dropped onto this one: (from, to)."""

    def __init__(self, index: int):
        super().__init__()
        self.index = index
        self.look = StripLook("auto", "auto", "", "white", configured=False, problems=0)
        self.selected = False
        self.drop_target = False
        self._press: QPoint | None = None
        self.setFixedSize(WIDTH, HEIGHT)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.lcd_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.lcd_font.setPixelSize(14)
        self.lcd_font.setWeight(QFont.Weight.DemiBold)

    def show_look(self, look: StripLook, selected: bool) -> None:
        self.look = look
        self.selected = selected
        state = "" if look.configured else ", not configured"
        self.setToolTip(f"Strip {self.index + 1}: {look.kind}{state}\n{look.detail}")
        self.setAccessibleName(f"Strip {self.index + 1}")
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(WIDTH, HEIGHT)

    # -- painting -------------------------------------------------------------------------------------------------
    # `_face` decides what the strip shows; the `_paint_*` methods only draw that, the way the device does

    def _face(self) -> Face:
        look = self.look
        lit = look.kind not in ("empty", "?") and look.configured
        if look.color == "off":
            backlight = 0.0
        elif look.kind == "auto" or not look.configured:
            # an auto strip without an application is dark on the device: the preview shows its color dimmed
            backlight = DIM
        else:
            backlight = 1.0
        return Face(
            lcd=(look.label, {"output": "100%", "input": "100%", "apps": "idle"}.get(look.kind, "")),
            color=look.color,
            backlight=backlight,
            ring=8 if lit else 0,
            fader=0.0 if look.kind in ("empty", "?") else 0.7,
        )

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        look = self.look
        face = self._face()
        body = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        self._paint_body(painter, body)
        if not look.configured:
            painter.setOpacity(UNCONFIGURED_OPACITY)
        center = body.center().x()
        self._paint_encoder(painter, QPointF(center, body.top() + 30), face.ring)
        self._paint_lcd(painter, QRectF(body.left() + 6, body.top() + 57, body.width() - 12, 46), face)
        kind = KIND_NAMES.get(look.kind, look.kind).upper()
        self._paint_print(painter, QRectF(body.left(), body.top() + 106, body.width(), 16), kind, look.kind == "?")
        for row, (name, color) in enumerate(BUTTONS):
            rect = QRectF(body.left() + 8, body.top() + 126 + row * 20, 54, 16)
            self._paint_button(painter, rect, name, color, name in face.leds)
        self._paint_meter(painter, QRectF(body.right() - 22, body.top() + 126, 10, 76), face.meter)
        self._paint_fader(painter, QRectF(center - 2.5, body.top() + 214, 5, 68), face.fader)
        painter.setOpacity(1)
        if self.drop_target:
            self._paint_drop(painter, body)
        if look.problems:
            self._paint_badge(painter, QPointF(body.right() - 9, body.top() + 9), str(look.problems))

    def _paint_body(self, painter: QPainter, body: QRectF) -> None:
        """The part of the panel that is this strip, outlined when it is selected, a drop target or not configured."""
        gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
        gradient.setColorAt(0, QColor(HW.strip_top))
        gradient.setColorAt(1, QColor(HW.strip_bottom))
        painter.setBrush(gradient)
        accent = QColor(theme.current_colors().accent)
        if self.selected or self.drop_target:
            # a soft glow around the outline
            glow = QColor(accent)
            for width, alpha in ((6, 40), (4, 80)):
                glow.setAlpha(alpha)
                painter.setPen(QPen(glow, width))
                painter.drawRoundedRect(body, STRIP_RADIUS, STRIP_RADIUS)
            pen = QPen(accent, 2)
        elif not self.look.configured:
            pen = QPen(QColor(HW.print_dim), 1, Qt.PenStyle.DashLine)
        else:
            pen = QPen(QColor(HW.print_dim if self.underMouse() else HW.strip_edge), 1)
        painter.setPen(pen)
        painter.drawRoundedRect(body, STRIP_RADIUS, STRIP_RADIUS)

    def _paint_drop(self, painter: QPainter, body: QRectF) -> None:
        """The accent over the whole strip, while a strip is dragged onto it."""
        accent = QColor(theme.current_colors().accent)
        accent.setAlpha(48)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(body, STRIP_RADIUS, STRIP_RADIUS)

    def _paint_encoder(self, painter: QPainter, center: QPointF, ring: int) -> None:
        """The LED ring (`ring` of its 11 LEDs lit, from the left), the center LED below it, and the knob."""
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(protocol.RING_MAX):
            angle = radians(225 - step * 27)
            point = QPointF(center.x() + 21 * cos(angle), center.y() - 21 * sin(angle))
            _paint_led(painter, point, 2.2, HW.ring, step < ring)
        _paint_led(painter, center + QPointF(0, 20), 1.6, HW.ring, False)
        # the knob: rubber with a ribbed edge, lit from the top left
        shading = QRadialGradient(center + QPointF(-4, -5), 16)
        shading.setColorAt(0, QColor(HW.knob_top))
        shading.setColorAt(1, QColor(HW.knob_bottom))
        painter.setBrush(shading)
        painter.setPen(QPen(QColor(HW.lcd_bezel), 1))
        painter.drawEllipse(center, 13.5, 13.5)
        painter.setPen(QPen(QColor(0, 0, 0, 110), 1))
        for rib in range(24):
            angle = radians(rib * 15)
            direction = QPointF(cos(angle), sin(angle))
            painter.drawLine(center + direction * 11.5, center + direction * 13)
        painter.setPen(QPen(QColor(HW.knob_pointer), 2, cap=Qt.PenCapStyle.RoundCap))
        painter.drawLine(center + QPointF(0, -4), center + QPointF(0, -10))

    def _paint_lcd(self, painter: QPainter, rect: QRectF, face: Face) -> None:
        """The LCD: a black bezel, the backlit glass, and 2 lines of 7 character cells, written from the left."""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(HW.lcd_bezel))
        painter.drawRoundedRect(rect, 4, 4)
        glass = rect.adjusted(3, 3, -3, -3)
        backlight = _mix(QColor(theme.LCD_COLORS[face.color]), QColor(theme.LCD_COLORS["off"]), face.backlight)
        lit = face.backlight == 1.0
        if lit:
            # the light that leaks around the glass
            halo = QColor(backlight)
            halo.setAlpha(60)
            painter.setPen(QPen(halo, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 5, 5)
            painter.setPen(Qt.PenStyle.NoPen)
        gradient = QLinearGradient(glass.topLeft(), glass.bottomLeft())
        gradient.setColorAt(0, backlight.lighter(110))
        gradient.setColorAt(1, backlight.darker(106))
        painter.setBrush(gradient)
        painter.drawRoundedRect(glass, 2, 2)
        cells = glass.adjusted(2, 3, -2, -3)
        width = cells.width() / protocol.LCD_CELL_WIDTH
        height = (cells.height() - 2) / 2
        painter.setBrush(QColor(0, 0, 0, 20) if lit else QColor(255, 255, 255, 8))
        for line in range(2):
            for column in range(protocol.LCD_CELL_WIDTH):
                cell = QRectF(cells.left() + column * width, cells.top() + line * (height + 2), width, height)
                painter.drawRect(cell.adjusted(0.5, 0, -0.5, 0))
        painter.setFont(self.lcd_font)
        painter.setPen(QColor(theme.LCD_TEXT if lit else theme.LCD_TEXT_OFF if face.backlight == 0 else LCD_TEXT_DIM))
        for line, text in enumerate(face.lcd):
            for column, char in enumerate(text[: protocol.LCD_CELL_WIDTH]):
                cell = QRectF(cells.left() + column * width, cells.top() + line * (height + 2), width, height)
                painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, char)

    def _paint_print(self, painter: QPainter, rect: QRectF, text: str, error: bool) -> None:
        """A label printed on the panel, in small capitals; a problem in white on red."""
        font = QFont(self.font())
        font.setPixelSize(10 if len(text) < 10 else 9)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2 if len(text) < 10 else 0.2)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        if error:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(HW.badge))
            width = QFontMetricsF(font).horizontalAdvance(text) + 12
            painter.drawRoundedRect(QRectF(rect.center().x() - width / 2, rect.top(), width, rect.height()), 3, 3)
        painter.setPen(QColor(HW.badge_text if error else HW.print))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_button(self, painter: QPainter, rect: QRectF, name: str, color: str, lit: bool) -> None:
        """A button with its LED: translucent rubber, tinted in its color when off, glowing when on."""
        led = QColor(color)
        if lit:
            glow = QColor(led)
            glow.setAlpha(80)
            painter.setPen(QPen(glow, 4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 3, 3)
        body = led if lit else _mix(led, QColor(HW.key), KEY_TINT)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0, body.lighter(110))
        gradient.setColorAt(1, body.darker(108))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(HW.lcd_bezel), 1))
        painter.drawRoundedRect(rect, 3, 3)
        font = QFont(self.font())
        font.setPixelSize(9)
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        painter.setFont(font)
        painter.setPen(QColor(theme.LCD_TEXT) if lit else _mix(led, QColor(HW.key_print), LABEL_TINT))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, name)

    def _paint_meter(self, painter: QPainter, rect: QRectF, level: int) -> None:
        """The LED meter, `level` of its segments lit from the bottom: green, yellow, and red at the top."""
        painter.setPen(Qt.PenStyle.NoPen)
        height = rect.height() / METER_SEGMENTS
        for segment in range(METER_SEGMENTS):
            color = QColor(HW.meter_high if segment == 0 else HW.meter_mid if segment < 3 else HW.meter_low)
            lit = METER_SEGMENTS - segment <= level
            painter.setBrush(color if lit else _mix(color, QColor(HW.led_off), LED_OFF_TINT))
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top() + segment * height + 1, rect.width(), height - 2), 1.5, 1.5
            )

    def _paint_fader(self, painter: QPainter, slot: QRectF, fraction: float) -> None:
        """The slot with its scale, and the cap at `fraction` (0 at the bottom, 1 at the top)."""
        painter.setPen(QPen(QColor(HW.print_dim), 1))
        for tick in range(11):
            y = slot.top() + 2 + tick * (slot.height() - 4) / 10
            # longer at the top, at 0 dB and at the bottom
            length = 7 if tick in (0, 3, 10) else 4
            painter.drawLine(QPointF(slot.left() - 7 - length, y), QPointF(slot.left() - 7, y))
            painter.drawLine(QPointF(slot.right() + 7, y), QPointF(slot.right() + 7 + length, y))
        painter.setPen(QPen(QColor(HW.strip_edge), 1))
        painter.setBrush(QColor(HW.slot))
        painter.drawRoundedRect(slot, 2.5, 2.5)
        y = slot.bottom() - 4 - fraction * (slot.height() - 8)
        cap = QRectF(slot.center().x() - 17, y - 8, 34, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 130))
        painter.drawRoundedRect(cap.translated(0, 2.5), 3, 3)
        gradient = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        gradient.setColorAt(0, QColor(HW.cap_top))
        gradient.setColorAt(0.5, QColor(HW.cap_top).darker(115))
        gradient.setColorAt(1, QColor(HW.cap_bottom))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(HW.cap_line), 1))
        painter.drawRoundedRect(cap, 3, 3)
        painter.setPen(QPen(QColor(HW.cap_line), 1.5))
        painter.drawLine(QPointF(cap.left() + 3, cap.center().y()), QPointF(cap.right() - 3, cap.center().y()))
        painter.setPen(QPen(QColor(255, 255, 255, 140), 1))
        painter.drawLine(QPointF(cap.left() + 3, cap.top() + 1.5), QPointF(cap.right() - 3, cap.top() + 1.5))

    def _paint_badge(self, painter: QPainter, center: QPointF, text: str) -> None:
        """The number of problems of the strip."""
        painter.setPen(QPen(QColor(HW.panel_bottom), 2))
        painter.setBrush(QColor(HW.badge))
        painter.drawEllipse(center, 9, 9)
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(HW.badge_text))
        painter.drawText(QRectF(center.x() - 9, center.y() - 9, 18, 18), Qt.AlignmentFlag.AlignCenter, text)

    # -- clicks and drag and drop ---------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        assert event is not None
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self.clicked.emit(self.index)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        assert event is not None
        if self._press is None or not self.look.configured:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        mime = QMimeData()
        mime.setData(MIME_TYPE, QByteArray(str(self.index).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(event.position().toPoint())
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        self._press = None

    def source_of(self, mime: QMimeData | None) -> int | None:
        """The strip being dragged onto this one, if it can go here."""
        if mime is None or not mime.hasFormat(MIME_TYPE) or not self.look.configured:
            return None
        source = int(bytes(mime.data(MIME_TYPE).data()).decode())
        return None if source == self.index else source

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        assert event is not None
        if self.source_of(event.mimeData()) is not None:
            self.drop_target = True
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent | None) -> None:
        self.drop_target = False
        self.update()

    def dropEvent(self, event: QDropEvent | None) -> None:
        assert event is not None
        self.drop_target = False
        self.update()
        source = self.source_of(event.mimeData())
        if source is not None:
            event.acceptProposedAction()
            self.moved.emit(source, self.index)


class Preview(QWidget):
    """The 8 strips side by side, on a panel like the device."""

    clicked = pyqtSignal(int, arguments=["index"])
    moved = pyqtSignal(int, int, arguments=["source", "target"])

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        self.strips: list[StripView] = []
        for index in range(protocol.STRIPS):
            view = StripView(index)
            view.clicked.connect(self.clicked)
            view.moved.connect(self.moved)
            layout.addWidget(view)
            self.strips.append(view)

    def show_looks(self, looks: tuple[StripLook, ...], selected: int | None) -> None:
        for view, look in zip(self.strips, looks, strict=True):
            view.show_look(look, view.index == selected)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """The panel of the device: dark, lit from above, with a bevel at the top edge."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(panel.topLeft(), panel.bottomLeft())
        gradient.setColorAt(0, QColor(HW.panel_top))
        gradient.setColorAt(1, QColor(HW.panel_bottom))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(HW.panel_edge), 1))
        painter.drawRoundedRect(panel, PANEL_RADIUS, PANEL_RADIUS)
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        painter.drawLine(
            QPointF(panel.left() + PANEL_RADIUS, panel.top() + 1.5),
            QPointF(panel.right() - PANEL_RADIUS, panel.top() + 1.5),
        )
