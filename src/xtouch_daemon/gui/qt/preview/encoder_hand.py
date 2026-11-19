"""
The mouse as a hand on the encoder of a strip of the device it plays (see `Hand`): the wheel turns it, a drag on the
knob turns it (up or right is clockwise), a click on the knob pushes it and holding it holds it down, and holding on
an LED of the ring turns the encoder until the ring lights that LED.
"""

from collections.abc import Callable
from enum import Enum, auto

from PyQt6.QtCore import QObject, QPointF, QTimer

from xtouch_daemon.gui.qt.preview.geometry import RING_LEDS, ring_led_at
from xtouch_daemon.hardware import protocol

NOTCH = 120
"""What a notch of a mouse wheel is in `QWheelEvent.angleDelta()`; touchpads and smooth wheels send parts of it."""
DRAG_STEP = 4.0
"""How far the mouse moves on the knob for a step of the encoder, in logical units of the strip."""
HOLD_MS = 300
"""How long a press on the knob waits for a drag before it pushes the encoder down."""
TURN_MS = 60
"""How often a hand held on an LED turns the encoder a step towards it, while the ring doesn't light it yet."""
_OFFSET = (RING_LEDS - protocol.RING_MAX) // 2
"""The positions light the middle LEDs: the first and the last one stay dark in Mackie Control."""


class _Grip(Enum):
    NONE = auto()
    KNOB = auto()
    """Pressed on the knob: neither a push nor a drag yet."""
    PUSHED = auto()
    DRAGGING = auto()
    LED = auto()
    """Held on an LED of the ring: turning towards it."""


class EncoderHand(QObject):
    """
    What the mouse does with the encoder of one strip: `turn(steps)` and `push(pressed)` go to the device,
    `position()` is where its ring is now (0: dark, else 1..RING_MAX).
    """

    def __init__(
        self,
        parent: QObject,
        turn: Callable[[int], None],
        push: Callable[[bool], None],
        position: Callable[[], int],
    ) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]
        self._turn = turn
        self._push = push
        self._position = position
        self._grip = _Grip.NONE
        self._origin = QPointF()
        self._travel = 0.0
        """How far the drag went that was not turned into steps yet."""
        self._wheel = 0
        """The part of a notch the wheel turned that was not a step yet."""
        self._target = 0
        """The position the ring should show (1..RING_MAX), while held on an LED."""
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(HOLD_MS)
        self._hold.timeout.connect(self._held)
        self._repeat = QTimer(self)
        self._repeat.setInterval(TURN_MS)
        self._repeat.timeout.connect(self._toward_target)

    @property
    def busy(self) -> bool:
        """Whether the mouse holds the encoder."""
        return self._grip != _Grip.NONE

    def wheel(self, delta: int) -> None:
        """The wheel turned by `delta` (`angleDelta().y()`): a step a notch, parts of notches add up."""
        self._wheel += delta
        # towards zero, so the parts of a notch count the same in both directions
        steps = int(self._wheel / NOTCH)
        if steps:
            self._wheel -= steps * NOTCH
            self._turn(steps)

    def press(self, point: QPointF) -> None:
        """The mouse went down at `point` of the strip, on the encoder."""
        self._end()
        led = ring_led_at(point)
        if led is None:
            self._grip = _Grip.KNOB
            self._origin = point
            self._travel = 0.0
            self._hold.start()
            return
        self._grip = _Grip.LED
        self._aim(led)
        self._toward_target()
        self._repeat.start()

    def move(self, point: QPointF, drag_distance: float) -> None:
        """The mouse moved to `point` while down; `drag_distance` (logical units) tells a drag from a shaky click."""
        match self._grip:
            case _Grip.KNOB:
                offset = point - self._origin
                if abs(offset.x()) + abs(offset.y()) >= drag_distance:
                    self._hold.stop()
                    self._grip = _Grip.DRAGGING
                    self._drag(point)
            case _Grip.DRAGGING:
                self._drag(point)
            case _Grip.LED:
                if (led := ring_led_at(point)) is not None:
                    self._aim(led)
                    if not self._repeat.isActive():
                        self._repeat.start()
            case _Grip.NONE | _Grip.PUSHED:
                pass

    def release(self) -> None:
        """The mouse went up: a click on the knob pushes the encoder and lets it go."""
        if self._grip == _Grip.KNOB:
            self._push(True)
            self._push(False)
        elif self._grip == _Grip.PUSHED:
            self._push(False)
        self._end()

    def _end(self) -> None:
        self._grip = _Grip.NONE
        self._hold.stop()
        self._repeat.stop()

    def _held(self) -> None:
        self._grip = _Grip.PUSHED
        self._push(True)

    def _drag(self, point: QPointF) -> None:
        # up and right turn it clockwise, as a thumb on the knob would
        offset = point - self._origin
        self._origin = point
        self._travel += offset.x() - offset.y()
        steps = int(self._travel / DRAG_STEP)
        if steps:
            self._travel -= steps * DRAG_STEP
            self._turn(steps)

    def _aim(self, led: int) -> None:
        self._target = min(protocol.RING_MAX, max(1, led - _OFFSET + 1))

    def _toward_target(self) -> None:
        position = self._position()
        if position == self._target:
            self._repeat.stop()
            return
        self._turn(1 if position < self._target else -1)
