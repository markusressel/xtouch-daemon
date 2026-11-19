"""
Depth, as Android has it: a scrolled list or page casts a soft shadow at an edge where more of it is hidden (at the
top once it is scrolled down, at the bottom while there is more below), and a popover a shadow on what is under it.
Style sheets have no shadows; a QGraphicsEffect on every card would render each of them again on every paint (and
make scrolling and the handles slow), so the cards have none.
"""

from PyQt6.QtCore import QEvent, QObject, QPointF, QSize, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPaintEvent, QPixmap
from PyQt6.QtWidgets import QAbstractScrollArea, QGraphicsDropShadowEffect, QWidget

from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.gui.qt.theme.tokens import Space

EDGE = Space.S
"""How far the shadow at an edge reaches into the list."""
FADE = Space.XL
"""How far the ends of a shadow fade out to the sides: no hard corners where the cards have round ones."""
FALLOFF = ((0.0, 1.0), (0.25, 0.55), (0.6, 0.18), (1.0, 0.0))
"""How the shadow fades from the edge into the list (where, how dark): eased, so the edge reads as no line."""


def _dark() -> bool:
    return QColor(current_colors().surface).lightness() < 128


def _shadow(alpha_dark: int, alpha_light: int) -> QColor:
    return QColor(0, 0, 0, alpha_dark if _dark() else alpha_light)


class _Edge(QWidget):
    """The shadow along one edge of the visible part of a list: dark at the edge, gone `EDGE` into it."""

    def __init__(self, area: QAbstractScrollArea, top: bool) -> None:
        # a child of the area, not of its viewport: what scrolls the viewport would move it along
        super().__init__(area)  # pyright: ignore[reportArgumentType]
        self.top = top
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        # drawn apart first: fading its ends on the widget itself would erase what is under it
        ratio = self.devicePixelRatioF()
        shadow = QPixmap(QSize(round(self.width() * ratio), round(self.height() * ratio)))
        shadow.setDevicePixelRatio(ratio)
        shadow.fill(Qt.GlobalColor.transparent)
        painter = QPainter(shadow)
        start, end = (0.0, float(self.height())) if self.top else (float(self.height()), 0.0)
        down = QLinearGradient(QPointF(0, start), QPointF(0, end))
        dark = _shadow(70, 32)
        for at, share in FALLOFF:
            down.setColorAt(at, QColor(0, 0, 0, round(dark.alpha() * share)))
        painter.fillRect(self.rect(), down)
        fade = min(FADE / max(self.width(), 1), 0.5)
        across = QLinearGradient(QPointF(0, 0), QPointF(self.width(), 0))
        across.setColorAt(0, QColor(0, 0, 0, 0))
        across.setColorAt(fade, QColor(0, 0, 0, 255))
        across.setColorAt(1 - fade, QColor(0, 0, 0, 255))
        across.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.fillRect(self.rect(), across)
        painter.end()
        QPainter(self).drawPixmap(0, 0, shadow)


class _ScrollShadows(QObject):
    """Shows the shadows of `area` where it has more than it shows, and keeps them on the edges of its viewport."""

    def __init__(self, area: QAbstractScrollArea) -> None:
        # a child of the area: gone with it
        super().__init__(area)  # pyright: ignore[reportArgumentType]
        self.area = area
        self.edges = (_Edge(area, top=True), _Edge(area, top=False))
        bar = area.verticalScrollBar()
        assert bar is not None
        bar.valueChanged.connect(self.update)
        bar.rangeChanged.connect(self.update)
        viewport = area.viewport()
        assert viewport is not None
        viewport.installEventFilter(self)  # pyright: ignore[reportArgumentType]
        self.update()

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if event is not None and event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
            self.update()
        return False

    def update(self) -> None:
        bar = self.area.verticalScrollBar()
        viewport = self.area.viewport()
        assert bar is not None
        assert viewport is not None
        frame = viewport.geometry()
        top, bottom = self.edges
        top.setGeometry(frame.left(), frame.top(), frame.width(), EDGE)
        bottom.setGeometry(frame.left(), frame.bottom() + 1 - EDGE, frame.width(), EDGE)
        top.setVisible(bar.value() > bar.minimum())
        bottom.setVisible(bar.value() < bar.maximum())
        for edge in self.edges:
            edge.raise_()


def scroll_shadows(area: QAbstractScrollArea) -> None:
    """Gives `area` the shadows at its edges where it has more than it shows."""
    _ScrollShadows(area)


def lift(widget: QWidget) -> None:
    """A shadow under `widget` (a popover), as if it were above the window."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(3 * Space.S)
    shadow.setOffset(0, Space.XS)
    shadow.setColor(_shadow(140, 60))
    widget.setGraphicsEffect(shadow)
