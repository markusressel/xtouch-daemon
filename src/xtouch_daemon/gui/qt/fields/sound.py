"""
The sound of the channels, as the daemon tells it (`Snapshot.sounding`): a small animation beside a channel that has
sound right now, so playing something shows which channels take it. Each type moves its own way, calm and small:

- an output and applications: three bars, like a level meter;
- an input: a ring that spreads from a dot, like a microphone that picks up;
- a person: a dot that breathes while they talk.

Home Assistant and custom channels have no sound. Nothing moves, and no timer runs, while nothing has sound.
"""

import math
import time
import zlib
from enum import StrEnum

from PyQt6.QtCore import QObject, QPointF, QRectF, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QWidget

from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.gui.qt.theme.tokens import Entity


class Sound(StrEnum):
    """How a channel shows its sound."""

    BARS = "bars"
    RIPPLE = "ripple"
    PULSE = "pulse"


SOUNDS = {"output": Sound.BARS, "apps": Sound.BARS, "input": Sound.RIPPLE, "person": Sound.PULSE}
"""The animation of each type of channel that can have sound."""
SIZE = QSize(14, 12)
"""The room of an animation, beside the name of its channel."""
FRAME = 50
"""Milliseconds between two frames: 20 a second, enough for movements this slow."""
OPACITY = 0.8
"""In the hue of the channels, a little faded: it is beside the name, not over it."""


def sound_of(channel_type: object) -> Sound | None:
    """The animation of a type of channel, None for one without sound."""
    return SOUNDS.get(str(channel_type))


def clock_of(channel: str) -> float:
    """
    The clock of the animation of a channel: the time, a little ahead by its name, so the channels don't move in
    step.
    """
    return time.monotonic() + zlib.crc32(channel.encode()) % 1000 / 1000


class Sounding(QObject):
    """
    Which channels have sound, and the clock of their animations: `tick` while one has sound, for whatever shows
    them to paint the next frame.
    """

    changed = pyqtSignal(arguments=[])
    tick = pyqtSignal(arguments=[])

    def __init__(self) -> None:
        super().__init__()
        self.ids: frozenset[str] = frozenset()
        self.timer = QTimer(self)
        self.timer.setInterval(FRAME)
        self.timer.timeout.connect(self.tick)

    def show(self, ids: tuple[str, ...]) -> None:
        """The channels that have sound now (none without a daemon)."""
        new = frozenset(ids)
        if new == self.ids:
            return
        self.ids = new
        if new:
            self.timer.start()
        else:
            self.timer.stop()
        self.changed.emit()

    def sounds(self, channel: str) -> bool:
        return channel in self.ids


_SOUNDING: Sounding | None = None


def sounding() -> Sounding:
    """The sound of the channels for the whole GUI: the window tells it (see `MainWindow.refresh_preview`)."""
    # one for all, as the daemon is one
    global _SOUNDING
    if _SOUNDING is None:
        _SOUNDING = Sounding()
    return _SOUNDING


def paint_sound(painter: QPainter, rect: QRectF, sound: Sound, at: float, color: str) -> None:
    """One frame of `sound` in `rect`, `at` seconds on a clock (`time.monotonic()`)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(0, 0, 0, 0))
    hue = QColor(color)
    hue.setAlphaF(OPACITY)
    center = rect.center()
    match sound:
        case Sound.BARS:
            # three bars of their own pace, never quite still and never all up at once
            width, gap = 2.0, 2.0
            left = center.x() - (3 * width + 2 * gap) / 2
            painter.setBrush(hue)
            for bar, (pace, shift) in enumerate(((1.1, 0.0), (1.7, 0.35), (1.3, 0.7))):
                wave = 0.5 + 0.5 * math.sin(2 * math.pi * (pace * at + shift))
                height = rect.height() * (0.3 + 0.7 * wave)
                x = left + bar * (width + gap)
                painter.drawRoundedRect(QRectF(x, rect.bottom() - height, width, height), 1, 1)
        case Sound.RIPPLE:
            # a dot, and a ring that spreads from it and fades
            painter.setBrush(hue)
            painter.drawEllipse(center, 2.0, 2.0)
            phase = (at / 1.4) % 1.0
            ring = QColor(hue)
            ring.setAlphaF(OPACITY * (1 - phase))
            painter.setPen(ring)
            painter.setBrush(QColor(0, 0, 0, 0))
            radius = 2.5 + phase * (min(rect.width(), rect.height()) / 2 - 3)
            painter.drawEllipse(center, radius, radius)
        case Sound.PULSE:
            # a dot that breathes, about once a second
            wave = 0.5 + 0.5 * math.sin(2 * math.pi * at)
            breath = QColor(hue)
            breath.setAlphaF(OPACITY * (0.55 + 0.45 * wave))
            painter.setBrush(breath)
            radius = 2.5 + 1.5 * wave
            painter.drawEllipse(QPointF(center), radius, radius)
    painter.restore()


class SoundBadge(QWidget):
    """
    The sound of one channel, e.g. after its chip on a card: empty while it has none, its room kept, so nothing moves
    when the sound comes and goes.
    """

    def __init__(self, channel: str, sound: Sound):
        super().__init__()
        self.channel = channel
        self.sound = sound
        self.setFixedSize(SIZE)
        clock = sounding()
        clock.tick.connect(self._tick)
        clock.changed.connect(self._changed)
        self._changed()

    @property
    def active(self) -> bool:
        return sounding().sounds(self.channel)

    def _changed(self) -> None:
        self.setToolTip(f"{self.channel} has sound now" if self.active else "")
        self.update()

    def _tick(self) -> None:
        if self.active and self.isVisible():
            self.update()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        if not self.active:
            return
        painter = QPainter(self)
        hue = getattr(current_colors(), Entity.CHANNEL)
        paint_sound(painter, QRectF(self.rect()), self.sound, clock_of(self.channel), hue)
        painter.end()
