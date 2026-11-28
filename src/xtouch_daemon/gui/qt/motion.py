"""
Motion in the GUI (see `docs/development/design/motion.md`): changes of the look fade (`fading`), rows that come and
go grow and shrink (`reveal`). The durations are the tokens of `Motion`; `Motion.enabled = False` makes every change
happen at once (in tests and screenshots).
"""

import contextlib
from collections.abc import Iterator

from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QObject, QPoint, QRect, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPixmap, QRegion
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

from xtouch_daemon.gui.qt.theme.tokens import Motion

UNBOUNDED = (1 << 24) - 1
"""The largest size of a widget (Qt's `QWIDGETSIZE_MAX`): no bound."""
REVEAL = "reveal"
"""The object name of the animation of `reveal`, a child of the widget it moves."""

OUT = 0.35
"""The part of a fade through in which the old picture fades out; the new look fades in in the rest (as Material's)."""

_fading: list[QWidget] = []
"""The widgets whose change fades right now: a change inside one of them is part of its fade."""


def moving(widget: QWidget) -> bool:
    """
    Whether a change of `widget` moves: motion is on, and it shows, in a window that shows and draws (a widget with
    its updates off draws nothing, so its picture would be empty).
    """
    window = widget.window()
    return (
        Motion.enabled
        and widget.isVisible()
        and widget.updatesEnabled()
        and not widget.size().isEmpty()
        and window is not None
        and not window.isMinimized()
    )


def picture_of(widget: QWidget) -> QPixmap:
    """
    What `widget` shows, with its children, on nothing: `grab()` would paint the background of the window behind it,
    a box around a pill with round corners.
    """
    ratio = widget.devicePixelRatioF()
    picture = QPixmap(max(1, round(widget.width() * ratio)), max(1, round(widget.height() * ratio)))
    picture.setDevicePixelRatio(ratio)
    picture.fill(Qt.GlobalColor.transparent)
    widget.render(picture, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return picture


class Fade(QWidget):
    """
    The old picture of a widget over its new look, fading out; gone at the end. With a color `behind` (what the widget
    sits on) it fades through: the old picture fades out on that color, then the color fades away to the new look, so
    the two never show at once (texts that change would show both, on top of each other).
    """

    def __init__(
        self,
        over: QWidget,
        picture: QPixmap,
        through_resize: bool = False,
        behind: QColor | None = None,
        at: QRect | None = None,
    ) -> None:
        """`at`: a part of `over` (e.g. a row of a list) it covers, where it stays whatever `over` does."""
        super().__init__(over)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.picture = picture
        self.behind = behind
        self.progress = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        size = picture.deviceIndependentSize().toSize()
        self.setGeometry(0, 0, size.width(), size.height())
        if at is not None:
            self.setGeometry(at)
        elif through_resize:
            self.resize(over.size().expandedTo(size))
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(Motion.FADE if behind is None else Motion.RESIZE)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._fade)
        self.animation.finished.connect(self.deleteLater)
        # a widget that changes its size moves what it shows: the old picture would show twice, apart (unless what
        # it shows stays where it is, e.g. rows from the top)
        self.through_resize = through_resize
        if at is None:
            over.installEventFilter(self)
        self.show()
        self.raise_()
        self.animation.start()

    @property
    def opacity(self) -> float:
        """Of the old picture: it fades out over the whole fade, or over its first part (`OUT`) to fade through."""
        return 1.0 - self.progress if self.behind is None else max(0.0, 1.0 - self.progress / OUT)

    @property
    def cover(self) -> float:
        """Of the color behind, over the new look: whole while the old picture fades out, then fading out itself."""
        return 0.0 if self.behind is None else min(1.0, (1.0 - self.progress) / (1.0 - OUT))

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is None or a1.type() != QEvent.Type.Resize or self.animation.state() == QAbstractAnimation.State.Stopped:
            return False
        if self.through_resize:
            # the color behind covers the rows that come too, until they fade in
            over = self.parentWidget()
            if over is not None:
                self.resize(over.size())
        else:
            self.animation.stop()
            self.hide()
            self.deleteLater()
        return False

    def _fade(self, progress: float) -> None:
        self.progress = progress
        self.update()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        painter = QPainter(self)
        if self.behind is not None:
            painter.setOpacity(self.cover)
            painter.fillRect(self.rect(), self.behind)
        painter.setOpacity(self.opacity)
        painter.drawPixmap(0, 0, self.picture)
        painter.end()


@contextlib.contextmanager
def fading(widget: QWidget, through_resize: bool = False, behind: QColor | None = None) -> Iterator[None]:
    """
    Fades from what `widget` shows (with its children) to what it shows after the block: any change of its look, a
    color of the stylesheet, a text, another page. At once when it doesn't move (see `moving`) or is part of a fade
    already. The fade ends when the widget changes its size, unless `through_resize`: what it shows stays where it
    was (rows from the top that grow or shrink at the bottom). With the color `behind` it (what it sits on) it fades
    through, see `Fade`.
    """
    if not moving(widget) or any(outer is widget or outer.isAncestorOf(widget) for outer in _fading):
        yield
        return
    picture = picture_of(widget)
    _fading.append(widget)
    try:
        yield
    finally:
        _fading.remove(widget)
    if widget.isVisible():
        Fade(widget, picture, through_resize, behind)


def reveal(widget: QWidget, shown: bool) -> QVariantAnimation | None:
    """
    Shows or hides `widget` in its layout: it grows from no height to its own, or shrinks to none and hides, and fades
    in or out while it does, so what is around it moves along. At once while its parent doesn't move. The animation,
    None for none.
    """
    animation = widget.findChild(QVariantAnimation, REVEAL, Qt.FindChildOption.FindDirectChildrenOnly)
    running = animation is not None and animation.state() == QAbstractAnimation.State.Running
    heading = bool(animation.property("shown")) if animation is not None and running else not widget.isHidden()
    if heading == shown:
        return animation if running else None
    parent = widget.parentWidget()
    if animation is not None:
        animation.stop()
    if parent is None or not moving(parent):
        _settle(widget, shown)
        return None
    if animation is None:
        animation = QVariantAnimation(widget)
        animation.setObjectName(REVEAL)
        animation.setDuration(Motion.RESIZE)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(lambda height: _grow(widget, animation, height))
        animation.finished.connect(lambda: _settle(widget, bool(animation.property("shown"))))
    start = 0 if widget.isHidden() else widget.height()
    end = _height(widget, parent) if shown else 0
    animation.setProperty("shown", shown)
    animation.setStartValue(start)
    animation.setEndValue(end)
    widget.setMaximumHeight(start)
    if widget.graphicsEffect() is None:
        # its own, for the time of the reveal: a widget has one effect at most
        effect = QGraphicsOpacityEffect(widget)
        effect.setObjectName(REVEAL)
        widget.setGraphicsEffect(effect)
    widget.show()
    animation.start()
    return animation


def _height(widget: QWidget, parent: QWidget) -> int:
    """The height `widget` takes at the width of its parent."""
    widget.setMaximumHeight(UNBOUNDED)
    if widget.hasHeightForWidth():
        return widget.heightForWidth(parent.contentsRect().width())
    return widget.sizeHint().height()


def _grow(widget: QWidget, animation: QVariantAnimation, height: int) -> None:
    widget.setMaximumHeight(int(height))
    effect = widget.graphicsEffect()
    full = max(int(animation.startValue()), int(animation.endValue()), 1)
    if isinstance(effect, QGraphicsOpacityEffect) and effect.objectName() == REVEAL:
        effect.setOpacity(min(1.0, int(height) / full))


def _settle(widget: QWidget, shown: bool) -> None:
    """The end of a reveal: shown at its own height, or hidden; no bound and no fade left."""
    widget.setMaximumHeight(UNBOUNDED)
    effect = widget.graphicsEffect()
    if effect is not None and effect.objectName() == REVEAL:
        widget.setGraphicsEffect(None)  # pyright: ignore[reportArgumentType]
    widget.setVisible(shown)
