"""
The drawing of the device without its toolkit: the 8 strips laid out like the hardware, what each shows, and what the
mouse and keys do on them. It is `Preview` of the widgets (`gui/qt/preview/panel.py`) for QML: the items of
`items.py` paint the strips, `DevicePanel.qml` lays them out from `scale`, `originX`, `originY` and `positions`.

It is in one of two modes: Select, where a click (or the arrow keys) picks a strip, and with it its slot, and dragging
a strip (or Ctrl+arrow) moves its slot; or Play, where the mouse is a hand on the device (`Hand`).
"""

import time
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, cast

from PyQt6.QtCore import (  # pyright: ignore[reportUnknownVariableType]
    QObject,
    QPointF,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QKeyEvent

from xtouch_daemon.gui.domain.looks import UNKNOWN, StripFace
from xtouch_daemon.gui.qt.preview.geometry import HEIGHT, MARGIN_X, MARGIN_Y, PANEL, SPACING, WIDTH, slot_position
from xtouch_daemon.gui.qt.preview.panel import ANIMATION_MS, BLINK_MS, FRAME_MS, LIFT, MIN_SCALE, SETTLE_MS, Hand
from xtouch_daemon.gui.quick.device.strips import HostWidget, PaintedStrip
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import moving

if TYPE_CHECKING:
    from xtouch_daemon.gui.qt.preview.strip_view import Mover

__all__ = ["ANIMATION_MS", "MIN_SCALE", "Drawing"]


@dataclass
class _Drag:
    source: int
    target: int
    grab: float
    """Where the strip was grabbed, from its left edge (in logical units)."""
    left: float
    """Where its left edge is (in logical units)."""


class Drawing(QObject):
    """The 8 strips side by side, on a panel like the device (see the module)."""

    clicked = pyqtSignal(int, arguments=["index"])
    cleared = pyqtSignal(arguments=[])
    """The panel was clicked beside the strips (in Select): nothing is picked anymore."""
    moved = pyqtSignal(int, int, arguments=["source", "target"])
    """A strip was moved (dragged, Ctrl+arrow, or with the menu), from 0: its slot goes along."""
    focusRequested = pyqtSignal(int, arguments=["index"])
    """The item of this strip is to get the keyboard focus (after the arrows or Home and End)."""
    layoutChanged = pyqtSignal(arguments=[])
    positionsChanged = pyqtSignal(arguments=[])
    dragChanged = pyqtSignal(arguments=[])
    modeChanged = pyqtSignal(arguments=[])
    simulatingChanged = pyqtSignal(arguments=[])
    panelChanged = pyqtSignal(arguments=[])
    """The panel behind the strips must be painted again (a frame, a place of a dragged strip)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]
        self.scale = 1.0
        """How large the panel is drawn: it fills the space it gets, keeping its proportions."""
        self.origin = QPointF()
        """Where the panel starts, centered in the space."""
        self.size = (0.0, 0.0)
        self.settle = QTimer(self)
        """Runs while the size changes: until it times out, strips scale the picture of their printed parts."""
        self.settle.setSingleShot(True)
        self.settle.setInterval(SETTLE_MS)
        self.settle.timeout.connect(self._settled)
        self.host = HostWidget(self)
        self.destroyed.connect(self.host.deleteLater)
        self.strips: list[PaintedStrip] = [PaintedStrip(self.host, index) for index in range(protocol.STRIPS)]
        self.blink = True
        """Whether flashing LEDs are lit right now."""
        self.blinker = QTimer(self)
        self.blinker.setInterval(BLINK_MS)
        self.blinker.timeout.connect(self._blink)
        self.now = time.monotonic()
        """The time the strips are drawn at: the meters fall and the faders glide from what they were told."""
        self.animator = QTimer(self)
        """Draws the strips again every frame while something of them moves by itself."""
        self.animator.setTimerType(Qt.TimerType.PreciseTimer)
        self.animator.setInterval(FRAME_MS)
        self.animator.timeout.connect(self._animate)
        self.simulating = False
        """Whether the strips show a simulation, not the device: then the panel has a frame in the accent color."""
        self.device_hand: Hand | None = None
        """
        The device the mouse can be a hand on (the hosted virtual device, or the daemon's device through the live
        view), None for none.
        """
        self.playing = False
        """Play: the mouse is a hand on `device_hand`, nothing is picked; else (Select) a click picks, a drag moves."""
        self.selected: int | None = None
        """The strip picked (in Select), shown again when Play ends."""
        self._drag: _Drag | None = None
        for strip in self.strips:
            strip.show_face(UNKNOWN, False)

    # -- what a strip is drawn in (`StripSource`) ----------------------------------------------------------------------

    @property
    def hand(self) -> Hand | None:
        """The device the mouse is a hand on right now: only in Play."""
        return self.device_hand if self.playing else None

    @property
    def mover(self) -> Mover | None:
        """In Select, dragging a strip moves its slot; in Play the mouse is a hand."""
        # the drag of the widgets' strips calls `start_drag`, `drag_to`, `drop` and `dragging`, which are here
        return None if self.playing else cast("Mover", self)

    @property
    def resizing(self) -> bool:
        """Whether the size is changing: then strips scale the pictures they have."""
        return self.settle.isActive()

    def pick(self, index: int) -> None:
        # in Play a click is a hand on the device: it picks nothing
        if not self.playing:
            self.clicked.emit(index)

    # -- the layout ----------------------------------------------------------------------------------------------

    @pyqtProperty(float, notify=layoutChanged)
    def panelScale(self) -> float:  # pyright: ignore[reportRedeclaration]
        """Pixels per logical unit: the panel fills the space it has, keeping its proportions."""
        return self.scale

    @pyqtProperty(float, notify=layoutChanged)
    def originX(self) -> float:  # pyright: ignore[reportRedeclaration]
        return self.origin.x()

    @pyqtProperty(float, notify=layoutChanged)
    def originY(self) -> float:  # pyright: ignore[reportRedeclaration]
        return self.origin.y()

    @pyqtProperty(int, notify=layoutChanged)
    def stripWidth(self) -> int:  # pyright: ignore[reportRedeclaration]
        return ceil(WIDTH * self.scale)

    @pyqtProperty(int, notify=layoutChanged)
    def stripHeight(self) -> int:  # pyright: ignore[reportRedeclaration]
        return ceil(HEIGHT * self.scale)

    @pyqtProperty(int, constant=True)
    def minimumHeight(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The least height the drawing gets: at about a third of its size it still shows the LEDs and the LCD."""
        return ceil(PANEL.height() * MIN_SCALE)

    @pyqtProperty(int, constant=True)
    def preferredHeight(self) -> int:  # pyright: ignore[reportRedeclaration]
        return ceil(PANEL.height())

    @pyqtSlot(float, float)
    def setSize(self, width: float, height: float) -> None:
        """Scales the panel to the space it gets, centered, and puts every strip in its place at that scale."""
        if (width, height) == self.size:
            return
        if self.size != (0.0, 0.0):
            # a change of size, not the first one: draw fast until it ends
            self.settle.start()
        self.size = (width, height)
        self.scale = max(0.01, min(width / PANEL.width(), height / PANEL.height()))
        self.origin = QPointF((width - PANEL.width() * self.scale) / 2, (height - PANEL.height() * self.scale) / 2)
        if self.dragging:
            self.cancel_drag()
        self.layoutChanged.emit()
        self.positionsChanged.emit()
        self.panelChanged.emit()
        for strip in self.strips:
            strip.update()

    def _settled(self) -> None:
        for strip in self.strips:
            strip.update()

    def places(self) -> list[QPointF]:
        """Where each strip is, in logical units: its slot, the others making room for a dragged one."""
        drag = self._drag
        if drag is None:
            return [QPointF(slot_position(index)) for index in range(protocol.STRIPS)]
        order = list(range(protocol.STRIPS))
        order.insert(drag.target, order.pop(drag.source))
        return [
            QPointF(drag.left, MARGIN_Y - LIFT) if index == drag.source else QPointF(slot_position(order.index(index)))
            for index in range(protocol.STRIPS)
        ]

    @pyqtProperty("QVariantList", notify=positionsChanged)
    def positions(self) -> list[QPointF]:  # pyright: ignore[reportRedeclaration]
        """Where the strips are, in logical units, from the left one: the dragged one under the mouse."""
        return self.places()

    # -- what it shows -------------------------------------------------------------------------------------------

    @pyqtProperty(bool, notify=modeChanged)
    def isPlaying(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self.playing

    @pyqtProperty(bool, notify=simulatingChanged)
    def isSimulating(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self.simulating

    def set_playing(self, playing: bool) -> None:
        if self.dragging:
            self.cancel_drag()
        changed = playing != self.playing
        self.playing = playing
        for view in self.strips:
            view.held = None
            view.dragged_fader = None
            view.selected = not playing and view.index == self.selected
            view.update()
        if changed:
            self.modeChanged.emit()

    def show_faces(self, strip_faces: tuple[StripFace, ...], selected: int | None, simulating: bool = False) -> None:
        if simulating != self.simulating:
            self.simulating = simulating
            self.simulatingChanged.emit()
            self.panelChanged.emit()
        self.selected = selected
        for view, face in zip(self.strips, strip_faces, strict=True):
            view.show_face(face, not self.playing and view.index == selected)
        self._animate()
        flashing = any("flash" in face.state.leds.values() for face in strip_faces)
        if flashing and not self.blinker.isActive():
            self.blinker.start()
        elif not flashing:
            self.blinker.stop()
            self.blink = True

    def _animate(self) -> None:
        """
        The strips at the time of now, where that changed what they show (a meter fell a level, a fader moved on);
        the frames go on while something still moves.
        """
        self.now = time.monotonic()
        for view in self.strips:
            view.follow_time()
        if any(moving(view.face.state, self.now) for view in self.strips):
            if not self.animator.isActive():
                self.animator.start()
        else:
            self.animator.stop()

    def _blink(self) -> None:
        self.blink = not self.blink
        for view in self.strips:
            view.update()

    @pyqtSlot()
    def clickBeside(self) -> None:
        """A click beside the strips (on the panel or around it) picks nothing: the strip picked is no more."""
        if not self.playing and not self.dragging:
            self.cleared.emit()

    # -- moving strips (Select) ----------------------------------------------------------------------------------

    @property
    def dragging(self) -> bool:
        return self._drag is not None

    @pyqtProperty(bool, notify=dragChanged)
    def isDragging(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._drag is not None

    @pyqtProperty(int, notify=dragChanged)
    def dragSource(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The strip dragged, -1 for none."""
        return -1 if self._drag is None else self._drag.source

    @pyqtProperty(int, notify=dragChanged)
    def dragTarget(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The place the dragged strip goes to when it is let go, -1 for none."""
        return -1 if self._drag is None else self._drag.target

    def start_drag(self, source: int, grab: float) -> None:
        """Lifts the strip out of the row: its place stays empty, and the others make room where it goes."""
        self._drag = _Drag(source, source, grab, slot_position(source).x())
        view = self.strips[source]
        view.lifted = True
        view.update()
        self.dragChanged.emit()
        self.positionsChanged.emit()
        self.panelChanged.emit()

    def drag_to(self, x: int) -> None:
        """Follows the mouse (`x` in the space of the drawing); the other strips make room at the nearest place."""
        drag = self._drag
        assert drag is not None
        panel_x = (x - self.origin.x()) / self.scale
        drag.left = max(MARGIN_X, min(panel_x - drag.grab, slot_position(protocol.STRIPS - 1).x()))
        nearest = round((drag.left - MARGIN_X) / (WIDTH + SPACING))
        target = max(0, min(nearest, protocol.STRIPS - 1))
        if target != drag.target:
            drag.target = target
            self.dragChanged.emit()
            self.panelChanged.emit()
        self.positionsChanged.emit()

    def drop(self) -> None:
        """Puts the strip where it was dragged to."""
        drag = self._end_drag()
        if drag.target != drag.source:
            self.moved.emit(drag.source, drag.target)

    @pyqtSlot()
    def cancel_drag(self) -> None:
        """Back to where it was, as if it had not been dragged."""
        if self._drag is not None:
            self._end_drag()

    def _end_drag(self) -> _Drag:
        drag = self._drag
        assert drag is not None
        self._drag = None
        self.strips[drag.source].lifted = False
        self.strips[drag.source].update()
        # the state of the drag first: the items glide only while it lasts, and every strip is back at its own place at
        # once (after a move the window shows the moved slots in them)
        self.dragChanged.emit()
        self.positionsChanged.emit()
        self.panelChanged.emit()
        return drag

    def menu_for(self, index: int) -> None:
        """Not here: `menuFor`, for the `Menu` of QML (the protocol of the widgets asks for a `QMenu`)."""
        raise NotImplementedError

    @pyqtSlot(int, result="QVariantList")
    def menuFor(self, index: int) -> list[dict[str, object]]:
        """What can be done with a strip, the same as with its keys, for those who look here."""
        return [
            {
                "text": text,
                "icon": icon_name,
                "keys": keys,
                "target": target,
                "enabled": 0 <= target < protocol.STRIPS,
            }
            for text, icon_name, target, keys in (
                ("Move left", "chevron-left", index - 1, "Ctrl+Left"),
                ("Move right", "chevron-right", index + 1, "Ctrl+Right"),
            )
        ]

    @pyqtSlot(int, int)
    def moveStrip(self, index: int, target: int) -> None:
        """The menu of a strip: its slot goes to `target`."""
        if 0 <= target < protocol.STRIPS and target != index:
            self.moved.emit(index, target)

    # -- keys ----------------------------------------------------------------------------------------------------

    def key(self, index: int, event: QKeyEvent) -> bool:
        """
        A key for the strip that has the focus: the arrows, Home and End pick, Ctrl+arrows move it (in Select), Esc
        ends a drag. False for other keys.
        """
        key = event.key()
        if self.dragging and key == Qt.Key.Key_Escape:
            self.cancel_drag()
            return True
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self.focus_strip(0 if key == Qt.Key.Key_Home else protocol.STRIPS - 1)
            return True
        if key not in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            return False
        target = index + (-1 if key == Qt.Key.Key_Left else 1)
        if not 0 <= target < protocol.STRIPS:
            return True
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if not self.playing:
                self.moved.emit(index, target)
                self.focusRequested.emit(target)
            return True
        self.focus_strip(target)
        return True

    def focus_strip(self, index: int) -> None:
        self.focusRequested.emit(index)
        self.pick(index)

    def panel_geometry(self) -> tuple[QPointF, float]:
        """Where the panel starts and how large it is drawn, for the item that paints it."""
        return self.origin, self.scale
