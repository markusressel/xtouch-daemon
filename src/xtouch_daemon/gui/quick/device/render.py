"""
The drawing of the device painted offscreen into an image, without a window: for the screenshots of the documentation
(`scripts/screenshot.py`) and for tests that look at pixels. A `Scene` is a `Drawing` with the items of QML that paint
it, at a scale and a pixel ratio of your choice, painted as the window paints them.
"""

from math import ceil

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPainter

from xtouch_daemon.gui.domain.looks import StripFace
from xtouch_daemon.gui.quick.device.drawing import Drawing
from xtouch_daemon.gui.quick.device.geometry import PANEL
from xtouch_daemon.gui.quick.device.items import PanelItem, StripItem
from xtouch_daemon.hardware import protocol


class Scene:
    """The panel and its 8 strips at `scale` (pixels per logical unit), for a window with the pixel ratio `ratio`."""

    def __init__(self, scale: float = 1.0, ratio: float = 1.0, dark: bool = True) -> None:
        self.ratio = ratio
        self.drawing = Drawing()
        self.panel = PanelItem()
        self.panel.dark = dark
        self.panel.drawing = self.drawing
        self.size = QSize(ceil(PANEL.width() * scale), ceil(PANEL.height() * scale))
        self.panel.setWidth(self.size.width())
        self.panel.setHeight(self.size.height())
        self.strips: list[StripItem] = []
        for index in range(protocol.STRIPS):
            item = StripItem()
            item.ratio_override = ratio
            item.dark = dark
            item.stripIndex = index
            item.drawing = self.drawing
            self.strips.append(item)
        self.drawing.setSize(self.size.width(), self.size.height())
        self.place()

    def place(self) -> None:
        """Puts the strips where the drawing has them (after a new size, or while one is dragged)."""
        drawing = self.drawing
        for item, point in zip(self.strips, drawing.places(), strict=True):
            item.setX(drawing.origin.x() + point.x() * drawing.scale)
            item.setY(drawing.origin.y() + point.y() * drawing.scale)
            item.setWidth(drawing.stripWidth)
            item.setHeight(drawing.stripHeight)

    def show(self, faces: tuple[StripFace, ...], selected: int | None = None, simulating: bool = False) -> None:
        self.drawing.show_faces(faces, selected, simulating)

    def _canvas(self, width: float, height: float) -> QImage:
        image = QImage(ceil(width * self.ratio), ceil(height * self.ratio), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(self.ratio)
        image.fill(QColor(Qt.GlobalColor.transparent))
        return image

    def image(self) -> QImage:
        """The whole drawing: the panel with its strips."""
        image = self._canvas(self.size.width(), self.size.height())
        painter = QPainter(image)
        self.panel.paint(painter)
        for item in self.strips:
            painter.save()
            painter.translate(item.x(), item.y())
            item.paint(painter)
            painter.restore()
        painter.end()
        return image

    def strip_image(self, index: int) -> QImage:
        """One strip alone, on a transparent background; `devicePixelRatio` is pixels per logical unit of the strip."""
        item = self.strips[index]
        image = self._canvas(item.width(), item.height())
        painter = QPainter(image)
        item.paint(painter)
        painter.end()
        # as the tests and the screenshots want it: a point in logical units of the strip is `point * ratio`
        image.setDevicePixelRatio(self.ratio * self.drawing.scale)
        return image


def render_drawing(
    faces: tuple[StripFace, ...],
    scale: float = 1.0,
    ratio: float = 1.0,
    dark: bool = True,
    selected: int | None = None,
    simulating: bool = False,
) -> QImage:
    """The drawing of the device showing `faces`, at `scale` (pixels per logical unit) and the pixel ratio `ratio`."""
    scene = Scene(scale, ratio, dark)
    scene.show(faces, selected, simulating)
    return scene.image()


def render_strip(face: StripFace, scale: float = 1.0, ratio: float = 1.0, dark: bool = True) -> QImage:
    """One strip showing `face`, as in the drawing, at `scale` and `ratio`."""
    scene = Scene(scale, ratio, dark)
    scene.show((face,) * protocol.STRIPS)
    return scene.strip_image(0)
