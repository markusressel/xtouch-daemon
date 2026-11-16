"""
The preview: the 8 strips laid out like the hardware, showing what the device shows right now while the daemon
runs, or what the file would show. It is also how a strip is picked: a click (or the arrow keys) selects a strip,
dragging a configured strip (or Ctrl+arrow) moves it, and the context menu has the rest.

The strips are laid out and painted in logical units (see `geometry`) and scaled to the space the preview gets, so
they stay sharp at any size and zoom.
"""

from dataclasses import dataclass
from math import ceil

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    QSizeF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QColor, QKeyEvent, QLinearGradient, QPainter, QPaintEvent, QPen, QResizeEvent
from PyQt6.QtWidgets import QMenu, QSizePolicy, QWidget

from xtouch_daemon.gui.domain.looks import StripFace
from xtouch_daemon.gui.qt.preview.geometry import HEIGHT, MARGIN_X, MARGIN_Y, PANEL, SPACING, WIDTH, slot_position
from xtouch_daemon.gui.qt.preview.painting import HW, PANEL_RADIUS, STRIP_RADIUS
from xtouch_daemon.gui.qt.preview.strip_view import StripView
from xtouch_daemon.gui.qt.theme.icons import icon
from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.hardware import protocol

MIN_SCALE = 0.5
"""The smallest the preview gets: half its size still shows the LEDs, faders and LCD colors."""
SETTLE_MS = 150
"""
How long after the last change of size the strips are drawn sharp again: meanwhile (e.g. while the handle above the
editor is dragged) their printed parts are the picture of before, scaled, which is much faster.
"""
ANIMATION_MS = 160
"""How long the other strips take to make room for a dragged one: quick, but long enough to see where they go."""
BLINK_MS = 400
"""How fast a flashing LED blinks."""
LIFT = 8
"""How far a dragged strip is lifted out of the row."""


@dataclass
class _Drag:
    source: int
    target: int
    grab: float
    """Where the strip was grabbed, from its left edge (in logical units)."""


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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.scale = 1.0
        """How large the panel is drawn: it fills the space it gets, keeping its proportions."""
        self.origin = QPointF()
        """Where the panel starts, centered in the widget."""
        self.settle = QTimer(self)
        """Runs while the size changes: until it times out, strips scale the picture of their printed parts."""
        self.settle.setSingleShot(True)
        self.settle.setInterval(SETTLE_MS)
        self.settle.timeout.connect(self._settled)
        self.held = False
        """Whether the handle that sizes the preview is held."""
        self.strips: list[StripView] = [StripView(self, index) for index in range(protocol.STRIPS)]
        self._drag: _Drag | None = None
        self.animations: dict[int, QPropertyAnimation] = {}
        """The glides of the strips making room for a dragged one, by strip."""
        self.blink = True
        """Whether flashing LEDs are lit right now."""
        self.blinker = QTimer(self)
        self.blinker.setInterval(BLINK_MS)
        self.blinker.timeout.connect(self._blink)

    def sizeHint(self) -> QSize:
        return QSize(ceil(PANEL.width()), ceil(PANEL.height()))

    def minimumSizeHint(self) -> QSize:
        return QSize(ceil(PANEL.width() * MIN_SCALE), ceil(PANEL.height() * MIN_SCALE))

    def to_widget(self, point: QPointF) -> QPoint:
        """A point of the panel (in logical units) in the widget."""
        return (self.origin + point * self.scale).toPoint()

    def slot_point(self, index: int) -> QPoint:
        """Where the strip at `index` sits in the widget."""
        return self.to_widget(QPointF(slot_position(index)))

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        """Scales the panel to the new size, centered, and puts every strip in its place at that scale."""
        if self.dragging:
            self.cancel_drag()
        assert event is not None
        if not event.oldSize().isEmpty():
            # a change of size, not the first one: draw fast until it ends
            self.settle.start()
        self.scale = min(self.width() / PANEL.width(), self.height() / PANEL.height())
        self.origin = QPointF(
            (self.width() - PANEL.width() * self.scale) / 2, (self.height() - PANEL.height() * self.scale) / 2
        )
        for animation in self.animations.values():
            animation.stop()
        for index, view in enumerate(self.strips):
            view.resize(ceil(WIDTH * self.scale), ceil(HEIGHT * self.scale))
            view.move(self.slot_point(index))

    @property
    def resizing(self) -> bool:
        """Whether the size is changing: then strips scale the pictures they have."""
        return self.held or self.settle.isActive()

    def hold(self, held: bool) -> None:
        """
        The handle that sizes the preview is held (or let go): until it is let go, strips scale their pictures, also
        when the hand rests for a moment; then they are drawn sharp at once.
        """
        self.held = held
        if not held:
            self.settle.stop()
            self._settled()

    def _settled(self) -> None:
        for view in self.strips:
            view.update()

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

    def start_drag(self, source: int, grab: float) -> None:
        """Lifts the strip out of the row: its place stays empty, and the others make room where it goes."""
        self._drag = _Drag(source, source, grab)
        view = self.strips[source]
        view.lifted = True
        view.raise_()
        view.update()
        view.setCursor(Qt.CursorShape.ClosedHandCursor)
        # Escape cancels: the keys come here while the mouse is held
        self.grabKeyboard()
        self.update()

    def drag_to(self, x: int) -> None:
        """Follows the mouse (`x` in the widget) and lets the other strips make room at the nearest place."""
        drag = self._drag
        assert drag is not None
        view = self.strips[drag.source]
        panel_x = (x - self.origin.x()) / self.scale
        left = max(MARGIN_X, min(panel_x - drag.grab, slot_position(protocol.STRIPS - 1).x()))
        view.move(self.to_widget(QPointF(left, MARGIN_Y - LIFT)))
        nearest = round((left - MARGIN_X) / (WIDTH + SPACING))
        target = max(0, min(nearest, protocol.STRIPS - 1))
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
        view.setCursor(Qt.CursorShape.PointingHandCursor)
        # every view back to its own place at once: after a move the window shows the moved strips in them
        for animation in self.animations.values():
            animation.stop()
        for index, strip in enumerate(self.strips):
            strip.move(self.slot_point(index))
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
            end = self.slot_point(place)
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
            if self.strips[index].look.configured:
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
            for text, icon_name, target, keys in (
                ("Move left", "chevron-left", index - 1, "Ctrl+Left"),
                ("Move right", "chevron-right", index + 1, "Ctrl+Right"),
            ):
                action = QAction(icon(icon_name), f"{text}\t{keys}", menu)
                action.setEnabled(0 <= target < protocol.STRIPS)
                action.triggered.connect(lambda _=False, target=target: self.moved.emit(index, target))
                menu.addAction(action)
            menu.addSeparator()
            remove = QAction(icon("delete-outline", current_colors().error), "Remove\tDel", menu)
            remove.triggered.connect(lambda: self.remove.emit(index))
            menu.addAction(remove)
        else:
            configure = QAction(icon("plus"), f"Configure strip {index + 1}", menu)
            configure.triggered.connect(lambda: self.configure.emit(index))
            menu.addAction(configure)
        return menu

    # -- painting -------------------------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """The panel of the device (dark, lit from above, a bevel at the top edge), and the place of a dragged strip."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.origin)
        painter.scale(self.scale, self.scale)
        panel = QRectF(QPointF(), PANEL).adjusted(0.5, 0.5, -0.5, -0.5)
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
            accent = QColor(current_colors().accent)
            fill = QColor(accent)
            fill.setAlpha(40)
            painter.setBrush(fill)
            painter.setPen(QPen(accent, 2, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(place, STRIP_RADIUS, STRIP_RADIUS)
