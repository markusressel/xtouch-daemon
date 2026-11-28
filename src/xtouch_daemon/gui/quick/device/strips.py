"""
The strips of the drawing, painted by the code of the widgets: `gui/qt/preview/strip_view.py` paints a strip in
`StripView` (a `QWidget`, which only supplies its font, whether it has the focus, whether the mouse is over it and the
pixel ratio). A `PaintedStrip` is such a view that is never shown: the items of QML hold one each and paint it with
their own painter, with the pixmap caches of the widgets, so the picture is the same one.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QPainter
from PyQt6.QtWidgets import QWidget

from xtouch_daemon.gui.qt.preview.painting import draw
from xtouch_daemon.gui.qt.preview.strip_view import LIFTED_OPACITY, StripView

if TYPE_CHECKING:
    from xtouch_daemon.gui.qt.preview.panel import Hand
    from xtouch_daemon.gui.qt.preview.strip_view import Mover


class StripSource(Protocol):
    """What a strip is drawn in (the `StripHost` of the widgets): the drawing of the device, or a part of a strip."""

    scale: float
    blink: bool
    now: float

    @property
    def hand(self) -> Hand | None: ...

    @property
    def mover(self) -> Mover | None: ...

    @property
    def resizing(self) -> bool: ...

    def pick(self, index: int) -> None: ...

    def key(self, index: int, event: QKeyEvent) -> bool: ...


class HostWidget(QWidget):
    """The `StripHost` a `StripView` wants as its parent: a widget that is never shown, passing on to the source."""

    def __init__(self, source: StripSource) -> None:
        super().__init__()
        self.source = source

    @property
    def scale(self) -> float:
        return self.source.scale

    @property
    def blink(self) -> bool:
        return self.source.blink

    @property
    def now(self) -> float:
        return self.source.now

    @property
    def hand(self) -> Hand | None:
        return self.source.hand

    @property
    def mover(self) -> Mover | None:
        return self.source.mover

    @property
    def resizing(self) -> bool:
        return self.source.resizing

    def pick(self, index: int) -> None:
        self.source.pick(index)

    def key(self, index: int, event: QKeyEvent) -> bool:
        return self.source.key(index, event)


class PaintedStrip(StripView):
    """A `StripView` that an item of QML paints and takes the input for (see the module)."""

    def __init__(self, host: HostWidget, index: int) -> None:
        super().__init__(host, index)  # pyright: ignore[reportArgumentType]
        self.focused = False
        """Whether the item has the focus: the dotted outline."""
        self.hovered_by_mouse = False
        """Whether the mouse is over the item."""
        self.ratio = 1.0
        """The device pixel ratio of the window that shows it."""
        self.tip = ""
        """The tooltip it has now (the strip's, or in Play the part's under the mouse)."""
        self.changed: Callable[[], None] = lambda: None
        """Called when the strip must be painted again."""
        self.to_parent: Callable[[QPoint], QPoint] = lambda point: point
        """Where a point of the strip is in the drawing (`mapToParent` of the widget)."""

    # -- what the widget asks of the toolkit ---------------------------------------------------------------------

    def hasFocus(self) -> bool:
        return self.focused

    def underMouse(self) -> bool:
        return self.hovered_by_mouse

    def devicePixelRatioF(self) -> float:
        return self.ratio

    def setToolTip(self, a0: str | None) -> None:
        self.tip = a0 or ""
        self.changed()

    def update(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        self.changed()

    def mapToParent(self, a0: QPoint) -> QPoint:  # pyright: ignore[reportIncompatibleMethodOverride]
        return self.to_parent(a0)

    def setCursor(self, a0: object) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """The item sets its own cursor from `cursor_shape`."""

    # -- painting (what `StripView.paintEvent` does) ---------------------------------------------------------------

    def paint_strip(self, painter: QPainter) -> None:
        """The strip as the widget paints it, in the units of the item (pixels at the zoom of the window)."""
        scale, ratio = self.preview.scale, self.ratio
        self.moving_drawn = self._moving_key()
        key = (self._shown_key(), self.moving_drawn)
        if not self._current(self.picture, key, scale, ratio):
            self.picture = draw(key, scale, ratio, self._paint_picture)
        picture = self.picture
        assert picture is not None
        painter.save()
        painter.scale(scale, scale)
        if self.lifted:
            painter.setOpacity(LIFTED_OPACITY)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        picture.paint(painter)
        if self.preview.hand is not None:
            painter.setOpacity(1.0)
            self._paint_hand(painter)
        painter.restore()

    def cursor_shape(self) -> Qt.CursorShape:
        """The mouse cursor over it: an arrow in Play, a closed hand while it is lifted, else a pointing hand."""
        if self.preview.mover is None:
            return Qt.CursorShape.ArrowCursor
        return Qt.CursorShape.ClosedHandCursor if self.lifted else Qt.CursorShape.PointingHandCursor

    def hover_point(self, point: QPointF | None) -> None:
        """The mouse moved over the strip (None: left it)."""
        self._hover(None if point is None else point / self.preview.scale)
