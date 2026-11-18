"""
Where everything is on a strip of the preview, in logical units (a strip is WIDTH x HEIGHT), like on the device:
the encoder with its ring, the LCD, the buttons, the meter and the fader with its scale.
"""

from dataclasses import dataclass
from math import cos, radians, sin
from typing import Literal

from PyQt6.QtCore import QLineF, QPoint, QPointF, QRectF, QSizeF

from xtouch_daemon.hardware import protocol

WIDTH = 104
HEIGHT = 500
"""A strip, in logical units (pixels at scale 1): narrower than the device (about 1:8)."""
SPACING = 6
MARGIN_X = 14
MARGIN_Y = 12
PANEL = QSizeF(2 * MARGIN_X + protocol.STRIPS * WIDTH + (protocol.STRIPS - 1) * SPACING, 2 * MARGIN_Y + HEIGHT)
"""The whole panel with the 8 strips, in logical units."""


CENTER_X = WIDTH / 2
NUMBER = QRectF(0, 4, WIDTH, 12)
"""The number of the strip, printed above the encoder."""
ENCODER = QPointF(CENTER_X, 44)
RING_LEDS = 13
"""The ring has 13 LEDs; the 11 positions of Mackie Control light the middle ones (position 6 at the top)."""
RING_SPAN = 300
"""The angle the LEDs of the ring cover, open at the bottom."""
RING_RADII = (20.5, 25.5)
"""Where the LEDs of the ring start and end, from the center of the encoder."""
LCD = QRectF(8, 80, WIDTH - 16, 44)
LCD_CELLS = LCD.adjusted(5, 6, -5, -6)
"""Where the 2 lines of 7 characters are, inside the bezel; a lit line divides them."""
KIND = QRectF(3, 126, WIDTH - 6, 13)
"""The type of the strip, printed under the LCD (the device has nothing there)."""
SELECT_ROW = 3
"""The row of Select, the last of the buttons (Rec, Solo, Mute, Select)."""
BUTTON_TOP = 143
BUTTON_PITCH = 36
"""The buttons are one above the other, each with its name printed under it."""
BUTTON_X = CENTER_X + 19
"""The middle of the column of buttons."""
BUTTON_SIZE = QSizeF(24, 24)
"""REC, SOLO and MUTE are square."""
SELECT_SIZE = QSizeF(30, 24)
"""SELECT is a little wider."""
BUTTONS_BOTTOM = BUTTON_TOP + 3 * BUTTON_PITCH + SELECT_SIZE.height() + 10
"""Where the name printed under SELECT ends."""
METER = QRectF(13, BUTTON_TOP - 1, 9, 3 * BUTTON_PITCH + SELECT_SIZE.height() + 2)
"""The window of the meter, left of the buttons: from the top of REC to the bottom of SELECT."""
METER_LEDS = 8
"""
8 LEDs from the bottom: 4 green and 3 orange for the level, and the red clip LED at the top (labeled CLIP; the
bottom one SIG), lit while the audio clips.
"""
METER_GREEN = 4
CAP_SIZE = QSizeF(34, 30)
CAP_AREA = QRectF(
    CENTER_X - CAP_SIZE.width() / 2 - 2, -CAP_SIZE.height() / 2 - 2, CAP_SIZE.width() + 4, CAP_SIZE.height() + 8
)
"""What the cap covers with its outline and shadow, its middle at 0."""
LED_GLOW = 4.5
"""How far the glow of a lit LED reaches beyond it."""
BODY = QRectF(3, 3, WIDTH - 6, HEIGHT - 6)
"""The strip on the panel, inside its place."""
STRIP_TAG = QRectF(CENTER_X - 7, HEIGHT - 22, 14, 12)
"""The number of the strip again, on a light tag at the bottom."""
TRAVEL = (BUTTONS_BOTTOM + CAP_SIZE.height() / 2 + 3, STRIP_TAG.top() - CAP_SIZE.height() / 2 - 3)
"""
Where the middle of the cap is at the top (1, +10 dB) and at the bottom (0, -∞) of the travel: the cap stays clear
of the buttons and the tag.
"""
SLOT = QRectF(CENTER_X - 2.5, TRAVEL[0] - 8, 5, TRAVEL[1] - TRAVEL[0] + 16)
"""The slot of the fader, a little longer than the travel."""


@dataclass(frozen=True)
class Mark:
    """A mark of the scale printed beside a fader."""

    label: str
    at: float
    """Where it is, as a fraction of the travel."""
    ticks: int
    """How many small ticks are between it and the next mark down."""
    boxed: bool = False
    """Whether there is a box instead, as from +5 to -5 dB, where most people put a fader."""


UNITY = 0.77
"""Where 0 dB is, as a fraction of the travel: the default of `behavior.unity_at`."""
PRINTED_SCALE = (
    ("10", 16, 4),
    ("5", 14, 0),
    ("0", 12, 0),
    ("-5", 10, 4),
    ("-10", 8, 4),
    ("-20", 6, 4),
    ("-30", 4, 1),
    ("-40", 3, 1),
    ("-50", 2, 1),
    ("-60", 1, 1),
    ("-∞", 0, 0),
)
"""
The marks printed on the device, measured on a photo: their height above -∞ in half steps (equal steps from +10 down
to -30 dB, half steps below), and the small ticks between each and the next one down.
"""


def _scale() -> tuple[Mark, ...]:
    """
    The printed marks on the travel: -∞ at the bottom, +10 dB at the top and 0 dB at UNITY, the marks between them
    evenly spaced as printed.
    """
    unity = next(height for label, height, _ in PRINTED_SCALE if label == "0")
    top = PRINTED_SCALE[0][1]
    marks: list[Mark] = []
    for label, height, ticks in PRINTED_SCALE:
        below = height <= unity
        at = height / unity * UNITY if below else UNITY + (height - unity) / (top - unity) * (1 - UNITY)
        # a box instead of ticks from +5 to -5 dB, where a fader is most of the time
        marks.append(Mark(label, at, ticks, boxed=label in ("5", "0")))
    return tuple(marks)


SCALE = _scale()
"""The dB scale beside the fader, where a cap in the middle of a mark shows that value."""


def slot_position(index: int) -> QPoint:
    """Where the strip at `index` sits in the preview."""
    return QPoint(MARGIN_X + index * (WIDTH + SPACING), MARGIN_Y)


def travel_y(fraction: float) -> float:
    """Where the middle of the cap is for a fader at `fraction` (0 at the bottom, 1 at the top)."""
    top, bottom = TRAVEL
    return bottom - fraction * (bottom - top)


def fraction_at(y: float) -> float:
    """The fader position (0..1) for the middle of the cap at `y`: `travel_y()` the other way round."""
    top, bottom = TRAVEL
    return min(1.0, max(0.0, (bottom - y) / (bottom - top)))


type Part = Literal["encoder", "fader"] | int
"""A part of a strip the mouse can take: the encoder, the fader, or a button (its row)."""


def part_at(point: QPointF) -> Part | None:
    """What is at `point` of a strip: the encoder with its ring, a button, the fader (anywhere along its slot)."""
    if QLineF(point, ENCODER).length() <= RING_RADII[1]:
        return "encoder"
    for row in range(SELECT_ROW + 1):
        if button_rect(row).contains(point):
            return row
    if abs(point.x() - CENTER_X) <= CAP_SIZE.width() / 2 and SLOT.top() <= point.y() <= SLOT.bottom():
        return "fader"
    return None


def button_rect(row: int) -> QRectF:
    """The button in `row` (REC is 0, SELECT 3), without its printed name."""
    size = SELECT_SIZE if row == SELECT_ROW else BUTTON_SIZE
    return QRectF(QPointF(BUTTON_X - size.width() / 2, BUTTON_TOP + row * BUTTON_PITCH), size)


def meter_led(led: int) -> QRectF:
    """The LED `led` of the meter, 0 at the bottom."""
    pitch = (METER.height() - 6) / METER_LEDS
    return QRectF(METER.center().x() - 1.5, METER.bottom() - 3 - (led + 1) * pitch + 1.5, 3, pitch - 3)


def ring_angle(led: int) -> float:
    """The angle of the LED `led` of the ring (0 the first one, at the bottom left), in degrees counterclockwise."""
    return 90 + RING_SPAN / 2 - led * RING_SPAN / (RING_LEDS - 1)


KNOB_RADIUS = 15.5
"""The black knob in the middle of the ring."""


def ring_led_at(point: QPointF) -> int | None:
    """The LED of the ring (0..12) nearest to `point` of a strip, outside the knob; None on the knob or in the gap."""
    line = QLineF(ENCODER, point)
    if line.length() <= KNOB_RADIUS:
        return None
    # counterclockwise from the right, as `ring_angle`, but from the first LED on: 0 at the bottom left
    from_first = (90 + RING_SPAN / 2 - line.angle()) % 360
    pitch = RING_SPAN / (RING_LEDS - 1)
    if from_first > RING_SPAN + pitch / 2:
        return None
    return round(min(from_first, RING_SPAN) / pitch)


def ring_led(led: int) -> tuple[QPointF, QPointF]:
    """Where the LED `led` of the ring (0..12) starts and ends."""
    angle = radians(ring_angle(led))
    direction = QPointF(cos(angle), -sin(angle))
    return ENCODER + direction * RING_RADII[0], ENCODER + direction * RING_RADII[1]
