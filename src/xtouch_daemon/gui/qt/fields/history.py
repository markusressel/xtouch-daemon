"""
The last day of a state, as the page States shows it under what the daemon says about it: a bar per hour of the clock,
as high as the share of the hour the state was on. The mouse on a bar tells the hour.
"""

from PyQt6.QtCore import QEvent, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QHelpEvent, QMouseEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import QToolTip, QWidget

from xtouch_daemon.gui.domain.states import Hour
from xtouch_daemon.gui.qt.theme.style import current_colors

BARS_HEIGHT = 32
"""Pixels of the bars: a bar of an hour the state was on all along."""
GAP = 2
"""Pixels between two bars."""
LABEL_EVERY = 6
"""Every how many hours of the clock a label tells the hour under its bar."""


class HistoryBars(QWidget):
    """A bar per hour (`show_hours`), oldest on the left, the current one up to now on the right."""

    def __init__(self) -> None:
        super().__init__()
        self.hours: tuple[Hour, ...] = ()
        self.setMouseTracking(True)
        self.setMinimumWidth(200)

    def show_hours(self, hours: tuple[Hour, ...]) -> None:
        if hours != self.hours:
            self.hours = hours
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(480, BARS_HEIGHT + self.fontMetrics().height() + 2)

    def minimumSizeHint(self) -> QSize:
        return QSize(200, self.sizeHint().height())

    def _bar_width(self) -> float:
        return self.width() / max(len(self.hours), 1)

    def hour_at(self, x: float) -> Hour | None:
        """The hour of the bar at `x`, None beside the bars."""
        index = int(x // self._bar_width())
        return self.hours[index] if self.hours and 0 <= index < len(self.hours) else None

    def tip_at(self, x: float) -> str:
        hour = self.hour_at(x)
        return hour.describe() if hour is not None else ""

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
        if not self.hours:
            return
        colors = current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self._bar_width()
        hue = QColor(colors.state)
        empty = QColor(colors.border)
        for index, hour in enumerate(self.hours):
            left = index * width + GAP / 2
            share = hour.share
            if share is None:
                # not watched: a dotted floor
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(empty)
                for dot in range(int(left), int(left + width - GAP), 4):
                    painter.drawRect(QRectF(dot, BARS_HEIGHT - 1, 2, 1))
                continue
            # watched: a floor, and the bar on it
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(empty)
            painter.drawRect(QRectF(left, BARS_HEIGHT - 1, width - GAP, 1))
            if share > 0:
                height = max(2.0, share * (BARS_HEIGHT - 1))
                painter.setBrush(hue)
                painter.drawRoundedRect(QRectF(left, BARS_HEIGHT - height, width - GAP, height), 1.5, 1.5)
        # the hours of the clock under their bars, and now under the last one
        painter.setPen(QColor(colors.text_muted))
        metrics = self.fontMetrics()
        top = BARS_HEIGHT + 2
        # not too close to now, which would cover it
        for index, hour in enumerate(self.hours[:-3]):
            if hour.start.hour % LABEL_EVERY == 0:
                text = f"{hour.start:%H}:00"
                painter.drawText(int(index * width), top + metrics.ascent(), text)
        now = "now"
        painter.drawText(int(self.width() - metrics.horizontalAdvance(now)), top + metrics.ascent(), now)
        painter.end()
