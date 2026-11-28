"""
The tip of what is under the mouse, at once and in the footer: a tooltip takes a while and is easily missed, so its
first paragraph shows in place of the status line while the mouse is on an item that has one (or inside one). An item
has a tip as its property `tip` (`IconButton`), or as the `ToolTip.text` of Qt's controls.
"""

from collections.abc import Callable

from PyQt6.QtCore import QEvent, QObject, QPointF, QTimer
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtQuick import QQuickItem, QQuickWindow


def item_at(item: QQuickItem, point: QPointF) -> QQuickItem | None:
    """The topmost visible item under `point` (in the coordinates of `item`), `item` itself if none of its children."""
    for child in sorted(item.childItems(), key=lambda child: child.z(), reverse=True):
        if not child.isVisible() or child.opacity() <= 0:
            continue
        found = item_at(child, child.mapFromItem(item, point))
        if found is not None:
            return found
    return item if item.contains(point) else None


def tip_of(item: QQuickItem) -> str:
    """The tip of `item` alone: its property `tip`, or the text of its `ToolTip`; "" for none."""
    tip = item.property("tip")
    if isinstance(tip, str) and tip:
        return tip
    for child in item.children():
        meta = child.metaObject()
        if meta is not None and (meta.className() or "").endswith("ToolTipAttached"):
            text = child.property("text")
            if isinstance(text, str) and text:
                return text
    return ""


def first_paragraph(tip: str) -> str:
    return " ".join(tip.split("\n\n")[0].split())


class HoverTips(QObject):
    """Tells `show` the first paragraph of the tip under the mouse of `window` ("" for none)."""

    def __init__(self, window: QQuickWindow, show: Callable[[str], None]) -> None:
        super().__init__(window)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.window = window
        self.show = show
        self.point: QPointF | None = None
        self.timer = QTimer(self)
        """Shows the tip after the mouse stopped moving over the item: moves come in dozens."""
        self.timer.setSingleShot(True)
        self.timer.setInterval(0)
        self.timer.timeout.connect(self._show)
        window.installEventFilter(self)  # pyright: ignore[reportArgumentType]

    def stop(self) -> None:
        self.window.removeEventFilter(self)  # pyright: ignore[reportArgumentType]

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        assert event is not None
        if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            self.point = event.position()
            self.timer.start()
        elif event.type() == QEvent.Type.Leave:
            self.point = None
            self.timer.start()
        return False

    def tip_at(self, point: QPointF) -> str:
        """The first paragraph of the tip of the item under `point`, or of the next of its parents that has one."""
        root = self.window.contentItem()
        assert root is not None
        item = item_at(root, point)
        while item is not None:
            if tip := tip_of(item):
                return first_paragraph(tip)
            item = item.parentItem()
        return ""

    def _show(self) -> None:
        self.show(self.tip_at(self.point) if self.point is not None else "")
