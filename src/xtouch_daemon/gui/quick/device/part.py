"""
The model of the preview of a part of a strip (see `PartPreview.qml`): the strip cut to the encoder, the display, the
buttons or the fader with its meter, and the steps of a scene of `gui.domain.demos` to go through like pictures, each
with a caption: what the options of a form do on the device. The crops and the size are in logical units of a strip.
"""

from math import ceil

from PyQt6.QtCore import QObject, QPointF, QRectF, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtGui import QKeyEvent

from xtouch_daemon.gui.domain.demos import Frame, Part
from xtouch_daemon.gui.domain.looks import StripFace, StripLook
from xtouch_daemon.gui.quick.device.geometry import (
    BUTTON_TOP,
    BUTTON_X,
    BUTTONS_BOTTOM,
    ENCODER,
    HEIGHT,
    LCD,
    METER,
    RING_RADII,
    WIDTH,
)
from xtouch_daemon.gui.quick.device.strip import Hand, Mover, StripPainter

_RING = RING_RADII[1] + 6
CROPS: dict[Part, QRectF] = {
    "encoder": QRectF(ENCODER.x() - _RING, ENCODER.y() - _RING, 2 * _RING, 2 * _RING),
    "display": LCD.adjusted(-4, -4, 4, 4),
    "buttons": QRectF(BUTTON_X - 26, BUTTON_TOP - 6, 52, BUTTONS_BOTTOM - BUTTON_TOP + 12),
    "fader": QRectF(METER.left() - 8, METER.top() - 6, WIDTH - METER.left() + 8, HEIGHT - METER.top() + 2),
}
"""What of the strip each part shows, in logical units."""
SIZE = (120, 220)
"""The most room the drawing of a part takes, in pixels at 100 %."""
CAPTION_WIDTH = SIZE[0]
"""The least width of the caption under it (the drawing's where it is wider): a few words a line."""


class PartPreviewModel(QObject):
    """The drawing of a `part` and the steps of its scene (`play(frames)`), for `PartPreview.qml`."""

    changed = pyqtSignal(arguments=[])

    def __init__(self, part: Part, parent: QObject | None = None) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]
        self.part = part
        crop = CROPS[part]
        self.scale = min(SIZE[0] / crop.width(), SIZE[1] / crop.height())
        """Pixels per logical unit of the strip."""
        self.blink = True
        self.now = 0.0
        """The demos tell levels that stay: no time passes for them."""
        self.pixel_width = ceil(crop.width() * self.scale)
        self.pixel_height = ceil(crop.height() * self.scale)
        self.offset = QPointF(round(-crop.left() * self.scale), round(-crop.top() * self.scale))
        """Where the strip starts in the cut, in pixels."""
        self.view = StripPainter(self, 0)
        self.frames: tuple[Frame, ...] = ()
        self.index = 0
        """The frame shown."""
        self.counter = ""
        self.caption = ""

    # -- what a strip is drawn in: nobody plays or moves a preview of a part --------------------------------------

    @property
    def hand(self) -> Hand | None:
        return None

    @property
    def mover(self) -> Mover | None:
        return None

    @property
    def resizing(self) -> bool:
        return False

    def pick(self, index: int) -> None:
        """A click does nothing."""

    def key(self, index: int, event: QKeyEvent) -> bool:
        return False

    # -- for QML -------------------------------------------------------------------------------------------------

    @pyqtProperty(str, constant=True)
    def partName(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self.part

    @pyqtProperty(int, constant=True)
    def drawingWidth(self) -> int:  # pyright: ignore[reportRedeclaration]
        """Pixels the drawing is wide, at 100 %."""
        return self.pixel_width

    @pyqtProperty(int, constant=True)
    def drawingHeight(self) -> int:  # pyright: ignore[reportRedeclaration]
        return self.pixel_height

    @pyqtProperty(int, constant=True)
    def captionWidth(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The least width of the caption under the drawing: a few words a line."""
        return max(CAPTION_WIDTH, self.pixel_width)

    @pyqtProperty(str, notify=changed)
    def stepText(self) -> str:  # pyright: ignore[reportRedeclaration]
        """Which step is shown, e.g. "2 / 4"."""
        return self.counter

    @pyqtProperty(str, notify=changed)
    def captionText(self) -> str:  # pyright: ignore[reportRedeclaration]
        """What the step shows on the device, in a sentence."""
        return self.caption

    @pyqtProperty(int, notify=changed)
    def stepCount(self) -> int:  # pyright: ignore[reportRedeclaration]
        return len(self.frames)

    @pyqtProperty(int, notify=changed)
    def stepIndex(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The step shown, from 0."""
        return self.index

    def play(self, frames: tuple[Frame, ...]) -> None:
        """Shows `frames`, at the same step as before: a changed option shows its effect there."""
        self.frames = frames
        self.index = min(self.index, len(frames) - 1)
        self._show()

    @pyqtSlot(int)
    def step(self, steps: int) -> None:
        """A frame `steps` later (or earlier), round from the last to the first."""
        if self.frames:
            self.index = (self.index + steps) % len(self.frames)
            self._show()

    def _show(self) -> None:
        frame = self.frames[self.index]
        look = StripLook("preview", frame.state.text[0], "", frame.state.color, printed=" ")
        self.view.show_face(StripFace(look, frame.state, live=True, dimmed=frame.state.color == "off"), False)
        self.view.set_tip("")
        self.counter = f"{self.index + 1} / {len(self.frames)}"
        self.caption = frame.caption
        self.changed.emit()
