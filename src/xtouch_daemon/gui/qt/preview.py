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
    QFontMetricsF,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QRadialGradient,
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
ANIMATION_MS = 160
"""How long the other strips take to make room for a dragged one: quick, but long enough to see where they go."""
BLINK_MS = 400
"""How fast a flashing LED blinks."""
LIFT = 8
"""How far a dragged strip is lifted out of the row."""
LIFTED_OPACITY = 0.8

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


def slot_position(index: int) -> QPoint:
    """Where the strip at `index` sits in the preview."""
    return QPoint(MARGIN_X + index * (WIDTH + SPACING), MARGIN_Y)


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
        """The panel of the device (dark, lit from above, a bevel at the top edge), and the place of a dragged strip."""
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
        if self._drag is not None:
            # where the strip goes when it is let go: an empty place in the row
            place = QRectF(QPointF(slot_position(self._drag.target)), QSizeF(WIDTH, HEIGHT)).adjusted(3, 3, -3, -3)
            accent = QColor(theme.current_colors().accent)
            fill = QColor(accent)
            fill.setAlpha(40)
            painter.setBrush(fill)
            painter.setPen(QPen(accent, 2, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(place, STRIP_RADIUS, STRIP_RADIUS)


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
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.lcd_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.lcd_font.setPixelSize(14)
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
    # what the strip shows comes from its `face` (live or from the file); the `_paint_*` methods draw it like the device

    def _backlight(self) -> float:
        """1 lit, 0 dark, in between dimmed (an auto strip of the file, which is dark until an application plays)."""
        if self.face.state.color == "off":
            return 0.0
        return DIM if self.face.dimmed else 1.0

    def _lit(self, led: str) -> bool:
        return led == "on" or (led == "flash" and self.preview.blink)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        face = self.face
        look, state = face.look, face.state
        body = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        self._paint_body(painter, body)
        if not look.configured:
            painter.setOpacity(UNCONFIGURED_OPACITY)
        center = body.center().x()
        self._paint_encoder(painter, QPointF(center, body.top() + 30), ring_leds(state.ring, state.ring_mode))
        self._paint_lcd(painter, QRectF(body.left() + 6, body.top() + 57, body.width() - 12, 46))
        kind = KIND_NAMES.get(look.kind, look.kind).upper()
        self._paint_print(painter, QRectF(body.left(), body.top() + 106, body.width(), 16), kind, look.kind == "?")
        for row, (name, color) in enumerate(BUTTONS):
            rect = QRectF(body.left() + 8, body.top() + 126 + row * 20, 54, 16)
            self._paint_button(painter, rect, name, color, self._lit(state.leds[name.lower()]))
        meter = meter_segments(state.meter, METER_SEGMENTS)
        self._paint_meter(painter, QRectF(body.right() - 22, body.top() + 126, 10, 76), meter)
        # not known yet: at the bottom, where the daemon leaves it
        fader = 0.0 if state.fader is None else state.fader
        self._paint_fader(painter, QRectF(center - 2.5, body.top() + 214, 5, 68), fader, state.touched)
        painter.setOpacity(1)
        if look.problems:
            self._paint_badge(painter, QPointF(body.right() - 9, body.top() + 9), str(look.problems))
        if face.edited:
            self._paint_edited(painter, QPointF(body.left() + 9, body.top() + 9))
        if self.hasFocus():
            painter.setPen(QPen(QColor(theme.current_colors().accent), 1.5, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(body.adjusted(-2, -2, 2, 2), STRIP_RADIUS + 2, STRIP_RADIUS + 2)

    def _paint_body(self, painter: QPainter, body: QRectF) -> None:
        """
        The part of the panel that is this strip, outlined when it is selected or dragged, dashed with unsaved changes
        (in the accent) or when it is not configured.
        """
        gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
        top = QColor(HW.strip_top)
        gradient.setColorAt(0, top.lighter(125) if self.lifted else top)
        gradient.setColorAt(1, QColor(HW.strip_bottom))
        painter.setBrush(gradient)
        accent = QColor(theme.current_colors().accent)
        if self.selected or self.lifted:
            # a soft glow around the outline
            glow = QColor(accent)
            for width, alpha in ((6, 40), (4, 80)):
                glow.setAlpha(alpha)
                painter.setPen(QPen(glow, width))
                painter.drawRoundedRect(body, STRIP_RADIUS, STRIP_RADIUS)
            pen = QPen(accent, 2)
        elif self.face.edited:
            pen = QPen(accent, 1.4, Qt.PenStyle.DashLine)
        elif not self.look.configured:
            pen = QPen(QColor(HW.print_dim), 1, Qt.PenStyle.DashLine)
        else:
            pen = QPen(QColor(HW.print_dim if self.underMouse() else HW.strip_edge), 1)
        painter.setPen(pen)
        painter.drawRoundedRect(body, STRIP_RADIUS, STRIP_RADIUS)

    def _paint_encoder(self, painter: QPainter, center: QPointF, ring: frozenset[int]) -> None:
        """The LED ring (`ring`: its lit LEDs, 1..11 from the left), the center LED below it, and the knob."""
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(protocol.RING_MAX):
            angle = radians(225 - step * 27)
            point = QPointF(center.x() + 21 * cos(angle), center.y() - 21 * sin(angle))
            _paint_led(painter, point, 2.2, HW.ring, step + 1 in ring)
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

    def _paint_lcd(self, painter: QPainter, rect: QRectF) -> None:
        """The LCD: a black bezel, the backlit glass, and 2 lines of 7 character cells, written from the left."""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(HW.lcd_bezel))
        painter.drawRoundedRect(rect, 4, 4)
        glass = rect.adjusted(3, 3, -3, -3)
        state = self.face.state
        level = self._backlight()
        backlight = _mix(QColor(theme.LCD_COLORS[state.color]), QColor(theme.LCD_COLORS["off"]), level)
        lit = level == 1.0
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
        painter.setPen(QColor(theme.LCD_TEXT if lit else theme.LCD_TEXT_OFF if level == 0 else LCD_TEXT_DIM))
        for line, text in enumerate(state.text):
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

    def _paint_fader(self, painter: QPainter, slot: QRectF, fraction: float, touched: bool) -> None:
        """
        The slot with its scale, and the cap at `fraction` (0 at the bottom, 1 at the top): outlined in the accent while
        a finger is on it, as the motor stays still meanwhile.
        """
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
        painter.setPen(QPen(QColor(theme.current_colors().accent), 2) if touched else QPen(QColor(HW.cap_line), 1))
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
