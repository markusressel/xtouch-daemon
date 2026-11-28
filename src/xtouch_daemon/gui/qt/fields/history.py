"""
The last day of a state, as the page States shows it under what the daemon says about it: a bar per quarter of an hour
of the clock (`Span`), the time it was on at the bottom, in the color of the states, the time it was off above it, in
gray. A time no daemon watched has no bar. The mouse on a bar tells its time.
"""

from PyQt6.QtCore import QEvent, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QHelpEvent, QMouseEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import QToolTip, QWidget

from xtouch_daemon.gui.domain.states import Span
from xtouch_daemon.gui.qt.theme.style import current_colors

BARS_HEIGHT = 32
"""Pixels of the bars: a bar of a whole span the daemon watched."""
GAP = 1
"""Pixels between two bars."""
LABEL_EVERY = 6
"""Every how many hours of the clock a label tells the hour under its bar."""


class HistoryBars(QWidget):
    """A bar per span (`show_spans`), oldest on the left, the current one up to now on the right."""

    def __init__(self) -> None:
        super().__init__()
        self.spans: tuple[Span, ...] = ()
        self.setMouseTracking(True)
        self.setMinimumWidth(200)

    def show_spans(self, spans: tuple[Span, ...]) -> None:
        if spans != self.spans:
            self.spans = spans
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(480, BARS_HEIGHT + self.fontMetrics().height() + 2)

    def minimumSizeHint(self) -> QSize:
        return QSize(200, self.sizeHint().height())

    def _bar_width(self) -> float:
        return self.width() / max(len(self.spans), 1)

    def span_at(self, x: float) -> Span | None:
        """The span of the bar at `x`, None beside the bars."""
        index = int(x // self._bar_width())
        return self.spans[index] if self.spans and 0 <= index < len(self.spans) else None

    def tip_at(self, x: float) -> str:
        span = self.span_at(x)
        return span.describe() if span is not None else ""

    def event(self, a0: QEvent | None) -> bool:
        if isinstance(a0, QHelpEvent) and a0.type() == QEvent.Type.ToolTip:
            tip = self.tip_at(a0.pos().x())
            if tip:
                QToolTip.showText(a0.globalPos(), tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None:
            tip = self.tip_at(a0.position().x())
            # the footer shows the tip of what the mouse is on (see `HoverTips`); a shown tooltip follows the bar
            self.setToolTip(tip)
            if QToolTip.isVisible() and tip:
                QToolTip.showText(a0.globalPosition().toPoint(), tip, self)
        super().mouseMoveEvent(a0)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        if not self.spans:
            return
        colors = current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self._bar_width()
        hue = QColor(colors.state)
        off = QColor(colors.text_muted)
        off.setAlphaF(0.35)
        empty = QColor(colors.border)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, span in enumerate(self.spans):
            left = index * width + GAP / 2
            bar = max(width - GAP, 1.0)
            if not span.known:
                # not watched: a dotted floor
                painter.setBrush(empty)
                painter.drawRect(QRectF(left, BARS_HEIGHT - 1, bar, 1))
                continue
            scale = (BARS_HEIGHT - 1) / span.length
            on = span.on * scale
            watched = max(span.known * scale, 2.0)
            # off above, on at the bottom
            painter.setBrush(off)
            painter.drawRect(QRectF(left, BARS_HEIGHT - watched, bar, watched - on))
            if on:
                painter.setBrush(hue)
                painter.drawRect(QRectF(left, BARS_HEIGHT - max(on, 1.0), bar, max(on, 1.0)))
        # every sixth hour of the clock under its bar, and now under the last one
        painter.setPen(QColor(colors.text_muted))
        metrics = self.fontMetrics()
        top = BARS_HEIGHT + 2
        # not too close to now, which would cover it
        for index, span in enumerate(self.spans[:-12]):
            if span.start.hour % LABEL_EVERY == 0 and span.start.minute == 0:
                text = f"{span.start:%H}:00"
                painter.drawText(int(index * width), top + metrics.ascent(), text)
        now = "now"
        painter.drawText(int(self.width() - metrics.horizontalAdvance(now)), top + metrics.ascent(), now)
        painter.end()
