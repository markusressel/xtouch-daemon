"""
The items of QML that paint the device: `StripItem` (a strip), `PanelItem` (the panel behind the strips) and `PartItem`
(a part of a strip, cut out). They are `QQuickPaintedItem`s: QML places and animates them, and the painting is that of
the widgets (see `strips.py`). The input comes to the item and goes to the code of the widgets: the same clicks, drags,
wheel steps and keys.

The types are registered once for the process (`register_types()`, `import XTouch.Device`).
"""

from PyQt6 import sip
from PyQt6.QtCore import (  # pyright: ignore[reportUnknownVariableType]
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QSizeF,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QHoverEvent,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PyQt6.QtQml import qmlRegisterType
from PyQt6.QtQuick import QQuickItem, QQuickPaintedItem

from xtouch_daemon.gui.domain.tokens import THEMES, ThemeMode
from xtouch_daemon.gui.quick.device.drawing import Drawing
from xtouch_daemon.gui.quick.device.geometry import HEIGHT, PANEL, WIDTH, slot_position
from xtouch_daemon.gui.quick.device.painting import HW, PANEL_RADIUS, STRIP_RADIUS
from xtouch_daemon.gui.quick.device.part import PartPreviewModel

URI = "XTouch.Device"
_registered = False


def mode_of(dark: bool) -> ThemeMode:
    return ThemeMode.DARK if dark else ThemeMode.LIGHT


class StripItem(QQuickPaintedItem):
    """One strip of the `drawing`: it paints the strip `index` and takes the mouse and keys for it."""

    drawingChanged = pyqtSignal(arguments=[])
    stripIndexChanged = pyqtSignal(arguments=[])
    darkChanged = pyqtSignal(arguments=[])
    tipChanged = pyqtSignal(arguments=[])
    hoveredChanged = pyqtSignal(arguments=[])
    contextRequested = pyqtSignal(float, float, arguments=["x", "y"])
    """The right mouse button went down at a point of the strip (Select): a menu of what to do with it."""

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self._drawing: Drawing | None = None
        self._index = 0
        self._dark = True
        self._hovered = False
        self.ratio_override: float | None = None
        """A pixel ratio to paint at instead of the window's (for images made without a window)."""
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.setAcceptHoverEvents(True)
        self.setActiveFocusOnTab(True)
        self.setAntialiasing(True)
        self.activeFocusChanged.connect(self._focus_changed)

    # -- what it shows -------------------------------------------------------------------------------------------

    @pyqtProperty(QObject, notify=drawingChanged)  # pyright: ignore[reportArgumentType]
    def drawing(self) -> QObject | None:  # pyright: ignore[reportRedeclaration]
        """The `Drawing` it is a strip of."""
        return self._drawing

    @drawing.setter
    def drawing(self, drawing: QObject | None) -> None:
        if drawing is self._drawing:
            return
        self._detach()
        self._drawing = drawing if isinstance(drawing, Drawing) else None
        self._attach()
        self.drawingChanged.emit()

    @pyqtProperty(int, notify=stripIndexChanged)
    def stripIndex(self) -> int:  # pyright: ignore[reportRedeclaration]
        """Which strip of the drawing it is, from 0 for the leftmost."""
        return self._index

    @stripIndex.setter
    def stripIndex(self, index: int) -> None:
        if index != self._index:
            self._detach()
            self._index = index
            self._attach()
            self.stripIndexChanged.emit()

    @pyqtProperty(bool, notify=darkChanged)
    def dark(self) -> bool:  # pyright: ignore[reportRedeclaration]
        """Whether the window shows the dark theme: the colors of the print and the marks follow."""
        return self._dark

    @dark.setter
    def dark(self, dark: bool) -> None:
        if dark != self._dark:
            self._dark = dark
            self.darkChanged.emit()
            self.update()

    @pyqtProperty(str, notify=tipChanged)
    def tip(self) -> str:  # pyright: ignore[reportRedeclaration]
        """The tooltip: what the strip is, or in Play what the mouse does with the part under it."""
        view = self.view
        return "" if view is None else view.tip

    @pyqtProperty(str, notify=tipChanged)
    def description(self) -> str:  # pyright: ignore[reportRedeclaration]
        """What the strip controls, for screen readers."""
        view = self.view
        return "" if view is None else view.face.look.detail

    @pyqtProperty(bool, notify=hoveredChanged)
    def hovered(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._hovered

    @property
    def view(self):
        """The strip of the widgets that it paints."""
        drawing = self._drawing
        if drawing is None or not 0 <= self._index < len(drawing.strips):
            return None
        return drawing.strips[self._index]

    def _attach(self) -> None:
        view, drawing = self.view, self._drawing
        if view is None or drawing is None:
            return
        view.changed = self._changed
        view.to_parent = self._to_parent
        view.ratio = self._ratio()
        drawing.focusRequested.connect(self._focus_requested)
        drawing.layoutChanged.connect(self.update)
        drawing.dragChanged.connect(self._sync_cursor)
        drawing.modeChanged.connect(self._sync_cursor)
        self._sync_cursor()
        self.update()

    def _detach(self) -> None:
        view, drawing = self.view, self._drawing
        if view is not None and drawing is not None:
            view.changed = lambda: None
            view.to_parent = lambda point: point
            try:
                for signal, slot in (
                    (drawing.focusRequested, self._focus_requested),
                    (drawing.layoutChanged, self.update),
                    (drawing.dragChanged, self._sync_cursor),
                    (drawing.modeChanged, self._sync_cursor),
                ):
                    signal.disconnect(slot)
            except RuntimeError:
                # the drawing is gone already (the window closes)
                pass

    def _ratio(self) -> float:
        if self.ratio_override is not None:
            return self.ratio_override
        window = self.window()
        return window.devicePixelRatio() if window is not None else 1.0

    def _changed(self) -> None:
        if sip.isdeleted(self):
            # the window closed, and the drawing still tells its strips
            return
        self._sync_cursor()
        self.tipChanged.emit()
        self.update()

    def _sync_cursor(self) -> None:
        view = self.view
        if view is not None:
            self.setCursor(QCursor(view.cursor_shape()))

    def _to_parent(self, point: QPoint) -> QPoint:
        parent = self.parentItem()
        mapped = QPointF(point) if parent is None else parent.mapFromItem(self, QPointF(point))
        return mapped.toPoint()

    # -- painting ------------------------------------------------------------------------------------------------

    def paint(self, painter: QPainter | None) -> None:
        view = self.view
        if painter is None or view is None or self.width() <= 0:
            return
        view.mode = mode_of(self._dark)
        view.ratio = self._ratio()
        view.paint_strip(painter)

    # -- input ---------------------------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        view = self.view
        if event is None or view is None:
            return
        self.forceActiveFocus(Qt.FocusReason.MouseFocusReason)
        if event.button() == Qt.MouseButton.RightButton:
            # a context menu in Select, where a click picks the strip too
            if view.preview.mover is not None:
                view.preview.pick(self._index)
                position = event.position()
                self.contextRequested.emit(position.x(), position.y())
            event.accept()
            return
        view.mousePressEvent(event)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        view = self.view
        if event is not None and view is not None:
            view.mouseMoveEvent(event)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        view = self.view
        if event is not None and view is not None:
            view.mouseReleaseEvent(event)
            event.accept()

    def mouseUngrabEvent(self) -> None:
        """The window took the mouse away (e.g. it lost the focus) in the middle of a drag: back to where it was."""
        drawing = self._drawing
        if drawing is not None and drawing.dragging:
            drawing.cancel_drag()

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        view = self.view
        if event is None:
            return
        if view is None:
            event.ignore()
            return
        view.wheelEvent(event)

    def hoverEnterEvent(self, event: QHoverEvent | None) -> None:
        view = self.view
        if event is None or view is None:
            return
        self._hovered = True
        view.hovered_by_mouse = True
        view.hover_point(event.position())
        view.update()
        self.hoveredChanged.emit()

    def hoverMoveEvent(self, event: QHoverEvent | None) -> None:
        view = self.view
        if event is not None and view is not None:
            view.hover_point(event.position())

    def hoverLeaveEvent(self, event: QHoverEvent | None) -> None:
        view = self.view
        if view is None:
            return
        self._hovered = False
        view.hovered_by_mouse = False
        view.hover_point(None)
        view.update()
        self.hoveredChanged.emit()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        drawing = self._drawing
        if event is None:
            return
        event.setAccepted(drawing is not None and drawing.key(self._index, event))

    def _focus_changed(self) -> None:
        view = self.view
        if view is not None:
            view.focused = self.hasActiveFocus()
            view.update()

    def _focus_requested(self, index: int) -> None:
        if index == self._index:
            self.forceActiveFocus(Qt.FocusReason.TabFocusReason)


class PanelItem(QQuickPaintedItem):
    """The panel of the device behind the strips: dark, lit from above, with a frame while the drawing simulates."""

    drawingChanged = pyqtSignal(arguments=[])
    darkChanged = pyqtSignal(arguments=[])

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self._drawing: Drawing | None = None
        self._dark = True
        self.setAntialiasing(True)

    @pyqtProperty(QObject, notify=drawingChanged)  # pyright: ignore[reportArgumentType]
    def drawing(self) -> QObject | None:  # pyright: ignore[reportRedeclaration]
        return self._drawing

    @drawing.setter
    def drawing(self, drawing: QObject | None) -> None:
        if drawing is not self._drawing:
            self._drawing = drawing if isinstance(drawing, Drawing) else None
            if self._drawing is not None:
                self._drawing.panelChanged.connect(self.update)
            self.drawingChanged.emit()
            self.update()

    @pyqtProperty(bool, notify=darkChanged)
    def dark(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._dark

    @dark.setter
    def dark(self, dark: bool) -> None:
        if dark != self._dark:
            self._dark = dark
            self.darkChanged.emit()
            self.update()

    def paint(self, painter: QPainter | None) -> None:
        """The panel of the device (dark, lit from above, a bevel at the top edge), and the place of a dragged strip."""
        drawing = self._drawing
        if painter is None or drawing is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        origin, scale = drawing.panel_geometry()
        painter.translate(origin)
        painter.scale(scale, scale)
        panel = QRectF(QPointF(), PANEL).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(panel.topLeft(), panel.bottomLeft())
        gradient.setColorAt(0, QColor(HW.panel_top))
        gradient.setColorAt(1, QColor(HW.panel_bottom))
        painter.setBrush(gradient)
        accent = QColor(THEMES[mode_of(self._dark)].accent)
        painter.setPen(QPen(accent, 4) if drawing.simulating else QPen(QColor(HW.panel_edge), 1))
        painter.drawRoundedRect(panel, PANEL_RADIUS, PANEL_RADIUS)
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        painter.drawLine(
            QPointF(panel.left() + PANEL_RADIUS, panel.top() + 1.5),
            QPointF(panel.right() - PANEL_RADIUS, panel.top() + 1.5),
        )
        if drawing.dragTarget >= 0:
            # where the strip goes when it is let go: an empty place in the row
            place = QRectF(QPointF(slot_position(drawing.dragTarget)), QSizeF(WIDTH, HEIGHT)).adjusted(3, 3, -3, -3)
            fill = QColor(accent)
            fill.setAlpha(40)
            painter.setBrush(fill)
            painter.setPen(QPen(accent, 2, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(place, STRIP_RADIUS, STRIP_RADIUS)


class PartItem(QQuickPaintedItem):
    """A part of a strip (the encoder, the display, the buttons, or the fader) of a `PartPreviewModel`, cut out."""

    modelChanged = pyqtSignal(arguments=[])
    darkChanged = pyqtSignal(arguments=[])
    cornersChanged = pyqtSignal(arguments=[])

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self._model: PartPreviewModel | None = None
        self._dark = True
        self._card = QColor("transparent")
        self._edge = QColor("transparent")
        self._radius = 8.0
        self.setAntialiasing(True)

    @pyqtProperty(QObject, notify=modelChanged)  # pyright: ignore[reportArgumentType]
    def model(self) -> QObject | None:  # pyright: ignore[reportRedeclaration]
        """The `PartPreviewModel` it draws."""
        return self._model

    @model.setter
    def model(self, model: QObject | None) -> None:
        if model is not self._model:
            if self._model is not None:
                self._model.view.changed = lambda: None
            self._model = model if isinstance(model, PartPreviewModel) else None
            if self._model is not None:
                self._model.view.changed = self.update
                self.setImplicitWidth(self._model.pixel_width)
                self.setImplicitHeight(self._model.pixel_height)
            self.modelChanged.emit()
            self.update()

    @pyqtProperty(bool, notify=darkChanged)
    def dark(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._dark

    @dark.setter
    def dark(self, dark: bool) -> None:
        if dark != self._dark:
            self._dark = dark
            self.darkChanged.emit()
            self.update()

    @pyqtProperty(QColor, notify=cornersChanged)
    def cardColor(self) -> QColor:  # pyright: ignore[reportRedeclaration]
        """The color of the card it sits on: the corners outside the rounded edge are painted in it."""
        return self._card

    @cardColor.setter
    def cardColor(self, color: QColor) -> None:
        self._card = QColor(color)
        self.cornersChanged.emit()
        self.update()

    @pyqtProperty(QColor, notify=cornersChanged)
    def edgeColor(self) -> QColor:  # pyright: ignore[reportRedeclaration]
        """The color of the thin edge around the cut."""
        return self._edge

    @edgeColor.setter
    def edgeColor(self, color: QColor) -> None:
        self._edge = QColor(color)
        self.cornersChanged.emit()
        self.update()

    @pyqtProperty(float, notify=cornersChanged)
    def cornerRadius(self) -> float:  # pyright: ignore[reportRedeclaration]
        return self._radius

    @cornerRadius.setter
    def cornerRadius(self, radius: float) -> None:
        self._radius = radius
        self.cornersChanged.emit()
        self.update()

    def paint(self, painter: QPainter | None) -> None:
        model = self._model
        if painter is None or model is None:
            return
        view = model.view
        view.mode = mode_of(self._dark)
        window = self.window()
        view.ratio = window.devicePixelRatio() if window is not None else 1.0
        painter.save()
        painter.translate(model.offset)
        view.paint_strip(painter)
        painter.restore()
        # the corners of the cut: rounded, on the card, with a thin edge
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        whole = QPainterPath()
        whole.addRect(QRectF(0, 0, self.width(), self.height()))
        inside = QRectF(0, 0, self.width(), self.height()).adjusted(0.5, 0.5, -0.5, -0.5)
        rounded = QPainterPath()
        rounded.addRoundedRect(inside, self._radius, self._radius)
        painter.fillPath(whole.subtracted(rounded), self._card)
        painter.setPen(QPen(self._edge, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(rounded)


def register_types() -> None:
    """Registers the items and the models for QML as `XTouch.Device` 1.0; once, as registrations are for the process."""
    global _registered
    if _registered:
        return
    _registered = True
    for kind, name in ((StripItem, "StripItem"), (PanelItem, "PanelItem"), (PartItem, "PartItem")):
        qmlRegisterType(kind, URI, 1, 0, name)
