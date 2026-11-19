"""
A strip of the preview: what it shows (the look of a strip of the configuration, or what the device shows), and
the mouse and keys on it.
"""

import dataclasses
from collections.abc import Callable
from itertools import pairwise
from math import cos, radians, sin
from typing import TYPE_CHECKING, Protocol

from PyQt6.QtCore import (
    QPoint,
    QPointF,
    QRectF,
    Qt,
)
from PyQt6.QtGui import (
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
    QRadialGradient,
    QWheelEvent,
)
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from xtouch_daemon.gui.domain.looks import UNKNOWN, StripFace, StripLook, meter_leds, ring_leds
from xtouch_daemon.gui.qt.preview.encoder_hand import EncoderHand
from xtouch_daemon.gui.qt.preview.geometry import (
    BODY,
    CAP_AREA,
    CAP_SIZE,
    CENTER_X,
    ENCODER,
    HEIGHT,
    KIND,
    KNOB_RADIUS,
    LCD,
    LCD_CELLS,
    LED_GLOW,
    METER,
    METER_LEDS,
    NUMBER,
    RING_LEDS,
    RING_RADII,
    SCALE,
    SLOT,
    STRIP_TAG,
    WIDTH,
    Part,
    button_rect,
    fraction_at,
    meter_led,
    part_at,
    ring_led,
    travel_y,
)
from xtouch_daemon.gui.qt.preview.painting import (
    BUTTONS,
    DIM,
    DIM_TEXT,
    HW,
    KEY_TINT,
    LCD_GLOW,
    LCD_PANEL,
    LCD_TINT,
    STRIP_RADIUS,
    _Picture,
    cached_sprite,
    draw,
    mix,
    paint_led,
    paint_meter_led,
    print_font,
)
from xtouch_daemon.gui.qt.theme.style import current_colors, current_mode
from xtouch_daemon.gui.qt.theme.tokens import LCD_COLORS
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.live.messages import fader_now, meter_now

if TYPE_CHECKING:
    from xtouch_daemon.gui.qt.preview.panel import Hand

KIND_NAMES = {"homeassistant": "Home Assistant", "?": "no type"}


UNCONFIGURED_OPACITY = 0.8
"""Strips after the configured ones are drawn fainter: their texts keep 4.6:1 (LCD) to 6.6:1 (printed)."""


DRAG_DISTANCE = QApplication.startDragDistance
"""How far the mouse moves before a press is a drag, not a click (the desktop's setting)."""
LIFTED_OPACITY = 0.8
"""A dragged strip is see-through, so the place where it goes shows under it."""


class Mover(Protocol):
    """What moves strips by dragging them (the `Preview` in Select)."""

    @property
    def dragging(self) -> bool: ...

    def start_drag(self, source: int, grab: float) -> None: ...

    def drag_to(self, x: int) -> None: ...

    def drop(self) -> None: ...

    def menu_for(self, index: int) -> QMenu: ...


class StripHost(Protocol):
    """What a strip is drawn in: the `Preview` of the window Device, or a `PartPreview` of a form."""

    scale: float
    """Pixels (at the zoom of the window) per logical unit of the strip."""
    blink: bool
    """Whether flashing LEDs are lit right now."""
    now: float
    """The time the strip is drawn at (`time.monotonic()`): meters fall and faders glide from what they were told."""

    @property
    def hand(self) -> Hand | None:
        """The device the mouse is a hand on, None for none: a click only selects."""
        ...

    @property
    def mover(self) -> Mover | None:
        """What moves the strip when it is dragged, None where strips stay put."""
        ...

    @property
    def resizing(self) -> bool: ...

    def pick(self, index: int) -> None:
        """The strip at `index` was clicked."""

    def key(self, index: int, event: QKeyEvent) -> bool: ...


class StripView(QWidget):
    """One strip of the device."""

    def __init__(self, preview: StripHost, index: int):
        super().__init__(preview)  # pyright: ignore[reportArgumentType]: PyQt's stub types the parent as Self
        self.preview = preview
        self.index = index
        self.face = UNKNOWN
        self.selected = False
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
        self.held: tuple[Part, bool] | None = None
        self.encoder = EncoderHand(
            self,
            turn=lambda steps: self._hand_does(lambda hand: hand.turn(self.index, steps)),
            push=lambda pressed: self._hand_does(lambda hand: hand.push(self.index, pressed)),
            position=lambda: self.face.state.ring,
        )
        """The mouse on the encoder, while the window is a hand on the device."""
        """The part the mouse holds on a device it is a hand on, and whether a hand does it (no Alt), None for none."""
        self.lifted = False
        """Whether it is being dragged."""
        self.dragged_fader: float | None = None
        """Where the mouse holds the fader in Play (0..1), drawn there until it is let go; None while it doesn't."""
        self._press: QPoint | None = None
        """Where the mouse was pressed, to tell a drag from a click."""
        self.moving_drawn: object = None
        """What moves by itself (see `_moving_key()`) as the strip was drawn last."""

    @property
    def look(self) -> StripLook:
        return self.face.look

    def show_face(self, face: StripFace, selected: bool) -> None:
        self.face = face
        self.selected = selected
        look = face.look
        lines = [f"Strip {self.index + 1}: {KIND_NAMES.get(look.kind, look.kind)}"]
        lines.append(look.detail)
        if face.live:
            lines.append("Live: what the device shows right now.")
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
        state = dataclasses.replace(
            self.face.state,
            meter=0,
            meter_at=None,
            ring=0,
            ring_mode="dot",
            ring_center=False,
            fader=None,
            glide=None,
            touched=False,
        )
        return (
            self._printed_key(),
            dataclasses.replace(self.face, state=state),
            self.selected,
            self.hasFocus(),
            self.underMouse(),
            self.playing,
            self.preview.blink,
            current_mode(),
        )

    def _moving_key(self) -> tuple[frozenset[int], int, float, str | None, bool]:
        """
        Where what moves all the time is: the lit LEDs of the ring and of the meter, the fader (at the bottom, where
        the daemon leaves it, while not known yet), the accent around it while it is touched, and the LED below the
        ring.
        """
        state = self.face.state
        now = self.preview.now
        position = fader_now(state, now)
        fader = 0.0 if position is None else position
        if self.dragged_fader is not None:
            # under the mouse at once: the device (or the daemon) tells where it is only a moment later
            fader = self.dragged_fader
        return (
            ring_leds(state.ring, state.ring_mode),
            meter_leds(meter_now(state, now)),
            fader,
            current_colors().accent if state.touched or self.dragged_fader is not None else None,
            state.ring_center,
        )

    def follow_time(self) -> None:
        """Drawn again if what moves by itself shows otherwise at the time of the preview now."""
        if self._moving_key() != self.moving_drawn:
            self.update()

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
        self.moving_drawn = self._moving_key()
        key = (self._shown_key(), self.moving_drawn)
        if not self._current(self.picture, key, scale, ratio):
            self.picture = draw(key, scale, ratio, self._paint_picture)
        picture = self.picture
        assert picture is not None
        # drawn in logical units, at the scale of the preview; while the size changes, the picture of before is scaled
        painter.scale(scale, scale)
        if self.lifted:
            painter.setOpacity(LIFTED_OPACITY)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        picture.paint(painter)

    def _paint_picture(self, painter: QPainter, scale: float, ratio: float) -> None:
        """
        The whole strip: the picture of what it shows, and what moves all the time over it. That is put together from
        pictures only, much faster than drawing it, as it changes up to 20 times a second.
        """
        key = self._shown_key()
        if not self._current(self.shown, key, scale, ratio):
            self.shown = draw(key, scale, ratio, self._paint_strip)
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
        ring, meter, fader, accent, center = self._moving_key()
        if not self.look.configured:
            painter.setOpacity(UNCONFIGURED_OPACITY)
        # the positions light the middle LEDs; the first and the last one light together for the bit "center" of
        # Mackie Control (as measured on the device), which only the test of the device sets
        offset = (RING_LEDS - protocol.RING_MAX) // 2
        leds = {position - 1 + offset for position in ring} | ({0, RING_LEDS - 1} if center else set())
        for led in sorted(leds):
            start, end = ring_led(led)
            area = QRectF(start, end).normalized().adjusted(-LED_GLOW, -LED_GLOW, LED_GLOW, LED_GLOW)
            sprite = cached_sprite(
                ("ring", led), area, scale, ratio, lambda p, s=start, e=end: paint_led(p, s, e, 2.4, HW.ring, True)
            )
            sprite.paint(painter)
        for led in range(meter):
            area = meter_led(led).adjusted(-LED_GLOW, -LED_GLOW, LED_GLOW, LED_GLOW)
            cached_sprite(
                ("meter", led), area, scale, ratio, lambda p, led=led: paint_meter_led(p, led, lit=True)
            ).paint(painter)
        cap = cached_sprite(("cap", accent), CAP_AREA, scale, ratio, lambda p: self._paint_cap(p, 0.0, accent))
        cap.paint(painter, travel_y(fader))

    def _paint_strip(self, painter: QPainter, scale: float, ratio: float) -> None:
        """The whole strip: the printed parts from their picture, and what the strip shows on top of them."""
        key = self._printed_key()
        if not self._current(self.printed, key, scale, ratio):
            self.printed = draw(key, scale, ratio, self._paint_printed)
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
        painter.setFont(print_font(self.font(), 10, QFont.Weight.Bold))
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
        if not look.configured and not self.playing:
            painter.setOpacity(UNCONFIGURED_OPACITY)
        self._paint_lcd(painter)
        for row, (name, color) in enumerate(BUTTONS):
            if self._lit(state.leds[name.lower()]):
                self._paint_key(painter, button_rect(row), color, lit=True)
        painter.setOpacity(1)
        if self.hasFocus() and not self.playing:
            painter.setPen(QPen(QColor(current_colors().accent), 1.5, Qt.PenStyle.DotLine))
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

    @property
    def playing(self) -> bool:
        """
        Play: the mouse is a hand on the device, and the strip looks like the device, without what the editor marks
        (the selection, the focus, the hover, a strip nobody configured).
        """
        return self.preview.mover is None

    def _paint_outline(self, painter: QPainter, body: QRectF) -> None:
        """
        The outline of the strip: in the accent when it is selected or dragged, dashed when nobody tells what it shows.
        In Play only the edge of the strip, as on the device.
        """
        painter.setBrush(Qt.BrushStyle.NoBrush)
        accent = QColor(current_colors().accent)
        if self.playing:
            pen = QPen(QColor(HW.strip_edge), 1)
        elif self.selected or self.lifted:
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
            paint_led(painter, *ring_led(led), 2.4, HW.ring, False)
        # the knob: black rubber with a ribbed edge around a smooth top, lit from the top left
        painter.setPen(QPen(QColor(HW.lcd_bezel), 1))
        side = QRadialGradient(center + QPointF(-5, -6), 22)
        side.setColorAt(0, QColor(HW.knob_top))
        side.setColorAt(1, QColor(HW.knob_bottom))
        painter.setBrush(side)
        painter.drawEllipse(center, KNOB_RADIUS, KNOB_RADIUS)
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
        color, off = QColor(LCD_COLORS[state.color]), QColor(LCD_COLORS["off"])
        backlight = mix(color, off, level)
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
        painter.setBrush(mix(backlight, QColor(LCD_PANEL), LCD_TINT))
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
        light = mix(color, off, level if level in (0.0, 1.0) else DIM_TEXT)
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
        font = print_font(self.font(), 10 if len(text) < 10 else 9)
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
        font = print_font(self.font(), 8, QFont.Weight.Bold)
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
        body = led if lit else mix(led, QColor(HW.key), KEY_TINT)
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
            paint_meter_led(painter, led, lit=False)
        painter.setFont(print_font(self.font(), 7, QFont.Weight.Bold))
        painter.setPen(QColor(HW.print))
        for text, led in (("CLIP", METER_LEDS - 1), ("SIG", 0)):
            y = meter_led(led).center().y()
            painter.drawText(QRectF(METER.right() + 3, y - 5, 26, 10), Qt.AlignmentFlag.AlignVCenter, text)

    def _paint_scale(self, painter: QPainter) -> None:
        """The dB scale on both sides of the slot: the marks, the ticks between them, and the boxes around 0 dB."""
        painter.setFont(print_font(self.font(), 7))
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
        painter.setFont(print_font(self.font(), 9, QFont.Weight.Bold))
        painter.setPen(QColor(HW.tag_text))
        painter.drawText(STRIP_TAG, Qt.AlignmentFlag.AlignCenter, number)

    # -- input ----------------------------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        assert event is not None
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.preview.pick(self.index)
        if self.preview.mover is not None:
            self._press = event.position().toPoint()
        hand = self.preview.hand
        point = event.position() / self.preview.scale
        part = part_at(point)
        if hand is None or part is None:
            return
        # with Alt the fader moves without a touch, like the device moving it by itself
        touching = not event.modifiers() & Qt.KeyboardModifier.AltModifier
        self.held = (part, touching)
        match part:
            case "fader":
                if touching:
                    hand.touch(self.index, True)
                self.dragged_fader = fraction_at(point.y())
                hand.move(self.index, self.dragged_fader, hand=touching)
                self.update()
            case "encoder":
                self.encoder.press(point)
            case row:
                hand.press(self.index, list(Button)[row], True)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        assert event is not None
        mover = self.preview.mover
        if mover is not None:
            point = event.position().toPoint()
            if mover.dragging:
                mover.drag_to(self.mapToParent(point).x())
            elif self._press is not None and (point - self._press).manhattanLength() >= DRAG_DISTANCE():
                mover.start_drag(self.index, self._press.x() / self.preview.scale)
                mover.drag_to(self.mapToParent(point).x())
            return
        if self.preview.hand is None or self.held is None:
            return
        if self.held[0] == "fader":
            self.dragged_fader = fraction_at(event.position().y() / self.preview.scale)
            self.preview.hand.move(self.index, self.dragged_fader, self.held[1])
            self.update()
        elif self.held[0] == "encoder":
            self.encoder.move(event.position() / self.preview.scale, DRAG_DISTANCE() / self.preview.scale)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        self._press = None
        mover = self.preview.mover
        if mover is not None and mover.dragging:
            mover.drop()
        held, self.held = self.held, None
        hand = self.preview.hand
        if hand is None or held is None:
            return
        match held[0]:
            case "fader":
                hand.touch(self.index, False)
                self.dragged_fader = None
                self.update()
            case "encoder":
                self.encoder.release()
            case row:
                hand.press(self.index, list(Button)[row], False)

    def _hand_does(self, action: Callable[[Hand], None]) -> None:
        # a timer of the encoder can go off after the window stopped being a hand
        if self.preview.hand is not None:
            action(self.preview.hand)

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        """On a device the mouse is a hand on, the wheel turns the encoder (a notch is a step)."""
        assert event is not None
        if self.preview.hand is None or not event.angleDelta().y():
            event.ignore()
            return
        self.encoder.wheel(event.angleDelta().y())

    def contextMenuEvent(self, a0: QContextMenuEvent | None) -> None:
        assert a0 is not None
        mover = self.preview.mover
        if mover is None:
            a0.ignore()
            return
        self.preview.pick(self.index)
        mover.menu_for(self.index).exec(a0.globalPos())

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
