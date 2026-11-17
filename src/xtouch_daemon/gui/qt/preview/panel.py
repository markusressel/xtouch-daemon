"""
The preview: the 8 strips laid out like the hardware, showing what the device shows right now while the daemon
runs. A click (or the arrow keys) selects a strip, and with it its slot.

The strips are laid out and painted in logical units (see `geometry`) and scaled to the space the preview gets, so
they stay sharp at any size and zoom.
"""

from math import ceil
from typing import Protocol

from PyQt6.QtCore import (
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from xtouch_daemon.gui.domain.looks import StripFace
from xtouch_daemon.gui.qt.preview.geometry import HEIGHT, PANEL, WIDTH, slot_position
from xtouch_daemon.gui.qt.preview.painting import HW, PANEL_RADIUS
from xtouch_daemon.gui.qt.preview.strip_view import StripView
from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button

MIN_SCALE = 0.5
"""The smallest the preview gets: half its size still shows the LEDs, faders and LCD colors."""
SETTLE_MS = 150
"""
How long after the last change of size the strips are drawn sharp again: meanwhile (e.g. while the handle above the
editor is dragged) their printed parts are the picture of before, scaled, which is much faster.
"""
BLINK_MS = 400
"""How fast a flashing LED blinks."""


class Hand(Protocol):
    """What the mouse does on a device it plays a hand on (the virtual device the GUI hosts), strips from 0."""

    def touch(self, strip: int, touched: bool) -> None: ...

    def move(self, strip: int, fraction: float, hand: bool = True) -> None: ...

    def press(self, strip: int, button: Button, pressed: bool) -> None: ...

    def turn(self, strip: int, steps: int) -> None: ...

    def push(self, strip: int, pressed: bool) -> None: ...


class Preview(QWidget):
    """The 8 strips side by side, on a panel like the device."""

    clicked = pyqtSignal(int, arguments=["index"])

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
        self.strips: list[StripView] = [StripView(self, index) for index in range(protocol.STRIPS)]
        self.blink = True
        """Whether flashing LEDs are lit right now."""
        self.blinker = QTimer(self)
        self.blinker.setInterval(BLINK_MS)
        self.blinker.timeout.connect(self._blink)
        self.simulating = False
        """Whether the strips show a simulation, not the device: then the panel has a frame in the accent color."""
        self.hand: Hand | None = None
        """The device the mouse is a hand on (the hosted virtual device), None for none: a click only selects."""

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
        assert event is not None
        if not event.oldSize().isEmpty():
            # a change of size, not the first one: draw fast until it ends
            self.settle.start()
        self.scale = min(self.width() / PANEL.width(), self.height() / PANEL.height())
        self.origin = QPointF(
            (self.width() - PANEL.width() * self.scale) / 2, (self.height() - PANEL.height() * self.scale) / 2
        )
        for index, view in enumerate(self.strips):
            view.resize(ceil(WIDTH * self.scale), ceil(HEIGHT * self.scale))
            view.move(self.slot_point(index))

    @property
    def resizing(self) -> bool:
        """Whether the size is changing: then strips scale the pictures they have."""
        return self.settle.isActive()

    def _settled(self) -> None:
        for view in self.strips:
            view.update()

    def show_faces(self, strip_faces: tuple[StripFace, ...], selected: int | None, simulating: bool = False) -> None:
        if simulating != self.simulating:
            self.simulating = simulating
            self.update()
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

    def pick(self, index: int) -> None:
        self.clicked.emit(index)

    def key(self, index: int, event: QKeyEvent) -> bool:
        """A key for the strip that has the focus: the arrows, Home and End select. False for other keys."""
        key = event.key()
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self.focus_strip(0 if key == Qt.Key.Key_Home else protocol.STRIPS - 1)
            return True
        if key not in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            return False
        target = index + (-1 if key == Qt.Key.Key_Left else 1)
        if 0 <= target < protocol.STRIPS:
            self.focus_strip(target)
        return True

    def focus_strip(self, index: int) -> None:
        self.strips[index].setFocus()
        self.clicked.emit(index)

    # -- painting -------------------------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """The panel of the device: dark, lit from above, a bevel at the top edge."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.origin)
        painter.scale(self.scale, self.scale)
        panel = QRectF(QPointF(), PANEL).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(panel.topLeft(), panel.bottomLeft())
        gradient.setColorAt(0, QColor(HW.panel_top))
        gradient.setColorAt(1, QColor(HW.panel_bottom))
        painter.setBrush(gradient)
        edge = QPen(QColor(current_colors().accent), 4) if self.simulating else QPen(QColor(HW.panel_edge), 1)
        painter.setPen(edge)
        painter.drawRoundedRect(panel, PANEL_RADIUS, PANEL_RADIUS)
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        painter.drawLine(
            QPointF(panel.left() + PANEL_RADIUS, panel.top() + 1.5),
            QPointF(panel.right() - PANEL_RADIUS, panel.top() + 1.5),
        )
