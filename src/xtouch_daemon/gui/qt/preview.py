"""
The preview: the 8 strips laid out like the hardware (encoder with its ring, LCD, buttons with LEDs, meter, fader),
showing what the device shows right now while the daemon runs, or what the file would show. It is also how a strip
is picked: a click (or the arrow keys) selects a strip, dragging a configured strip (or Ctrl+arrow) moves it, and the
context menu has the rest.

The strips are laid out and painted in logical units (a strip is WIDTH x HEIGHT) and scaled to the space the preview
gets, so they stay sharp at any size and zoom.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from math import ceil, cos, floor, radians, sin

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    QSizeF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QContextMenuEvent,
    QFocusEvent,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QRadialGradient,
    QResizeEvent,
)
from PyQt6.QtWidgets import QApplication, QMenu, QSizePolicy, QWidget

from xtouch_daemon import protocol
from xtouch_daemon.gui.domain.looks import StripFace, StripLook, faces, meter_leds, ring_leds
from xtouch_daemon.gui.qt import theme

KIND_NAMES = {"homeassistant": "Home Assistant", "?": "no type"}
WIDTH = 104
HEIGHT = 500
"""A strip, in logical units (pixels at scale 1): narrower than the device (about 1:8)."""
SPACING = 6
MARGIN_X = 14
MARGIN_Y = 12
PANEL = QSizeF(2 * MARGIN_X + protocol.STRIPS * WIDTH + (protocol.STRIPS - 1) * SPACING, 2 * MARGIN_Y + HEIGHT)
"""The whole panel with the 8 strips, in logical units."""
MIN_SCALE = 0.5
"""The smallest the preview gets: half its size still shows the LEDs, faders and LCD colors."""
SETTLE_MS = 150
"""
How long after the last change of size the strips are drawn sharp again: meanwhile (e.g. while the handle above the
editor is dragged) their printed parts are the picture of before, scaled, which is much faster.
"""
ANIMATION_MS = 160
"""How long the other strips take to make room for a dragged one: quick, but long enough to see where they go."""
BLINK_MS = 400
"""How fast a flashing LED blinks."""
LIFT = 8
"""How far a dragged strip is lifted out of the row."""
LIFTED_OPACITY = 0.8

HW = theme.HARDWARE
BUTTONS = (("REC", HW.rec), ("SOLO", HW.solo), ("MUTE", HW.mute), ("SELECT", HW.select))
STRIP_RADIUS = 8
PANEL_RADIUS = 14
DIM = 0.19
"""How bright a dimmed backlight is."""
DIM_TEXT = 0.75
"""How bright the characters of a dimmed LCD are: they keep 4:1 on its panel, for every color."""
LCD_PANEL = "#050608"
"""The dark panel of an LCD, over the backlight."""
LCD_TINT = 0.06
"""How much of the backlight shines through the dark panel."""
LCD_GLOW = 0.5
"""How far the light around the characters reaches."""
KEY_TINT = 0.08
"""How much of its LED color an unlit button shows: the device has gray buttons, the tint hints at their color."""
LED_OFF_TINT = 0.18
UNCONFIGURED_OPACITY = 0.8
"""Strips after the configured ones are drawn fainter: their texts keep 4.6:1 (LCD) to 6.6:1 (printed)."""

# -- the layout of a strip, top to bottom like on the device, in the coordinates of the strip ------------------------

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


def button_rect(row: int) -> QRectF:
    """The button in `row` (REC is 0, SELECT 3), without its printed name."""
    size = SELECT_SIZE if row == len(BUTTONS) - 1 else BUTTON_SIZE
    return QRectF(QPointF(BUTTON_X - size.width() / 2, BUTTON_TOP + row * BUTTON_PITCH), size)


def meter_led(led: int) -> QRectF:
    """The LED `led` of the meter, 0 at the bottom."""
    pitch = (METER.height() - 6) / METER_LEDS
    return QRectF(METER.center().x() - 1.5, METER.bottom() - 3 - (led + 1) * pitch + 1.5, 3, pitch - 3)


def ring_angle(led: int) -> float:
    """The angle of the LED `led` of the ring (0 the first one, at the bottom left), in degrees counterclockwise."""
    return 90 + RING_SPAN / 2 - led * RING_SPAN / (RING_LEDS - 1)


def _mix(color: QColor, base: QColor, amount: float) -> QColor:
    """`amount` of `color` over `base`."""
    return QColor.fromRgbF(
        color.redF() * amount + base.redF() * (1 - amount),
        color.greenF() * amount + base.greenF() * (1 - amount),
        color.blueF() * amount + base.blueF() * (1 - amount),
    )


def _paint_led(painter: QPainter, start: QPointF, end: QPointF, width: float, color: str, lit: bool) -> None:
    """An LED, a short bar from `start` to `end` like those of the device: lit with a glow, or dark."""
    led = QColor(color)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if lit:
        glow = QColor(led)
        for extra, alpha in ((5, 40), (2.5, 90)):
            glow.setAlpha(alpha)
            painter.setPen(QPen(glow, width + extra, cap=Qt.PenCapStyle.RoundCap))
            painter.drawLine(start, end)
    painter.setPen(
        QPen(led if lit else _mix(led, QColor(HW.led_off), LED_OFF_TINT), width, cap=Qt.PenCapStyle.RoundCap)
    )
    painter.drawLine(start, end)


def _ring_led(led: int) -> tuple[QPointF, QPointF]:
    """Where the LED `led` of the ring (0..12) starts and ends."""
    angle = radians(ring_angle(led))
    direction = QPointF(cos(angle), -sin(angle))
    return ENCODER + direction * RING_RADII[0], ENCODER + direction * RING_RADII[1]


def _paint_meter_led(painter: QPainter, led: int, lit: bool) -> None:
    """The LED `led` of the meter (0 at the bottom): green, orange, and red at the top."""
    color = HW.meter_high if led == METER_LEDS - 1 else HW.meter_mid if led >= METER_GREEN else HW.meter_low
    rect = meter_led(led)
    half = QPointF(0, rect.height() / 2 - 1.5)
    _paint_led(painter, rect.center() - half, rect.center() + half, rect.width(), color, lit)


@dataclass(frozen=True)
class _Picture:
    """A picture of a strip (or a part of it), and what it was drawn for."""

    pixmap: QPixmap
    key: object
    """What it shows."""
    scale: float
    ratio: float
    """The device pixel ratio."""

    def paint(self, painter: QPainter) -> None:
        """Draws it on a painter in logical units: exact at its own scale, else scaled."""
        size = QSizeF(self.pixmap.width(), self.pixmap.height()) / (self.scale * self.ratio)
        painter.drawPixmap(QRectF(QPointF(), size), self.pixmap, QRectF(self.pixmap.rect()))


def _draw(key: object, scale: float, ratio: float, paint: Callable[[QPainter, float, float], None]) -> _Picture:
    """A picture of a strip at a scale and pixel ratio, painted in logical units by `paint`."""
    pixmap = QPixmap(ceil(WIDTH * scale * ratio), ceil(HEIGHT * scale * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    paint(painter, scale, ratio)
    painter.end()
    return _Picture(pixmap, key, scale, ratio)


@dataclass(frozen=True)
class _Sprite:
    """A small picture of a part of a strip that moves or blinks, e.g. a lit LED."""

    pixmap: QPixmap
    area: QRectF
    """Where it goes, in logical units, aligned to the pixels of its scale."""
    scale: float
    ratio: float

    def paint(self, painter: QPainter, dy: float = 0) -> None:
        """Draws it, `dy` lower (rounded to its pixels, so that it stays sharp)."""
        step = self.scale * self.ratio
        painter.drawPixmap(self.area.translated(0, round(dy * step) / step), self.pixmap, QRectF(self.pixmap.rect()))


SPRITES_KEPT = 200
"""The small pictures kept: those of a few scales; more are dropped and drawn again."""
_sprites: dict[tuple[object, ...], _Sprite] = {}


def _sprite(
    key: tuple[object, ...], area: QRectF, scale: float, ratio: float, paint: Callable[[QPainter], None]
) -> _Sprite:
    """The small picture of `area` (in logical units) at a scale and pixel ratio, painted by `paint` the first time."""
    full = (*key, scale, ratio)
    sprite = _sprites.get(full)
    if sprite is None:
        if len(_sprites) >= SPRITES_KEPT:
            _sprites.clear()
        step = scale * ratio
        # on whole pixels, so that it is drawn without blurring
        left, top = floor(area.left() * step), floor(area.top() * step)
        right, bottom = ceil(area.right() * step), ceil(area.bottom() * step)
        aligned = QRectF(left / step, top / step, (right - left) / step, (bottom - top) / step)
        pixmap = QPixmap(right - left, bottom - top)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(scale, scale)
        painter.translate(-aligned.topLeft())
        paint(painter)
        painter.end()
        sprite = _sprites[full] = _Sprite(pixmap, aligned, scale, ratio)
    return sprite


def _print_font(base: QFont, size: int, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    """The font of the fine print on the panel."""
    font = QFont(base)
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


@dataclass
class _Drag:
    source: int
    target: int
    grab: float
    """Where the strip was grabbed, from its left edge (in logical units)."""


class Preview(QWidget):
    """The 8 strips side by side, on a panel like the device."""

    clicked = pyqtSignal(int, arguments=["index"])
    moved = pyqtSignal(int, int, arguments=["source", "target"])
    """A strip was moved (dragged, Ctrl+arrow, or with the menu): from, to."""
    configure = pyqtSignal(int, arguments=["index"])
    """A strip that is not configured should be."""
    remove = pyqtSignal(int, arguments=["index"])

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.scale = 1.0
        """How large the panel is drawn: it fills the space it gets, keeping its proportions."""
        self.origin = QPointF()
        """Where the panel starts, centered in the widget."""
        self.settle = QTimer(self)
        """Runs while the size changes: until it times out, strips scale the picture of their printed parts."""
        self.settle.setSingleShot(True)
        self.settle.setInterval(SETTLE_MS)
        self.settle.timeout.connect(self._settled)
        self.held = False
        """Whether the handle that sizes the preview is held."""
        self.strips: list[StripView] = [StripView(self, index) for index in range(protocol.STRIPS)]
        self._drag: _Drag | None = None
        self.animations: dict[int, QPropertyAnimation] = {}
        """The glides of the strips making room for a dragged one, by strip."""
        self.blink = True
        """Whether flashing LEDs are lit right now."""
        self.blinker = QTimer(self)
        self.blinker.setInterval(BLINK_MS)
        self.blinker.timeout.connect(self._blink)

    def sizeHint(self) -> QSize:
        return QSize(ceil(PANEL.width()), ceil(PANEL.height()))

    def minimumSizeHint(self) -> QSize:
        return QSize(ceil(PANEL.width() * MIN_SCALE), ceil(PANEL.height() * MIN_SCALE))

    def to_widget(self, point: QPointF) -> QPoint:
        """A point of the panel (in logical units) in the widget."""
        return (self.origin + point * self.scale).toPoint()

    def slot_point(self, index: int) -> QPoint:
        """Where the strip at `index` sits in the widget."""
        return self.to_widget(QPointF(slot_position(index)))

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        """Scales the panel to the new size, centered, and puts every strip in its place at that scale."""
        if self.dragging:
            self.cancel_drag()
        assert event is not None
        if not event.oldSize().isEmpty():
            # a change of size, not the first one: draw fast until it ends
            self.settle.start()
        self.scale = min(self.width() / PANEL.width(), self.height() / PANEL.height())
        self.origin = QPointF(
            (self.width() - PANEL.width() * self.scale) / 2, (self.height() - PANEL.height() * self.scale) / 2
        )
        for animation in self.animations.values():
            animation.stop()
        for index, view in enumerate(self.strips):
            view.resize(ceil(WIDTH * self.scale), ceil(HEIGHT * self.scale))
            view.move(self.slot_point(index))

    @property
    def resizing(self) -> bool:
        """Whether the size is changing: then strips scale the pictures they have."""
        return self.held or self.settle.isActive()

    def hold(self, held: bool) -> None:
        """
        The handle that sizes the preview is held (or let go): until it is let go, strips scale their pictures, also
        when the hand rests for a moment; then they are drawn sharp at once.
        """
        self.held = held
        if not held:
            self.settle.stop()
            self._settled()

    def _settled(self) -> None:
        for view in self.strips:
            view.update()

    @property
    def dragging(self) -> bool:
        return self._drag is not None

    @property
    def drop_target(self) -> int | None:
        """Where the dragged strip goes when it is let go."""
        return None if self._drag is None else self._drag.target

    def show_faces(self, strip_faces: tuple[StripFace, ...], selected: int | None) -> None:
        for view, face in zip(self.strips, strip_faces, strict=True):
            view.show_face(face, view.index == selected)
        flashing = any("flash" in face.state.leds.values() for face in strip_faces)
        if flashing and not self.blinker.isActive():
            self.blinker.start()
        elif not flashing:
            self.blinker.stop()
            self.blink = True

    def _blink(self) -> None:
        self.blink = not self.blink
        for view in self.strips:
            view.update()

    # -- moving strips --------------------------------------------------------------------------------------------

    def start_drag(self, source: int, grab: float) -> None:
        """Lifts the strip out of the row: its place stays empty, and the others make room where it goes."""
        self._drag = _Drag(source, source, grab)
        view = self.strips[source]
        view.lifted = True
        view.raise_()
        view.update()
        view.setCursor(Qt.CursorShape.ClosedHandCursor)
        # Escape cancels: the keys come here while the mouse is held
        self.grabKeyboard()
        self.update()

    def drag_to(self, x: int) -> None:
        """Follows the mouse (`x` in the widget) and lets the other strips make room at the nearest place."""
        drag = self._drag
        assert drag is not None
        view = self.strips[drag.source]
        panel_x = (x - self.origin.x()) / self.scale
        left = max(MARGIN_X, min(panel_x - drag.grab, slot_position(protocol.STRIPS - 1).x()))
        view.move(self.to_widget(QPointF(left, MARGIN_Y - LIFT)))
        nearest = round((left - MARGIN_X) / (WIDTH + SPACING))
        target = max(0, min(nearest, protocol.STRIPS - 1))
        if target != drag.target:
            drag.target = target
            self._arrange(drag.source, target)
            self.update()

    def drop(self) -> None:
        """Puts the strip where it was dragged to."""
        drag = self._end_drag()
        if drag.target != drag.source:
            self.moved.emit(drag.source, drag.target)

    def cancel_drag(self) -> None:
        """Back to where it was, as if it had not been dragged."""
        self._end_drag()

    def _end_drag(self) -> _Drag:
        drag = self._drag
        assert drag is not None
        self._drag = None
        self.releaseKeyboard()
        view = self.strips[drag.source]
        view.lifted = False
        view.setCursor(Qt.CursorShape.PointingHandCursor)
        # every view back to its own place at once: after a move the window shows the moved strips in them
        for animation in self.animations.values():
            animation.stop()
        for index, strip in enumerate(self.strips):
            strip.move(self.slot_point(index))
        self.update()
        return drag

    def _arrange(self, source: int, target: int) -> None:
        """Glides every strip but the dragged one to its place with the dragged one at `target`."""
        order = list(range(protocol.STRIPS))
        order.insert(target, order.pop(source))
        for place, index in enumerate(order):
            if index == source:
                continue
            animation = self.animations.get(index)
            if animation is None:
                animation = QPropertyAnimation(self.strips[index], b"pos", self)
                animation.setDuration(ANIMATION_MS)
                animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                self.animations[index] = animation
            end = self.slot_point(place)
            if animation.state() == QAbstractAnimation.State.Running and animation.endValue() == end:
                continue
            animation.stop()
            animation.setStartValue(self.strips[index].pos())
            animation.setEndValue(end)
            animation.start()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        assert event is not None
        if self.dragging and event.key() == Qt.Key.Key_Escape:
            self.cancel_drag()
            return
        super().keyPressEvent(event)

    def key(self, index: int, event: QKeyEvent) -> bool:
        """
        A key for the strip that has the focus: the arrows, Home and End select, Ctrl+arrows move it, Delete removes
        it. False for other keys.
        """
        key = event.key()
        if self.dragging and key == Qt.Key.Key_Escape:
            self.cancel_drag()
            return True
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self.focus_strip(0 if key == Qt.Key.Key_Home else protocol.STRIPS - 1)
            return True
        if key == Qt.Key.Key_Delete and self.strips[index].look.configured:
            self.remove.emit(index)
            return True
        if key not in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            return False
        target = index + (-1 if key == Qt.Key.Key_Left else 1)
        if not 0 <= target < protocol.STRIPS:
            return True
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.strips[index].look.configured:
                self.moved.emit(index, target)
                self.strips[target].setFocus()
            return True
        self.focus_strip(target)
        return True

    def focus_strip(self, index: int) -> None:
        self.strips[index].setFocus()
        self.clicked.emit(index)

    def menu_for(self, index: int) -> QMenu:
        """What can be done with a strip, the same as with its keys and on its page, for those who look here."""
        menu = QMenu(self)
        if self.strips[index].look.configured:
            for text, icon, target, keys in (
                ("Move left", "chevron-left", index - 1, "Ctrl+Left"),
                ("Move right", "chevron-right", index + 1, "Ctrl+Right"),
            ):
                action = QAction(theme.icon(icon), f"{text}\t{keys}", menu)
                action.setEnabled(0 <= target < protocol.STRIPS)
                action.triggered.connect(lambda _=False, target=target: self.moved.emit(index, target))
                menu.addAction(action)
            menu.addSeparator()
            remove = QAction(theme.icon("delete-outline", theme.current_colors().error), "Remove\tDel", menu)
            remove.triggered.connect(lambda: self.remove.emit(index))
            menu.addAction(remove)
        else:
            configure = QAction(theme.icon("plus"), f"Configure strip {index + 1}", menu)
            configure.triggered.connect(lambda: self.configure.emit(index))
            menu.addAction(configure)
        return menu

    # -- painting -------------------------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """The panel of the device (dark, lit from above, a bevel at the top edge), and the place of a dragged strip."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.origin)
        painter.scale(self.scale, self.scale)
        panel = QRectF(QPointF(), PANEL).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(panel.topLeft(), panel.bottomLeft())
        gradient.setColorAt(0, QColor(HW.panel_top))
        gradient.setColorAt(1, QColor(HW.panel_bottom))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(HW.panel_edge), 1))
        painter.drawRoundedRect(panel, PANEL_RADIUS, PANEL_RADIUS)
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        painter.drawLine(
            QPointF(panel.left() + PANEL_RADIUS, panel.top() + 1.5),
            QPointF(panel.right() - PANEL_RADIUS, panel.top() + 1.5),
        )
        if self._drag is not None:
            # where the strip goes when it is let go: an empty place in the row
            place = QRectF(QPointF(slot_position(self._drag.target)), QSizeF(WIDTH, HEIGHT)).adjusted(3, 3, -3, -3)
            accent = QColor(theme.current_colors().accent)
            fill = QColor(accent)
            fill.setAlpha(40)
            painter.setBrush(fill)
            painter.setPen(QPen(accent, 2, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(place, STRIP_RADIUS, STRIP_RADIUS)


class StripView(QWidget):
    """One strip of the device."""

    def __init__(self, preview: Preview, index: int):
        super().__init__(preview)  # pyright: ignore[reportArgumentType]: PyQt's stub types the parent as Self
        self.preview = preview
        self.index = index
        look = StripLook("auto", "auto", "", "white", configured=False, problems=0)
        self.face = faces((look,), None, (False,))[0]
        self.selected = False
        self.lifted = False
        """Whether it is being dragged."""
        self._press: QPoint | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.lcd_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.lcd_font.setPixelSize(14)
        self.lcd_font.setWeight(QFont.Weight.DemiBold)
        self.printed: _Picture | None = None
        """The picture of the parts that don't change with the state, drawn once per size."""
        self.shown: _Picture | None = None
        """The picture of the strip without what moves all the time, drawn again when it shows something else."""
        self.picture: _Picture | None = None
        """The picture of the whole strip: the one of what it shows, with what moves over it."""

    @property
    def look(self) -> StripLook:
        return self.face.look

    def show_face(self, face: StripFace, selected: bool) -> None:
        self.face = face
        self.selected = selected
        look = face.look
        lines = [f"Strip {self.index + 1}: {KIND_NAMES.get(look.kind, look.kind)}"]
        if not look.configured:
            lines.append("Not configured, so an auto strip: double-click to configure it.")
        lines.append(look.detail)
        if face.edited and face.live:
            lines.append("Unsaved changes, live on the device (live preview).")
        elif face.edited:
            lines.append("Unsaved changes: it shows how it will look once saved.")
        elif face.live:
            lines.append("Live: what the device shows right now.")
        if look.problems:
            lines.append(f"{look.problems} problem{'' if look.problems == 1 else 's'}")
        if look.configured:
            lines.append("Drag it (or Ctrl+Left/Right) to move it.")
        self.setToolTip("\n".join(lines))
        self.setAccessibleName(f"Strip {self.index + 1}")
        self.setAccessibleDescription(" ".join(lines[1:]))
        self.update()

    # -- painting -------------------------------------------------------------------------------------------------
    # what the strip shows comes from its `face` (live or from the file); the `_paint_*` methods draw it like the device

    def _backlight(self) -> float:
        """1 lit, 0 dark, in between dimmed (an auto strip of the file, which is dark until an application plays)."""
        if self.face.state.color == "off":
            return 0.0
        return DIM if self.face.dimmed else 1.0

    def _lit(self, led: str) -> bool:
        return led == "on" or (led == "flash" and self.preview.blink)

    def _printed_key(self) -> tuple[int, str, str, bool, bool]:
        """What the printed parts depend on: the number, the type and its print, whether it is configured, lifted."""
        return self.index, self.look.kind, self.look.printed, self.look.configured, self.lifted

    def _shown_key(self) -> tuple[object, ...]:
        """
        Everything the picture of what the strip shows depends on: all but the meter, the ring and the fader, which
        change all the time (the live view tells them 20 times a second) and are put over it from small pictures.
        """
        state = dataclasses.replace(self.face.state, meter=0, ring=0, ring_mode="dot", fader=None, touched=False)
        return (
            self._printed_key(),
            dataclasses.replace(self.face, state=state),
            self.selected,
            self.hasFocus(),
            self.underMouse(),
            self.preview.blink,
            theme.current_mode(),
        )

    def _moving_key(self) -> tuple[frozenset[int], int, float, str | None]:
        """
        Where what moves all the time is: the lit LEDs of the ring and of the meter, the fader (at the bottom, where
        the daemon leaves it, while not known yet), and the accent around it while it is touched.
        """
        state = self.face.state
        return (
            ring_leds(state.ring, state.ring_mode),
            meter_leds(state.meter),
            0.0 if state.fader is None else state.fader,
            theme.current_colors().accent if state.touched else None,
        )

    def _current(self, picture: _Picture | None, key: object, scale: float, ratio: float) -> bool:
        """
        Whether a picture shows what the strip shows now: at this scale, or at the one before while the size changes
        (it is scaled then).
        """
        if picture is None or picture.key != key:
            return False
        return (picture.scale, picture.ratio) == (scale, ratio) or self.preview.resizing

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """
        The picture of the strip, drawn again when it shows something else, and for a new size once the size has
        stopped changing; the pictures of its parts save most of the work of that.
        """
        painter = QPainter(self)
        scale, ratio = self.preview.scale, self.devicePixelRatioF()
        key = (self._shown_key(), self._moving_key())
        if not self._current(self.picture, key, scale, ratio):
            self.picture = _draw(key, scale, ratio, self._paint_picture)
        picture = self.picture
        assert picture is not None
        # drawn in logical units, at the scale of the preview; while the size changes, the picture of before is scaled
        painter.scale(scale, scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # a lifted strip is see-through, so the place where it goes shows under it
        opacity = LIFTED_OPACITY if self.lifted else 1.0
        painter.setOpacity(opacity)
        picture.paint(painter)

    def _paint_picture(self, painter: QPainter, scale: float, ratio: float) -> None:
        """
        The whole strip: the picture of what it shows, and what moves all the time over it. That is put together from
        pictures only, much faster than drawing it, as it changes up to 20 times a second.
        """
        key = self._shown_key()
        if not self._current(self.shown, key, scale, ratio):
            self.shown = _draw(key, scale, ratio, self._paint_strip)
        shown = self.shown
        assert shown is not None
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        shown.paint(painter)
        self._paint_moving(painter, shown.scale, shown.ratio)

    def _paint_moving(self, painter: QPainter, scale: float, ratio: float) -> None:
        """
        What moves all the time: the lit LEDs of the ring and of the meter, and the fader, from small pictures at
        `scale` and `ratio`.
        """
        ring, meter, fader, accent = self._moving_key()
        if not self.look.configured:
            painter.setOpacity(UNCONFIGURED_OPACITY)
        # the positions light the middle LEDs: the first and the last one stay dark in Mackie Control
        offset = (RING_LEDS - protocol.RING_MAX) // 2
        for position in ring:
            led = position - 1 + offset
            start, end = _ring_led(led)
            area = QRectF(start, end).normalized().adjusted(-LED_GLOW, -LED_GLOW, LED_GLOW, LED_GLOW)
            sprite = _sprite(
                ("ring", led), area, scale, ratio, lambda p, s=start, e=end: _paint_led(p, s, e, 2.4, HW.ring, True)
            )
            sprite.paint(painter)
        for led in range(meter):
            area = meter_led(led).adjusted(-LED_GLOW, -LED_GLOW, LED_GLOW, LED_GLOW)
            _sprite(("meter", led), area, scale, ratio, lambda p, led=led: _paint_meter_led(p, led, lit=True)).paint(
                painter
            )
        cap = _sprite(("cap", accent), CAP_AREA, scale, ratio, lambda p: self._paint_cap(p, 0.0, accent))
        cap.paint(painter, travel_y(fader))

    def _paint_strip(self, painter: QPainter, scale: float, ratio: float) -> None:
        """The whole strip: the printed parts from their picture, and what the strip shows on top of them."""
        key = self._printed_key()
        if not self._current(self.printed, key, scale, ratio):
            self.printed = _draw(key, scale, ratio, self._paint_printed)
        printed = self.printed
        assert printed is not None
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        printed.paint(painter)
        self._paint_shown(painter)

    def _paint_printed(self, painter: QPainter, scale: float, ratio: float) -> None:
        """
        The parts that don't change with the state: the strip, the encoder with its LEDs dark, the labels, the meter
        and the buttons dark, the scale and the slot of the fader.
        """
        look = self.look
        self._paint_body(painter, BODY)
        if not look.configured:
            painter.setOpacity(UNCONFIGURED_OPACITY)
        number = str(self.index + 1)
        painter.setFont(_print_font(self.font(), 10, QFont.Weight.Bold))
        painter.setPen(QColor(HW.print))
        painter.drawText(NUMBER, Qt.AlignmentFlag.AlignCenter, number)
        self._paint_encoder(painter)
        kind = (look.printed or KIND_NAMES.get(look.kind, look.kind)).upper()
        self._paint_print(painter, KIND, kind, look.kind == "?")
        self._paint_meter(painter)
        for row, (name, color) in enumerate(BUTTONS):
            self._paint_button(painter, button_rect(row), name, color)
        self._paint_scale(painter)
        painter.setPen(QPen(QColor(HW.strip_edge), 1))
        painter.setBrush(QColor(HW.slot))
        painter.drawRoundedRect(SLOT, 2.5, 2.5)
        self._paint_tag(painter, number)

    def _paint_shown(self, painter: QPainter) -> None:
        """What the strip shows but the meter, the ring and the fader: the outline, the LCD, lit buttons, the marks."""
        face = self.face
        look, state = face.look, face.state
        self._paint_outline(painter, BODY)
        if not look.configured:
            painter.setOpacity(UNCONFIGURED_OPACITY)
        self._paint_lcd(painter)
        for row, (name, color) in enumerate(BUTTONS):
            if self._lit(state.leds[name.lower()]):
                self._paint_key(painter, button_rect(row), color, lit=True)
        painter.setOpacity(1)
        if look.problems:
            self._paint_badge(painter, QPointF(BODY.right() - 9, BODY.top() + 9), str(look.problems))
        if face.edited:
            self._paint_edited(painter, QPointF(BODY.left() + 9, BODY.top() + 9))
        if self.hasFocus():
            painter.setPen(QPen(QColor(theme.current_colors().accent), 1.5, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(BODY.adjusted(-2, -2, 2, 2), STRIP_RADIUS + 2, STRIP_RADIUS + 2)

    def _paint_body(self, painter: QPainter, body: QRectF) -> None:
        """The part of the panel that is this strip, lighter while it is lifted."""
        gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
        top = QColor(HW.strip_top)
        gradient.setColorAt(0, top.lighter(125) if self.lifted else top)
        gradient.setColorAt(1, QColor(HW.strip_bottom))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(body, STRIP_RADIUS, STRIP_RADIUS)

    def _paint_outline(self, painter: QPainter, body: QRectF) -> None:
        """
        The outline of the strip: in the accent when it is selected or dragged, dashed with unsaved changes (in the
        accent) or when it is not configured.
        """
        painter.setBrush(Qt.BrushStyle.NoBrush)
        accent = QColor(theme.current_colors().accent)
        if self.selected or self.lifted:
            # a soft glow around the outline, outside of the strip only
            outside = QPainterPath()
            outside.addRect(QRectF(0, 0, WIDTH, HEIGHT))
            inside = QPainterPath()
            inside.addRoundedRect(body, STRIP_RADIUS, STRIP_RADIUS)
            painter.save()
            painter.setClipPath(outside.subtracted(inside))
            glow = QColor(accent)
            for width, alpha in ((6, 40), (4, 80)):
                glow.setAlpha(alpha)
                painter.setPen(QPen(glow, width))
                painter.drawRoundedRect(body, STRIP_RADIUS, STRIP_RADIUS)
            painter.restore()
            pen = QPen(accent, 2)
        elif self.face.edited:
            pen = QPen(accent, 1.4, Qt.PenStyle.DashLine)
        elif not self.look.configured:
            pen = QPen(QColor(HW.print_dim), 1, Qt.PenStyle.DashLine)
        else:
            pen = QPen(QColor(HW.print_dim if self.underMouse() else HW.strip_edge), 1)
        painter.setPen(pen)
        painter.drawRoundedRect(body, STRIP_RADIUS, STRIP_RADIUS)

    def _paint_encoder(self, painter: QPainter) -> None:
        """The encoder: a gray collar with the 13 LEDs of the ring, dark, and the black knob in it."""
        center = ENCODER
        outer = RING_RADII[1] + 3
        collar = QRadialGradient(center, outer)
        collar.setColorAt(0.6, QColor(HW.collar_inner))
        collar.setColorAt(1, QColor(HW.collar_outer))
        painter.setBrush(collar)
        painter.setPen(QPen(QColor(HW.lcd_bezel), 1))
        painter.drawEllipse(center, outer, outer)
        for led in range(RING_LEDS):
            _paint_led(painter, *_ring_led(led), 2.4, HW.ring, False)
        # the knob: black rubber with a ribbed edge around a smooth top, lit from the top left
        painter.setPen(QPen(QColor(HW.lcd_bezel), 1))
        side = QRadialGradient(center + QPointF(-5, -6), 22)
        side.setColorAt(0, QColor(HW.knob_top))
        side.setColorAt(1, QColor(HW.knob_bottom))
        painter.setBrush(side)
        painter.drawEllipse(center, 15.5, 15.5)
        painter.setPen(QPen(QColor(0, 0, 0, 120), 1))
        for rib in range(32):
            angle = radians(rib * 360 / 32)
            direction = QPointF(cos(angle), sin(angle))
            painter.drawLine(center + direction * 12.5, center + direction * 15)
        top = QRadialGradient(center + QPointF(-3, -4), 14)
        top.setColorAt(0, QColor(HW.knob_top).lighter(115))
        top.setColorAt(1, QColor(HW.knob_bottom))
        painter.setBrush(top)
        painter.setPen(QPen(QColor(0, 0, 0, 160), 1))
        painter.drawEllipse(center, 10, 10)

    def _paint_lcd(self, painter: QPainter) -> None:
        """
        The LCD, a negative display like the one of the device: the backlight shines in a thin rim around a dark
        panel, and through it where the characters (2 lines of 7 cells, written from the left) and the line between
        the two lines are. With the backlight off, all of it is dark.
        """
        rect = LCD
        state = self.face.state
        level = self._backlight()
        color, off = QColor(theme.LCD_COLORS[state.color]), QColor(theme.LCD_COLORS["off"])
        backlight = _mix(color, off, level)
        painter.setPen(Qt.PenStyle.NoPen)
        if level == 1.0:
            # the light that leaks around the glass
            halo = QColor(backlight)
            halo.setAlpha(60)
            painter.setPen(QPen(halo, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 5, 5)
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(HW.lcd_bezel))
        painter.drawRoundedRect(rect, 4, 4)
        glass = rect.adjusted(2, 2, -2, -2)
        gradient = QLinearGradient(glass.topLeft(), glass.bottomLeft())
        gradient.setColorAt(0, backlight.lighter(110))
        gradient.setColorAt(1, backlight.darker(106))
        painter.setBrush(gradient)
        painter.drawRoundedRect(glass, 2.5, 2.5)
        painter.setBrush(_mix(backlight, QColor(LCD_PANEL), LCD_TINT))
        painter.drawRoundedRect(glass.adjusted(1.5, 1.5, -1.5, -1.5), 1.5, 1.5)
        cells = LCD_CELLS
        width = cells.width() / protocol.LCD_CELL_WIDTH
        height = (cells.height() - 2) / 2
        # the cells, a shade lighter than the panel, as the light comes through them a little
        faint = QColor(backlight)
        faint.setAlpha(10)
        painter.setBrush(faint)
        for line in range(2):
            for column in range(protocol.LCD_CELL_WIDTH):
                cell = QRectF(cells.left() + column * width, cells.top() + line * (height + 2), width, height)
                painter.drawRect(cell.adjusted(0.5, 0, -0.5, 0))
        # what lets the light through, dimmed less than the backlight, so that a dimmed LCD can still be read
        light = _mix(color, off, level if level in (0.0, 1.0) else DIM_TEXT)
        glow = QColor(light)
        glow.setAlpha(70)
        painter.setFont(self.lcd_font)
        for line, text in enumerate(state.text):
            for column, char in enumerate(text[: protocol.LCD_CELL_WIDTH]):
                cell = QRectF(cells.left() + column * width, cells.top() + line * (height + 2), width, height)
                # a little light around the characters, as on the device
                painter.setPen(glow)
                for dx, dy in ((-LCD_GLOW, 0), (LCD_GLOW, 0), (0, -LCD_GLOW), (0, LCD_GLOW)):
                    painter.drawText(cell.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, char)
                painter.setPen(light)
                painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, char)
        painter.setPen(QPen(light, 1))
        # in the middle of the pixel row between the lines, so that it is sharp
        middle = cells.top() + height + 1.5
        painter.drawLine(QPointF(glass.left() + 2.5, middle), QPointF(glass.right() - 2.5, middle))

    def _paint_print(self, painter: QPainter, rect: QRectF, text: str, error: bool) -> None:
        """A label printed on the panel, in small capitals; a problem in white on red."""
        font = _print_font(self.font(), 10 if len(text) < 10 else 9)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2 if len(text) < 10 else 0.2)
        painter.setFont(font)
        if error:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(HW.badge))
            width = QFontMetricsF(font).horizontalAdvance(text) + 12
            painter.drawRoundedRect(QRectF(rect.center().x() - width / 2, rect.top(), width, rect.height()), 3, 3)
        painter.setPen(QColor(HW.badge_text if error else HW.print))
        # a long name of a person ends in "…"
        text = QFontMetricsF(font).elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_button(self, painter: QPainter, rect: QRectF, name: str, color: str) -> None:
        """A button, dark, and its name printed under it."""
        self._paint_key(painter, rect, color, lit=False)
        font = _print_font(self.font(), 8, QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        painter.setFont(font)
        painter.setPen(QColor(HW.print))
        label = QRectF(rect.left() - 8, rect.bottom() + 1, rect.width() + 16, 10)
        painter.drawText(label, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, name)

    @staticmethod
    def _paint_key(painter: QPainter, rect: QRectF, color: str, lit: bool) -> None:
        """
        A button with its LED: translucent gray rubber (with a hint of its color) when off, glowing when on.
        """
        led = QColor(color)
        if lit:
            glow = QColor(led)
            glow.setAlpha(80)
            painter.setPen(QPen(glow, 4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 4, 4)
        body = led if lit else _mix(led, QColor(HW.key), KEY_TINT)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0, body.lighter(112))
        gradient.setColorAt(1, body.darker(110))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(HW.lcd_bezel), 1.5))
        painter.drawRoundedRect(rect, 4, 4)

    def _paint_meter(self, painter: QPainter) -> None:
        """The LED meter, dark (green, orange, and the red clip LED at the top), in a window labeled CLIP and SIG."""
        painter.setPen(QPen(QColor(HW.strip_edge), 1))
        painter.setBrush(QColor(HW.slot))
        painter.drawRoundedRect(METER, 3, 3)
        for led in range(METER_LEDS):
            _paint_meter_led(painter, led, lit=False)
        painter.setFont(_print_font(self.font(), 7, QFont.Weight.Bold))
        painter.setPen(QColor(HW.print))
        for text, led in (("CLIP", METER_LEDS - 1), ("SIG", 0)):
            y = meter_led(led).center().y()
            painter.drawText(QRectF(METER.right() + 3, y - 5, 26, 10), Qt.AlignmentFlag.AlignVCenter, text)

    def _paint_scale(self, painter: QPainter) -> None:
        """The dB scale on both sides of the slot: the marks, the ticks between them, and the boxes around 0 dB."""
        painter.setFont(_print_font(self.font(), 7))
        # how far the ticks start and end from the middle of the slot; the small ones are shorter at both ends
        near, far = 5.5, 17.0
        for side in (-1, 1):
            for upper, lower in pairwise(SCALE):
                top, bottom = travel_y(upper.at), travel_y(lower.at)
                painter.setPen(QPen(QColor(HW.print_dim), 1))
                if upper.boxed:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    box = QRectF(QPointF(CENTER_X + side * far, top + 2), QPointF(CENTER_X + side * near, bottom - 2))
                    painter.drawRoundedRect(box.normalized(), 2.5, 2.5)
                for tick in range(1, upper.ticks + 1):
                    y = top + tick * (bottom - top) / (upper.ticks + 1)
                    painter.drawLine(QPointF(CENTER_X + side * (near + 2), y), QPointF(CENTER_X + side * (far - 3), y))
        for mark in SCALE:
            y = travel_y(mark.at)
            painter.setPen(QPen(QColor(HW.print), 1))
            for side in (-1, 1):
                painter.drawLine(QPointF(CENTER_X + side * near, y), QPointF(CENTER_X + side * far, y))
            label = QRectF(CENTER_X - far - 26, y - 5, 24, 10)
            painter.drawText(label, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, mark.label)

    @staticmethod
    def _paint_cap(painter: QPainter, y: float, touched: str | None) -> None:
        """
        The metal cap of the fader, its middle at `y`: outlined in the accent (`touched`) while a finger is on it, as
        the motor stays still meanwhile.
        """
        cap = QRectF(CENTER_X - CAP_SIZE.width() / 2, y - CAP_SIZE.height() / 2, CAP_SIZE.width(), CAP_SIZE.height())
        # its shadow on the panel
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawRoundedRect(cap.translated(0, 3), 3, 3)
        # brushed metal, curved like a saddle: light at the edges, darker towards the line in the middle
        gradient = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        gradient.setColorAt(0, QColor(HW.cap_top))
        gradient.setColorAt(0.42, QColor(HW.cap_bottom))
        gradient.setColorAt(0.5, QColor(HW.cap_top))
        gradient.setColorAt(0.58, QColor(HW.cap_bottom))
        gradient.setColorAt(1, QColor(HW.cap_top).darker(115))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(touched), 2) if touched else QPen(QColor(HW.cap_line), 1))
        painter.drawRoundedRect(cap, 3, 3)
        painter.setPen(QPen(QColor(HW.cap_line), 1))
        painter.drawLine(QPointF(cap.left() + 2, cap.center().y()), QPointF(cap.right() - 2, cap.center().y()))
        painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
        painter.drawLine(QPointF(cap.left() + 3, cap.top() + 1.5), QPointF(cap.right() - 3, cap.top() + 1.5))

    def _paint_tag(self, painter: QPainter, number: str) -> None:
        """The light tag with the number of the strip at the bottom."""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(HW.tag))
        painter.drawRoundedRect(STRIP_TAG, 2.5, 2.5)
        painter.setFont(_print_font(self.font(), 9, QFont.Weight.Bold))
        painter.setPen(QColor(HW.tag_text))
        painter.drawText(STRIP_TAG, Qt.AlignmentFlag.AlignCenter, number)

    def _paint_badge(self, painter: QPainter, center: QPointF, text: str) -> None:
        """The number of problems of the strip."""
        painter.setPen(QPen(QColor(HW.panel_bottom), 2))
        painter.setBrush(QColor(HW.badge))
        painter.drawEllipse(center, 9, 9)
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(HW.badge_text))
        painter.drawText(QRectF(center.x() - 9, center.y() - 9, 18, 18), Qt.AlignmentFlag.AlignCenter, text)

    def _paint_edited(self, painter: QPainter, center: QPointF) -> None:
        # unsaved changes: a dot, like the marker of a modified file in an editor tab
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.current_colors().accent))
        painter.drawEllipse(center, 4.5, 4.5)

    # -- input ----------------------------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        assert event is not None
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self.preview.clicked.emit(self.index)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        if not self.look.configured:
            self.preview.configure.emit(self.index)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        assert event is not None
        point = event.position().toPoint()
        if self.preview.dragging:
            self.preview.drag_to(self.mapToParent(point).x())
            return
        if self._press is None or not self.look.configured:
            return
        if (point - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self.preview.start_drag(self.index, self._press.x() / self.preview.scale)
        self.preview.drag_to(self.mapToParent(point).x())

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        self._press = None
        if self.preview.dragging:
            self.preview.drop()

    def contextMenuEvent(self, event: QContextMenuEvent | None) -> None:
        assert event is not None
        self.preview.clicked.emit(self.index)
        self.preview.menu_for(self.index).exec(event.globalPos())

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        assert event is not None
        if not self.preview.key(self.index, event):
            super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent | None) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event: QFocusEvent | None) -> None:
        super().focusOutEvent(event)
        self.update()
