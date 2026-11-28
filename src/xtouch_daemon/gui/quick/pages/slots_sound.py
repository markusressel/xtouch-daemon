"""The sound of a channel beside its chip on a card (see `sound.py`), painted for QML."""

from PyQt6.QtCore import QRectF, pyqtProperty, pyqtSignal  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtQml import qmlRegisterType
from PyQt6.QtQuick import QQuickItem, QQuickPaintedItem

from xtouch_daemon.gui.quick.pages.slots_condition import URI
from xtouch_daemon.gui.quick.pages.sound import SIZE, Sound, clock_of, paint_sound, sounding


class SoundBadge(QQuickPaintedItem):
    """
    The sound of one channel: empty while it has none, its room kept, so nothing moves when it comes and goes. Moves
    while the channel has sound (`active`, from the clock `sounding()` the window feeds).
    """

    changed = pyqtSignal(arguments=[])

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self._channel = ""
        self._kind = ""
        self._hue = QColor("#808080")
        self.setAntialiasing(True)
        self.setImplicitWidth(SIZE.width())
        self.setImplicitHeight(SIZE.height())
        clock = sounding()
        clock.tick.connect(self._tick)
        clock.changed.connect(self._changed)

    @pyqtProperty(str, notify=changed)
    def channel(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._channel

    @channel.setter
    def channel(self, channel: str) -> None:
        self._channel = channel
        self._changed()

    @pyqtProperty(str, notify=changed)
    def kind(self) -> str:  # pyright: ignore[reportRedeclaration]
        """`bars`, `ripple` or `pulse` (see `Sound`)."""
        return self._kind

    @kind.setter
    def kind(self, kind: str) -> None:
        self._kind = kind
        self._changed()

    @pyqtProperty(QColor, notify=changed)
    def hue(self) -> QColor:  # pyright: ignore[reportRedeclaration]
        return self._hue

    @hue.setter
    def hue(self, hue: QColor) -> None:
        self._hue = hue
        self._changed()

    @pyqtProperty(bool, notify=changed)
    def active(self) -> bool:  # pyright: ignore[reportRedeclaration]
        """Whether the channel has sound now."""
        return bool(self._channel) and bool(self._kind) and sounding().sounds(self._channel)

    def _changed(self) -> None:
        self.changed.emit()
        self.update()

    def _tick(self) -> None:
        if self.active and self.isVisible():
            self.update()

    def paint(self, painter: QPainter | None) -> None:
        if painter is None or not self.active:
            return
        paint_sound(
            painter,
            QRectF(0, 0, self.width(), self.height()),
            Sound(self._kind),
            clock_of(self._channel),
            self._hue.name(),
        )


def register() -> None:
    qmlRegisterType(SoundBadge, URI, 1, 0, "SoundBadge")
