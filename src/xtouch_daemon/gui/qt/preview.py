"""
The preview: the 8 strips laid out like the hardware (encoder with its ring, LCD, buttons with LEDs, meter, fader),
showing what the device shows right now while the daemon runs, or what the file would show. It is also how a strip
is picked: a click (or the arrow keys) selects a strip, dragging a configured strip (or Ctrl+arrow) moves it, and the
context menu has the rest.
"""

from dataclasses import dataclass
from math import cos, radians, sin

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSizeF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QContextMenuEvent,
    QFocusEvent,
    QFont,
    QFontDatabase,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QMenu, QWidget

from xtouch_daemon import protocol
from xtouch_daemon.gui.domain.looks import StripFace, StripLook, faces, meter_segments, ring_leds
from xtouch_daemon.gui.qt import theme

KIND_NAMES = {"homeassistant": "Home Assistant", "?": "no type"}
WIDTH = 104
HEIGHT = 300
SPACING = 6
MARGIN_X = 14
MARGIN_Y = 12
METER_SEGMENTS = 8
ANIMATION_MS = 160
"""How long the other strips take to make room for a dragged one: quick, but long enough to see where they go."""
BLINK_MS = 400
"""How fast a flashing LED blinks."""
LED_COLORS = {"rec": "#ff4d4d", "solo": "#ffd23f", "mute": "#ff4d4d", "select": "#3ee06a"}
LIFT = 8
"""How far a dragged strip is lifted out of the row."""
LIFTED_OPACITY = 0.8


def slot_position(index: int) -> QPoint:
    """Where the strip at `index` sits in the preview."""
    return QPoint(MARGIN_X + index * (WIDTH + SPACING), MARGIN_Y)


def _lcd_text_color(color: str) -> QColor:
    # the device shows dark text on a lit backlight; a dark LCD shows dim light text
    return QColor("#9aa0a6") if color == "off" else QColor("#101215")


@dataclass
class _Drag:
    source: int
    target: int
    grab: int
    """Where the strip was grabbed, from its left edge."""


class Preview(QWidget):
    """The 8 strips side by side, on a panel like the device."""

    clicked = pyqtSignal(int, arguments=["index"])
    moved = pyqtSignal(int, int, arguments=["source", "target"])
    """A strip was moved (dragged, Ctrl+arrow, or with the menu): from, to."""
    configure = pyqtSignal(int, arguments=["index"])
    """A strip that is not configured should be."""
    remove = pyqtSignal(int, arguments=["index"])

    def __init__(self):
        super().__init__()
        width = 2 * MARGIN_X + protocol.STRIPS * WIDTH + (protocol.STRIPS - 1) * SPACING
        self.setFixedSize(width, 2 * MARGIN_Y + HEIGHT)
        self.strips: list[StripView] = []
        for index in range(protocol.STRIPS):
            view = StripView(self, index)
            view.move(slot_position(index))
            self.strips.append(view)
        self._drag: _Drag | None = None
        self.animations: dict[int, QPropertyAnimation] = {}
        """The glides of the strips making room for a dragged one, by strip."""
        self.blink = True
        """Whether flashing LEDs are lit right now."""
        self.blinker = QTimer(self)
        self.blinker.setInterval(BLINK_MS)
        self.blinker.timeout.connect(self._blink)

    @property
    def configured(self) -> int:
        """How many strips are configured: only those move, and only among each other."""
        return sum(view.look.configured for view in self.strips)

    @property
    def dragging(self) -> bool:
        return self._drag is not None

    @property
    def drop_target(self) -> int | None:
        """Where the dragged strip goes when it is let go."""
        return None if self._drag is None else self._drag.target

    def show_faces(self, strip_faces: tuple[StripFace, ...], selected: int | None) -> None:
        for view, face in zip(self.strips, strip_faces, strict=True):
            view.show_face(face, view.index == selected)
        flashing = any("flash" in face.state.leds.values() for face in strip_faces)
        if flashing and not self.blinker.isActive():
            self.blinker.start()
        elif not flashing:
            self.blinker.stop()
            self.blink = True

    def _blink(self) -> None:
        self.blink = not self.blink
        for view in self.strips:
            view.update()

    # -- moving strips --------------------------------------------------------------------------------------------

    def start_drag(self, source: int, grab: int) -> None:
        """Lifts the strip out of the row: its place stays empty, and the others make room where it goes."""
        self._drag = _Drag(source, source, grab)
        view = self.strips[source]
        view.lifted = True
        view.raise_()
        # see-through, so the place where it goes shows under it
        effect = QGraphicsOpacityEffect(view)
        effect.setOpacity(LIFTED_OPACITY)
        view.setGraphicsEffect(effect)
        view.setCursor(Qt.CursorShape.ClosedHandCursor)
        # Escape cancels: the keys come here while the mouse is held
        self.grabKeyboard()
        self.update()

    def drag_to(self, x: int) -> None:
        """Follows the mouse (`x` in the preview) and lets the other strips make room at the nearest place."""
        drag = self._drag
        assert drag is not None
        view = self.strips[drag.source]
        left = max(MARGIN_X, min(x - drag.grab, slot_position(protocol.STRIPS - 1).x()))
        view.move(left, MARGIN_Y - LIFT)
        nearest = round((left - MARGIN_X) / (WIDTH + SPACING))
        target = max(0, min(nearest, self.configured - 1))
        if target != drag.target:
            drag.target = target
            self._arrange(drag.source, target)
            self.update()

    def drop(self) -> None:
        """Puts the strip where it was dragged to."""
        drag = self._end_drag()
        if drag.target != drag.source:
            self.moved.emit(drag.source, drag.target)

    def cancel_drag(self) -> None:
        """Back to where it was, as if it had not been dragged."""
        self._end_drag()

    def _end_drag(self) -> _Drag:
        drag = self._drag
        assert drag is not None
        self._drag = None
        self.releaseKeyboard()
        view = self.strips[drag.source]
        view.lifted = False
        view.setGraphicsEffect(None)
        view.setCursor(Qt.CursorShape.PointingHandCursor)
        # every view back to its own place at once: after a move the window shows the moved strips in them
        for animation in self.animations.values():
            animation.stop()
        for index, strip in enumerate(self.strips):
            strip.move(slot_position(index))
        self.update()
        return drag

    def _arrange(self, source: int, target: int) -> None:
        """Glides every strip but the dragged one to its place with the dragged one at `target`."""
        order = list(range(protocol.STRIPS))
        order.insert(target, order.pop(source))
        for place, index in enumerate(order):
            if index == source:
                continue
            animation = self.animations.get(index)
            if animation is None:
                animation = QPropertyAnimation(self.strips[index], b"pos", self)
                animation.setDuration(ANIMATION_MS)
                animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                self.animations[index] = animation
            end = slot_position(place)
            if animation.state() == QAbstractAnimation.State.Running and animation.endValue() == end:
                continue
            animation.stop()
            animation.setStartValue(self.strips[index].pos())
            animation.setEndValue(end)
            animation.start()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        assert event is not None
        if self.dragging and event.key() == Qt.Key.Key_Escape:
            self.cancel_drag()
            return
        super().keyPressEvent(event)

    def key(self, index: int, event: QKeyEvent) -> bool:
        """
        A key for the strip that has the focus: the arrows, Home and End select, Ctrl+arrows move it, Delete removes
        it. False for other keys.
        """
        key = event.key()
        if self.dragging and key == Qt.Key.Key_Escape:
            self.cancel_drag()
            return True
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self.focus_strip(0 if key == Qt.Key.Key_Home else protocol.STRIPS - 1)
            return True
        if key == Qt.Key.Key_Delete and self.strips[index].look.configured:
            self.remove.emit(index)
            return True
        if key not in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            return False
        target = index + (-1 if key == Qt.Key.Key_Left else 1)
        if not 0 <= target < protocol.STRIPS:
            return True
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.strips[index].look.configured and target < self.configured:
                self.moved.emit(index, target)
                self.strips[target].setFocus()
            return True
        self.focus_strip(target)
        return True

    def focus_strip(self, index: int) -> None:
        self.strips[index].setFocus()
        self.clicked.emit(index)

    def menu_for(self, index: int) -> QMenu:
        """What can be done with a strip, the same as with its keys and on its page, for those who look here."""
        menu = QMenu(self)
        if self.strips[index].look.configured:
            for text, icon, target, keys in (
                ("Move left", "chevron-left", index - 1, "Ctrl+Left"),
                ("Move right", "chevron-right", index + 1, "Ctrl+Right"),
            ):
                action = QAction(theme.icon(icon), f"{text}\t{keys}", menu)
                action.setEnabled(0 <= target < self.configured)
                action.triggered.connect(lambda _=False, target=target: self.moved.emit(index, target))
                menu.addAction(action)
            menu.addSeparator()
            remove = QAction(theme.icon("delete-outline", theme.current_colors().error), "Remove\tDel", menu)
            remove.triggered.connect(lambda: self.remove.emit(index))
            menu.addAction(remove)
        else:
            configure = QAction(theme.icon("plus"), f"Configure strip {index + 1}", menu)
            configure.triggered.connect(lambda: self.configure.emit(index))
            menu.addAction(configure)
        return menu

    # -- painting -------------------------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#2b2f37"), 1))
        painter.setBrush(QColor("#111317"))
        painter.drawRoundedRect(QRect(self.rect()).adjusted(1, 1, -1, -1), 16, 16)
        if self._drag is not None:
            # where the strip goes when it is let go: an empty place in the row
            place = QRectF(QPointF(slot_position(self._drag.target)), QSizeF(WIDTH, HEIGHT)).adjusted(3, 3, -3, -3)
            accent = QColor(theme.current_colors().accent)
            fill = QColor(accent)
            fill.setAlpha(40)
            painter.setBrush(fill)
            painter.setPen(QPen(accent, 2, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(place, 10, 10)


class StripView(QWidget):
    """One strip of the device."""

    def __init__(self, preview: Preview, index: int):
        super().__init__(preview)  # pyright: ignore[reportArgumentType]: PyQt's stub types the parent as Self
        self.preview = preview
        self.index = index
        look = StripLook("auto", "auto", "", "white", configured=False, problems=0)
        self.face = faces((look,), None, (False,))[0]
        self.selected = False
        self.lifted = False
        """Whether it is being dragged."""
        self._press: QPoint | None = None
        self.resize(WIDTH, HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lcd_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.lcd_font.setPixelSize(15)
        self.lcd_font.setWeight(QFont.Weight.DemiBold)

    @property
    def look(self) -> StripLook:
        return self.face.look

    def show_face(self, face: StripFace, selected: bool) -> None:
        self.face = face
        self.selected = selected
        look = face.look
        lines = [f"Strip {self.index + 1}: {KIND_NAMES.get(look.kind, look.kind)}"]
        if not look.configured:
            lines.append("Not configured, so an auto strip: double-click to configure it.")
        lines.append(look.detail)
        if face.edited:
            lines.append("Unsaved changes: it shows how it will look once saved.")
        elif face.live:
            lines.append("Live: what the device shows right now.")
        if look.problems:
            lines.append(f"{look.problems} problem{'' if look.problems == 1 else 's'}")
        if look.configured:
            lines.append("Drag it (or Ctrl+Left/Right) to move it.")
        self.setToolTip("\n".join(lines))
        self.setAccessibleName(f"Strip {self.index + 1}")
        self.setAccessibleDescription(" ".join(lines[1:]))
        self.update()

    # -- painting -------------------------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        face = self.face
        if face.dimmed:
            painter.setOpacity(0.55)
        body = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
        gradient.setColorAt(0, QColor("#30343d" if self.lifted else "#2a2e36"))
        gradient.setColorAt(1, QColor("#1f2228"))
        painter.setBrush(gradient)
        accent = QColor(theme.current_colors().accent)
        if self.selected or self.lifted:
            pen = QPen(accent, 2.5)
        elif face.edited:
            pen = QPen(accent, 1.4, Qt.PenStyle.DashLine)
        elif face.look.configured:
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
        if face.look.problems:
            self._paint_badge(painter, QPointF(body.right() - 8, body.top() + 8), str(face.look.problems))
        if face.edited:
            self._paint_edited(painter, QPointF(body.left() + 9, body.top() + 9))
        if self.hasFocus():
            painter.setPen(QPen(accent, 1.5, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(body.adjusted(-2, -2, 2, 2), 12, 12)

    def _paint_encoder(self, painter: QPainter, center: QPointF) -> None:
        # the ring of LEDs around the encoder, and the knob
        painter.setPen(Qt.PenStyle.NoPen)
        state = self.face.state
        lit = ring_leds(state.ring, state.ring_mode)
        for step in range(protocol.RING_MAX):
            angle = 225 - step * 27
            point = QPointF(center.x() + 19 * cos(radians(angle)), center.y() - 19 * sin(radians(angle)))
            painter.setBrush(QColor("#ff9e3d" if step + 1 in lit else "#3a3f49"))
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
        state = self.face.state
        painter.setPen(QPen(QColor("#0c0d0f"), 2))
        backlight = QColor(theme.LCD_COLORS[state.color])
        if self.face.dimmed:
            # an auto strip without an application is dark on the device; the preview shows it dimmed
            backlight = backlight.darker(170)
        painter.setBrush(backlight)
        painter.drawRoundedRect(rect, 4, 4)
        painter.setFont(self.lcd_font)
        painter.setPen(_lcd_text_color(state.color))
        top = QRectF(rect.left(), rect.top() + 3, rect.width(), rect.height() / 2 - 2)
        bottom = QRectF(rect.left(), rect.center().y() + 1, rect.width(), rect.height() / 2 - 4)
        # the 7 characters of the cell where the device puts them: it does not center a shorter text
        width = protocol.LCD_CELL_WIDTH
        painter.drawText(top, Qt.AlignmentFlag.AlignCenter, state.text[0][:width].ljust(width))
        painter.drawText(bottom, Qt.AlignmentFlag.AlignCenter, state.text[1][:width].ljust(width))

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
        leds = self.face.state.leds
        for row, name in enumerate(LED_COLORS):
            rect = QRectF(left, top + row * 21, 52, 16)
            led = leds[name]
            on = led == "on" or (led == "flash" and self.preview.blink)
            color = QColor(LED_COLORS[name])
            painter.setPen(QPen(QColor("#121418"), 1))
            painter.setBrush(color if on else QColor("#3a3f48"))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor("#15171b") if on else color.darker(150))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, name.upper())

    def _paint_meter(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        height = rect.height() / METER_SEGMENTS
        lit = meter_segments(self.face.state.meter, METER_SEGMENTS)
        for segment in range(METER_SEGMENTS):
            # from the top: red, two yellow, the rest green; they light from the bottom up
            color = QColor("#ff4d4d" if segment == 0 else "#ffd23f" if segment < 3 else "#3ee06a")
            painter.setBrush(color if METER_SEGMENTS - segment <= lit else color.darker(330))
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top() + segment * height + 1, rect.width(), height - 2), 1.5, 1.5
            )

    def _paint_fader(self, painter: QPainter, track: QRectF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0d0e10"))
        painter.drawRoundedRect(track, 3, 3)
        state = self.face.state
        # not known yet: at the bottom, where the daemon leaves it
        fraction = 0.0 if state.fader is None else state.fader
        position = track.bottom() - 6 - (track.height() - 12) * fraction
        cap = QRectF(track.center().x() - 16, position - 7, 32, 14)
        gradient = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        gradient.setColorAt(0, QColor("#d9dce1"))
        gradient.setColorAt(1, QColor("#8c929c"))
        painter.setBrush(gradient)
        # a finger on it: outlined, as the motor stays still meanwhile
        touched = QPen(QColor(theme.current_colors().accent), 2)
        painter.setPen(touched if state.touched else QPen(QColor("#202328"), 1))
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

    def _paint_edited(self, painter: QPainter, center: QPointF) -> None:
        # unsaved changes: a dot, like the marker of a modified file in an editor tab
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.current_colors().accent))
        painter.drawEllipse(center, 4.5, 4.5)

    # -- input ----------------------------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        assert event is not None
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self.preview.clicked.emit(self.index)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        if not self.look.configured:
            self.preview.configure.emit(self.index)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        assert event is not None
        point = event.position().toPoint()
        if self.preview.dragging:
            self.preview.drag_to(self.mapToParent(point).x())
            return
        if self._press is None or not self.look.configured:
            return
        if (point - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self.preview.start_drag(self.index, self._press.x())
        self.preview.drag_to(self.mapToParent(point).x())

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        self._press = None
        if self.preview.dragging:
            self.preview.drop()

    def contextMenuEvent(self, event: QContextMenuEvent | None) -> None:
        assert event is not None
        self.preview.clicked.emit(self.index)
        self.preview.menu_for(self.index).exec(event.globalPos())

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        assert event is not None
        if not self.preview.key(self.index, event):
            super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent | None) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event: QFocusEvent | None) -> None:
        super().focusOutEvent(event)
        self.update()
