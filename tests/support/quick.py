"""
Driving the window in Qt Quick from a test: find an item by its `objectName`, click it, type into it, press keys.
QML items have no widgets to look at; a test names what it needs in the QML (`objectName: "rail_slots"`).
"""

from collections.abc import Callable, Iterator
from typing import Any

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QKeyEvent
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickItem, QQuickWindow
from PyQt6.QtTest import QTest
from pytestqt.qtbot import QtBot

from xtouch_daemon.gui.quick.app import App

MOUSE: Any = QTest
"""QTest, for the clicks on a QWindow: the stubs of PyQt6 type its functions for widgets only."""


class Ui:
    """The window of a test: its `app` (the backends), the QML `window`, and ways to drive it."""

    def __init__(self, qtbot: QtBot, app: App, engine: QQmlApplicationEngine, window: QQuickWindow) -> None:
        self.qtbot = qtbot
        self.app = app
        self.engine = engine
        self.window = window

    # -- finding --------------------------------------------------------------------------------------------------

    def all_items(self) -> Iterator[QQuickItem]:
        """Every item of the window, through the tree of items (delegates of a Repeater are no QObject children),
        also those of popups (they live in the overlay of the window)."""
        root = self.window.contentItem()
        assert root is not None
        stack = [root.parentItem() or root]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(reversed(item.childItems()))

    def find(self, name: str) -> QQuickItem | None:
        """The first item named `name`, or None."""
        return next((item for item in self.all_items() if item.objectName() == name), None)

    def item(self, name: str) -> QQuickItem:
        """The item named `name`; fails the test without one."""
        found = self.find(name)
        assert found is not None, f"no item named {name!r}"
        return found

    def items(self, name: str) -> list[QQuickItem]:
        """Every item named `name`, e.g. the delegates of a list."""
        return [item for item in self.all_items() if item.objectName() == name and item.isVisible()]

    def shows(self, name: str) -> bool:
        """Whether the item named `name` is there and visible (and all items above it are)."""
        found = self.find(name)
        return found is not None and found.isVisible() and found.opacity() > 0

    @staticmethod
    def value(item: QObject, name: str) -> Any:
        return item.property(name)

    def text(self, name: str) -> str:
        return str(self.item(name).property("text"))

    # -- doing ----------------------------------------------------------------------------------------------------

    def center(self, item: QQuickItem) -> QPoint:
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
        return point.toPoint()

    def click(
        self, target: str | QQuickItem, button: Qt.MouseButton = Qt.MouseButton.LeftButton, at: QPointF | None = None
    ) -> None:
        """Clicks the middle of an item (or `at`, in its coordinates) with the mouse, as a user does."""
        item = self.item(target) if isinstance(target, str) else target
        assert item.isVisible(), f"{item.objectName()!r} does not show"
        point = self.center(item) if at is None else item.mapToScene(at).toPoint()
        MOUSE.mouseClick(self.window, button, Qt.KeyboardModifier.NoModifier, point)
        self.settle()

    def double_click(self, target: str | QQuickItem) -> None:
        item = self.item(target) if isinstance(target, str) else target
        MOUSE.mouseDClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.center(item))
        self.settle()

    def key(self, key: Qt.Key, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
        """Presses a key in the window, at the item with the focus."""
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(self.window, QKeyEvent(kind, key, modifiers))
        self.settle()

    def type(self, text: str) -> None:
        """Types `text` into the item with the focus."""
        for char in text:
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QGuiApplication.sendEvent(self.window, QKeyEvent(kind, 0, Qt.KeyboardModifier.NoModifier, char))
        self.settle()

    def focus(self, target: str | QQuickItem) -> None:
        item = self.item(target) if isinstance(target, str) else target
        item.forceActiveFocus()
        self.settle()

    def settle(self) -> None:
        """Lets QML do what is pending: bindings, layouts, zero-length animations."""
        for _ in range(3):
            QGuiApplication.processEvents()

    def wait_until(self, check: Callable[[], bool], timeout: int = 2000) -> None:
        self.qtbot.waitUntil(check, timeout=timeout)

    def grab(self) -> QImage:
        """The window as it shows now."""
        self.settle()
        return self.window.grabWindow()
