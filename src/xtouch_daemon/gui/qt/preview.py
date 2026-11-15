"""
The preview: the 8 strips as they look on the device, laid out like its hardware (encoder, LCD, buttons, meter,
fader). A click selects a strip, dragging a configured strip moves it.
"""

from math import cos, radians, sin

from PyQt6.QtCore import QByteArray, QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QWidget

from xtouch_daemon import protocol
from xtouch_daemon.gui.domain.looks import StripLook
from xtouch_daemon.gui.qt import theme

MIME_TYPE = "application/x-xtouch-daemon-strip"
KIND_NAMES = {"homeassistant": "Home Assistant", "?": "no type"}
WIDTH = 104
HEIGHT = 300


def _lcd_text_color(color: str) -> QColor:
    # the device shows dark text on a lit backlight; a dark LCD shows dim light text
    return QColor("#9aa0a6") if color == "off" else QColor("#101215")


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
        self.lcd_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.lcd_font.setPixelSize(15)
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

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        look = self.look
        if not look.configured:
            painter.setOpacity(0.55)
        body = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
        gradient.setColorAt(0, QColor("#2a2e36"))
        gradient.setColorAt(1, QColor("#1f2228"))
        painter.setBrush(gradient)
        if self.selected or self.drop_target:
            pen = QPen(QColor(theme.current_colors().accent), 2.5)
        elif look.configured:
            pen = QPen(QColor("#5c6370"), 1)
        else:
            pen = QPen(QColor("#4a505c"), 1.2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(body, 10, 10)
        center = body.center().x()

        self._paint_encoder(painter, QPointF(center, 34))
        self._paint_lcd(painter, QRectF(body.left() + 8, 62, body.width() - 16, 46))
        self._paint_kind(painter, QRectF(body.left(), 110, body.width(), 18))
        self._paint_buttons(painter, body.left() + 10, 134)
        self._paint_meter(painter, QRectF(body.right() - 22, 134, 10, 82))
        self._paint_fader(painter, QRectF(center - 3, 226, 6, 58))
        painter.setOpacity(1)
        if look.problems:
            self._paint_badge(painter, QPointF(body.right() - 8, body.top() + 8), str(look.problems))

    def _paint_encoder(self, painter: QPainter, center: QPointF) -> None:
        # the ring of LEDs around the encoder, and the knob
        painter.setPen(Qt.PenStyle.NoPen)
        lit = self.look.kind not in ("empty", "?") and self.look.configured
        for step in range(11):
            angle = 225 - step * 27
            point = QPointF(center.x() + 19 * cos(radians(angle)), center.y() - 19 * sin(radians(angle)))
            on = lit and step <= 7
            painter.setBrush(QColor("#ff9e3d" if on else "#3a3f49"))
            painter.drawEllipse(point, 1.8, 1.8)
        gradient = QLinearGradient(center - QPointF(0, 13), center + QPointF(0, 13))
        gradient.setColorAt(0, QColor("#4a505b"))
        gradient.setColorAt(1, QColor("#262a31"))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#15171b"), 1))
        painter.drawEllipse(center, 13, 13)
        painter.setPen(QPen(QColor("#c8ccd2"), 2))
        painter.drawLine(center, center + QPointF(0, -9))

    def _paint_lcd(self, painter: QPainter, rect: QRectF) -> None:
        look = self.look
        painter.setPen(QPen(QColor("#0c0d0f"), 2))
        backlight = QColor(theme.LCD_COLORS[look.color])
        if not look.configured or look.kind in ("auto",):
            # an auto strip without an application is dark on the device; the preview shows it dimmed
            backlight = backlight.darker(170)
        painter.setBrush(backlight)
        painter.drawRoundedRect(rect, 4, 4)
        painter.setFont(self.lcd_font)
        painter.setPen(_lcd_text_color(look.color))
        top = QRectF(rect.left(), rect.top() + 3, rect.width(), rect.height() / 2 - 2)
        bottom = QRectF(rect.left(), rect.center().y() + 1, rect.width(), rect.height() / 2 - 4)
        painter.drawText(top, Qt.AlignmentFlag.AlignCenter, look.label[: protocol.LCD_CELL_WIDTH])
        second = {"output": "100%", "input": "100%", "apps": "idle", "auto": ""}.get(look.kind, "")
        painter.drawText(bottom, Qt.AlignmentFlag.AlignCenter, second)

    def _paint_kind(self, painter: QPainter, rect: QRectF) -> None:
        kind = KIND_NAMES.get(self.look.kind, self.look.kind).upper()
        font = QFont(self.font())
        font.setPixelSize(10 if len(kind) < 10 else 9)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2 if len(kind) < 10 else 0)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(theme.current_colors().error if self.look.kind == "?" else "#8b929e"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, kind)

    def _paint_buttons(self, painter: QPainter, left: float, top: float) -> None:
        font = QFont(self.font())
        font.setPixelSize(8)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        for row, (name, color) in enumerate(
            (("REC", "#ff4d4d"), ("SOLO", "#ffd23f"), ("MUTE", "#ff4d4d"), ("SELECT", "#3ee06a"))
        ):
            rect = QRectF(left, top + row * 21, 52, 16)
            painter.setPen(QPen(QColor("#121418"), 1))
            painter.setBrush(QColor("#3a3f48"))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor(color).darker(150))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, name)

    def _paint_meter(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        segments = 8
        height = rect.height() / segments
        for segment in range(segments):
            color = "#ff4d4d" if segment == 0 else "#ffd23f" if segment < 3 else "#3ee06a"
            painter.setBrush(QColor(color).darker(330))
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top() + segment * height + 1, rect.width(), height - 2), 1.5, 1.5
            )

    def _paint_fader(self, painter: QPainter, track: QRectF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0d0e10"))
        painter.drawRoundedRect(track, 3, 3)
        empty = self.look.kind in ("empty", "?")
        position = track.bottom() - 6 if empty else track.top() + track.height() * 0.3
        cap = QRectF(track.center().x() - 16, position - 7, 32, 14)
        gradient = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        gradient.setColorAt(0, QColor("#d9dce1"))
        gradient.setColorAt(1, QColor("#8c929c"))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#202328"), 1))
        painter.drawRoundedRect(cap, 3, 3)
        painter.setPen(QPen(QColor("#202328"), 1.5))
        painter.drawLine(QPointF(cap.left() + 3, cap.center().y()), QPointF(cap.right() - 3, cap.center().y()))

    def _paint_badge(self, painter: QPainter, center: QPointF, text: str) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.current_colors().error))
        painter.drawEllipse(center, 9, 9)
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("white"))
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#2b2f37"), 1))
        painter.setBrush(QColor("#111317"))
        painter.drawRoundedRect(QRect(self.rect()).adjusted(1, 1, -1, -1), 16, 16)
