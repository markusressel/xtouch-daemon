"""
Painting the parts of the hardware: the colors of the panel, LEDs that glow, and pictures of the parts that don't
change, painted once per scale and kept (`cached_sprite()`).
"""

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil, floor

from PyQt6.QtCore import QPointF, QRectF, QSizeF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from xtouch_daemon.gui.domain.tokens import HARDWARE
from xtouch_daemon.gui.quick.device.geometry import HEIGHT, METER_GREEN, METER_LEDS, WIDTH, meter_led

HW = HARDWARE
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


def mix(color: QColor, base: QColor, amount: float) -> QColor:
    """`amount` of `color` over `base`."""
    return QColor.fromRgbF(
        color.redF() * amount + base.redF() * (1 - amount),
        color.greenF() * amount + base.greenF() * (1 - amount),
        color.blueF() * amount + base.blueF() * (1 - amount),
    )


def paint_led(painter: QPainter, start: QPointF, end: QPointF, width: float, color: str, lit: bool) -> None:
    """An LED, a short bar from `start` to `end` like those of the device: lit with a glow, or dark."""
    led = QColor(color)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if lit:
        glow = QColor(led)
        for extra, alpha in ((5, 40), (2.5, 90)):
            glow.setAlpha(alpha)
            painter.setPen(QPen(glow, width + extra, cap=Qt.PenCapStyle.RoundCap))
            painter.drawLine(start, end)
    painter.setPen(QPen(led if lit else mix(led, QColor(HW.led_off), LED_OFF_TINT), width, cap=Qt.PenCapStyle.RoundCap))
    painter.drawLine(start, end)


def paint_meter_led(painter: QPainter, led: int, lit: bool) -> None:
    """The LED `led` of the meter (0 at the bottom): green, orange, and red at the top."""
    color = HW.meter_high if led == METER_LEDS - 1 else HW.meter_mid if led >= METER_GREEN else HW.meter_low
    rect = meter_led(led)
    half = QPointF(0, rect.height() / 2 - 1.5)
    paint_led(painter, rect.center() - half, rect.center() + half, rect.width(), color, lit)


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


def draw(key: object, scale: float, ratio: float, paint: Callable[[QPainter, float, float], None]) -> _Picture:
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


def cached_sprite(
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


def print_font(base: QFont, size: int, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    """The font of the fine print on the panel."""
    font = QFont(base)
    font.setPixelSize(size)
    font.setWeight(weight)
    return font
