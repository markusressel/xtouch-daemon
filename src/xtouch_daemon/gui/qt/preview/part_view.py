"""
A part of a strip (the encoder, the display, the buttons, or the fader and meter) drawn like the window Device draws
it, with the steps of a scene of `gui.domain.demos` to go through like pictures (‹ and ›), each with a caption: what
the options of a form do on the device.
"""

from math import ceil

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from xtouch_daemon.gui.domain.demos import Frame, Part
from xtouch_daemon.gui.domain.looks import StripFace, StripLook
from xtouch_daemon.gui.qt.fields.basics import flat_button, label
from xtouch_daemon.gui.qt.preview.geometry import (
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
from xtouch_daemon.gui.qt.preview.panel import Hand
from xtouch_daemon.gui.qt.preview.strip_view import StripView
from xtouch_daemon.gui.qt.theme.tokens import Space

_RING = RING_RADII[1] + 6
CROPS: dict[Part, QRectF] = {
    "encoder": QRectF(ENCODER.x() - _RING, ENCODER.y() - _RING, 2 * _RING, 2 * _RING),
    "display": LCD.adjusted(-4, -4, 4, 4),
    "buttons": QRectF(BUTTON_X - 26, BUTTON_TOP - 6, 52, BUTTONS_BOTTOM - BUTTON_TOP + 6),
    "fader": QRectF(METER.left() - 8, METER.top() - 6, WIDTH - METER.left() + 8, HEIGHT - METER.top() + 2),
}
"""What of the strip each part shows, in logical units."""
SIZE = (120, 220)
"""The most room the drawing of a part takes, in pixels at 100 %."""
CAPTION_WIDTH = 160
"""The width of the caption under it: a few words a line."""


class PartDrawing(QWidget):
    """The strip, cut to a part, at a scale that fits `SIZE`; the mouse does nothing on it."""

    def __init__(self, part: Part):
        super().__init__()
        crop = CROPS[part]
        self.scale = min(SIZE[0] / crop.width(), SIZE[1] / crop.height())
        self.blink = True
        self.hand: Hand | None = None
        self.view = StripView(self, 0)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.view.resize(ceil(WIDTH * self.scale), ceil(HEIGHT * self.scale))
        self.view.move(round(-crop.left() * self.scale), round(-crop.top() * self.scale))
        self.setFixedSize(ceil(crop.width() * self.scale), ceil(crop.height() * self.scale))

    @property
    def resizing(self) -> bool:
        return False

    def pick(self, index: int) -> None:
        """A click does nothing."""

    def key(self, index: int, event: QKeyEvent) -> bool:
        return False


class PartPreview(QWidget):
    """The drawing of a part, buttons to go through the steps of its scene, and the caption of the step shown."""

    def __init__(self, part: Part):
        super().__init__()
        self.part = part
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Space.XS)
        self.drawing = PartDrawing(part)
        layout.addWidget(self.drawing, 0, Qt.AlignmentFlag.AlignHCenter)
        steps = QHBoxLayout()
        steps.setSpacing(Space.XS)
        self.back = flat_button("chevron-left", "The step before")
        self.back.clicked.connect(lambda: self.step(-1))
        self.counter = label("", "hint")
        self.next = flat_button("chevron-right", "The next step")
        self.next.clicked.connect(lambda: self.step(1))
        steps.addStretch()
        for widget in (self.back, self.counter, self.next):
            steps.addWidget(widget)
        steps.addStretch()
        layout.addLayout(steps)
        self.caption = label("", "hint", wrap=True)
        self.caption.setFixedWidth(CAPTION_WIDTH)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.caption)
        layout.addStretch()
        self.frames: tuple[Frame, ...] = ()
        self.index = 0
        """The frame shown."""

    def play(self, frames: tuple[Frame, ...]) -> None:
        """Shows `frames`, at the same step as before: a changed option shows its effect there."""
        self.frames = frames
        self.index = min(self.index, len(frames) - 1)
        self._show()

    def step(self, steps: int) -> None:
        """A frame `steps` later (or earlier), round from the last to the first."""
        self.index = (self.index + steps) % len(self.frames)
        self._show()

    def _show(self) -> None:
        frame = self.frames[self.index]
        look = StripLook("preview", frame.state.text[0], "", frame.state.color, printed=" ")
        self.drawing.view.show_face(StripFace(look, frame.state, live=True, dimmed=frame.state.color == "off"), False)
        self.drawing.view.setToolTip("")
        self.counter.setText(f"{self.index + 1} / {len(self.frames)}")
        self.caption.setText(frame.caption)
        self.setAccessibleDescription(frame.caption)
