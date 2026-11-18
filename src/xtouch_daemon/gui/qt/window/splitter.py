"""
The splitter between the two panes of a page (a list or the slots on the left, what is picked on the right), with a
grip on its handle. Where the handle was left is kept for the next start.
"""

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QResizeEvent
from PyQt6.QtWidgets import QSplitter, QSplitterHandle, QWidget

from xtouch_daemon.gui.qt.theme.settings import load_split, save_split
from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.gui.qt.theme.tokens import Space

GRIP = (4, 36)
"""The grip on the handle: a short upright bar that shows it can be dragged."""
LEFT_SHARE = 0.3
"""The share of the width the left pane has until the handle is dragged: most of it is for what is picked."""


class GripHandle(QSplitterHandle):
    """The handle between the panes, with a grip in the middle, brighter under the mouse."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter):
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setToolTip("Drag to give either side more room")
        self.move_to: QMouseEvent | None = None
        """The last move of the mouse that the handle has not followed yet."""

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        """
        Follows the mouse once for all the moves that came in together: each step lays out the page again, and a
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
        splitter = self.splitter()
        if isinstance(splitter, PaneSplitter):
            splitter.keep()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = current_colors()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors.text_muted if self.underMouse() else colors.control_border))
        width, height = GRIP
        grip = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
        painter.drawRoundedRect(grip, width / 2, width / 2)


class PaneSplitter(QSplitter):
    """
    Two panes side by side and a handle with a grip between them. The left pane keeps its share of the width when
    the page gets wider or narrower; `name` keeps it for the next start. Until the handle is dragged it is
    `LEFT_SHARE`.
    """

    def __init__(self, name: str, left: QWidget, right: QWidget):
        super().__init__(Qt.Orientation.Horizontal)
        self.name = name
        self.setChildrenCollapsible(False)
        self.setHandleWidth(Space.M)
        self.addWidget(left)
        self.addWidget(right)
        self.wanted = load_split(name) or LEFT_SHARE
        """The share of the width the left pane has."""
        self.splitterMoved.connect(self._moved)

    def createHandle(self) -> QSplitterHandle:
        return GripHandle(self.orientation(), self)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self.share = self.wanted

    def _moved(self) -> None:
        """The handle moves: the new share stays (`keep` keeps it for the next start, once it is let go)."""
        self.wanted = self.share

    def keep(self) -> None:
        """
        The handle was let go: its share is kept for the next start. Not on every move: writing the settings takes
        tens of milliseconds (QSettings writes its file each time), which made dragging lag.
        """
        save_split(self.name, self.wanted)

    @property
    def share(self) -> float:
        """The share of the width the left pane has."""
        left, right = self.sizes()
        return left / (left + right)

    @share.setter
    def share(self, share: float) -> None:
        total = max(0, self.width() - self.handleWidth())
        left = round(total * share)
        self.setSizes([left, total - left])
