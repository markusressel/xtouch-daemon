"""
The splitter between the drawing of the device and the slots below it, with a grip on its handle.
"""

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import QSplitter, QSplitterHandle

from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.gui.qt.theme.tokens import Space

EDITOR_MIN_HEIGHT = 160
"""What is below the drawing keeps room for a few rows when the drawing is dragged large."""
GRIP = (36, 4)
"""The grip on the handle between the preview and the editor: a short bar that shows it can be dragged."""


class GripHandle(QSplitterHandle):
    """The handle between the preview and the editor, with a grip in the middle, brighter under the mouse."""

    def __init__(self, orientation: Qt.Orientation, parent: PreviewSplitter):
        super().__init__(orientation, parent)
        self.owner = parent
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setToolTip("Drag to make the strips larger or smaller")
        self.move_to: QMouseEvent | None = None
        """The last move of the mouse that the handle has not followed yet."""

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        super().mousePressEvent(event)
        self.owner.held.emit(True)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        """
        Follows the mouse once for all the moves that came in together: each step lays out the window again, and a
        fast mouse sends more of them than the screen shows.
        """
        assert event is not None
        if self.move_to is None:
            QTimer.singleShot(0, self._follow)
        self.move_to = event.clone()

    def _follow(self) -> None:
        event, self.move_to = self.move_to, None
        if event is not None:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        self._follow()
        super().mouseReleaseEvent(event)
        self.owner.held.emit(False)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = current_colors()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors.text_muted if self.underMouse() else colors.control_border))
        width, height = GRIP
        grip = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
        painter.drawRoundedRect(grip, height / 2, height / 2)


class PreviewSplitter(QSplitter):
    """The preview above, the editor below, and a handle with a grip between them."""

    held = pyqtSignal(bool, arguments=["held"])
    """The handle was pressed (True) or let go (False)."""

    def __init__(self):
        super().__init__(Qt.Orientation.Vertical)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(Space.M)

    def createHandle(self) -> QSplitterHandle:
        return GripHandle(self.orientation(), self)

    @property
    def share(self) -> float:
        """The share of the height the preview has."""
        top, bottom = self.sizes()
        return top / (top + bottom)

    @share.setter
    def share(self, share: float) -> None:
        total = sum(self.sizes())
        top = round(total * share)
        self.setSizes([top, total - top])
