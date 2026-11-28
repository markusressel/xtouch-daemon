"""
What the tests of the drawing of the device share: a fake daemon's live view, snapshots, a hand that records, and
ways to reach the drawing in the window.
"""

import dataclasses
import math

from PyQt6.QtCore import QPoint, QPointF, QSizeF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage
from PyQt6.QtQuick import QQuickItem, QQuickWindow
from pytestqt.qtbot import QtBot

from tests.gui.quick.conftest import MakeUi
from tests.support.gui import FakeLiveDaemon, strip_state
from tests.support.quick import MOUSE, Ui
from xtouch_daemon.gui.domain.looks import StripFace
from xtouch_daemon.gui.qt.preview.geometry import PANEL
from xtouch_daemon.gui.quick.device.drawing import Drawing
from xtouch_daemon.gui.quick.device.items import PanelItem, StripItem
from xtouch_daemon.gui.quick.device.panel import DevicePanel
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.live.messages import FEATURES, Snapshot, fingerprint


def device_of(ui: Ui) -> DevicePanel:
    panel = ui.app.device
    assert isinstance(panel, DevicePanel)
    return panel


def drawing_of(ui: Ui) -> Drawing:
    return device_of(ui).drawing


def snapshot(ui: Ui, **changes: object) -> Snapshot:
    """What a daemon with a device tells: 8 dark strips, and the features of this version."""
    config = device_of(ui).document.saved_config
    assert config is not None
    strips = tuple(strip_state() for _ in range(8))
    state = Snapshot(fingerprint(config), True, True, None, strips, features=FEATURES)
    return dataclasses.replace(state, **changes)  # pyright: ignore[reportArgumentType]


def live_ui(make_ui: MakeUi, daemon: FakeLiveDaemon, qtbot: object, **changes: object) -> Ui:
    """A window whose daemon told its first snapshot."""
    ui = make_ui(live_socket=daemon.path)
    ui.wait_until(lambda: bool(daemon.clients))
    daemon.send(snapshot(ui, **changes))
    ui.wait_until(lambda: ui.app.shell.live.snapshot is not None)
    ui.settle()
    return ui


def strip_item(ui: Ui, index: int) -> QQuickItem:
    return ui.item(f"strip_{index}")


class FakeHand:
    """A hand that records what the mouse did (the `Hand` of the drawing)."""

    def __init__(self) -> None:
        self.done: list[tuple[object, ...]] = []

    def touch(self, strip: int, touched: bool) -> None:
        self.done.append(("touch", strip, touched))

    def move(self, strip: int, fraction: float, hand: bool = True) -> None:
        self.done.append(("move", strip, round(fraction, 2), hand))

    def press(self, strip: int, button: Button, pressed: bool) -> None:
        self.done.append(("press", strip, button, pressed))

    def turn(self, strip: int, steps: int) -> None:
        self.done.append(("turn", strip, steps))

    def push(self, strip: int, pressed: bool) -> None:
        self.done.append(("push", strip, pressed))


def configured(face: StripFace) -> StripFace:
    """The face of a strip as one the daemon tells about (not drawn fainter)."""
    return dataclasses.replace(face, look=dataclasses.replace(face.look, configured=True), live=True)


def pixel(image: QImage, point: QPointF) -> QColor:
    """The color at a point of the strip, in logical units, at any zoom and scale."""
    return image.pixelColor((point * image.devicePixelRatio()).toPoint())


class Stage:
    """
    The drawing in a bare window of Qt Quick, laid out like `DrawingStage.qml` does (no QML, no page): a window at the
    size of the panel at `scale`, 8 strips in it, and a mouse to drive them.
    """

    def __init__(self, qtbot: QtBot, scale: float = 1.0) -> None:
        self.window = QQuickWindow()
        self.drawing = Drawing()
        size = QSizeF(PANEL.width() * scale, PANEL.height() * scale)
        self.window.resize(math.ceil(size.width()), math.ceil(size.height()))
        root = self.window.contentItem()
        assert root is not None
        self.panel = PanelItem(root)
        self.panel.setWidth(self.window.width())
        self.panel.setHeight(self.window.height())
        self.panel.drawing = self.drawing
        self.strips: list[StripItem] = []
        for index in range(protocol.STRIPS):
            item = StripItem(root)
            item.stripIndex = index
            item.drawing = self.drawing
            self.strips.append(item)
        self.drawing.layoutChanged.connect(self.place)
        self.drawing.positionsChanged.connect(self.place)
        self.drawing.setSize(self.window.width(), self.window.height())
        self.window.show()
        qtbot.waitExposed(self.window)

    def place(self) -> None:
        drawing = self.drawing
        for item, point in zip(self.strips, drawing.places(), strict=True):
            item.setX(drawing.origin.x() + point.x() * drawing.scale)
            item.setY(drawing.origin.y() + point.y() * drawing.scale)
            item.setWidth(drawing.stripWidth)
            item.setHeight(drawing.stripHeight)

    def at(self, index: int, point: QPointF) -> QPoint:
        """Where a point of the strip (in its logical units) is in the window."""
        # the point in pixels of the strip first, as the widgets' tests did: a pixel is what a mouse points at
        return self.strips[index].mapToScene(QPointF((point * self.drawing.scale).toPoint())).toPoint()

    def press(
        self, index: int, point: QPointF, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    ) -> None:
        MOUSE.mousePress(self.window, Qt.MouseButton.LeftButton, modifiers, self.at(index, point))
        QGuiApplication.processEvents()

    def move(self, index: int, point: QPointF) -> None:
        MOUSE.mouseMove(self.window, self.at(index, point))
        QGuiApplication.processEvents()

    def release(
        self, index: int, point: QPointF, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    ) -> None:
        MOUSE.mouseRelease(self.window, Qt.MouseButton.LeftButton, modifiers, self.at(index, point))
        QGuiApplication.processEvents()

    def click(self, index: int, point: QPointF, button: Qt.MouseButton = Qt.MouseButton.LeftButton) -> None:
        MOUSE.mouseClick(self.window, button, Qt.KeyboardModifier.NoModifier, self.at(index, point))
        QGuiApplication.processEvents()

    def image(self) -> QImage:
        return self.window.grabWindow()

    def close(self) -> None:
        self.window.close()
        self.window.deleteLater()
