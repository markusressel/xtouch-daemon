"""
Where a channel or a state is used, as the device would show it: a small strip for each slot, lit where it is used
(see `SlotStrips`), then the rest (pools, states) in words.
"""

import re

from PyQt6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QHBoxLayout, QToolTip, QWidget

from xtouch_daemon.gui.qt.fields.basics import label
from xtouch_daemon.gui.qt.theme.style import current_colors
from xtouch_daemon.gui.qt.theme.tokens import Radius, Space
from xtouch_daemon.hardware.protocol import STRIPS

STRIP = QSize(16, 26)
"""The size of a strip of `SlotStrips`."""
GAP = 3
"""The room between two strips."""


class SlotStrips(QWidget):
    """
    The slots as a row of small strips, numbered from the left: filled in the color of slots where a slot shows it
    (`slots`), outlined where only the controls of a slot use it (`controls`), dim elsewhere. A click on a used one
    picks it (`picked`, 1 for the leftmost one).
    """

    picked = pyqtSignal(int, arguments=["slot"])

    def __init__(self) -> None:
        super().__init__()
        self.slots: set[int] = set()
        self.controls: set[int] = set()
        self.setFixedSize(STRIPS * STRIP.width() + (STRIPS - 1) * GAP, STRIP.height())
        self.setMouseTracking(True)

    def show_uses(self, slots: set[int], controls: set[int]) -> None:
        self.slots, self.controls = slots, controls
        self.update()

    def slot_at(self, point: QPoint) -> int | None:
        """The slot under a point, if it is used."""
        slot = point.x() // (STRIP.width() + GAP) + 1
        return slot if slot in self.slots | self.controls else None

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        slot = self.slot_at(a0.position().toPoint()) if a0 is not None else None
        self.setCursor(Qt.CursorShape.PointingHandCursor if slot is not None else Qt.CursorShape.ArrowCursor)
        if a0 is not None and slot is not None:
            how = "shows it" if slot in self.slots else "its controls use it"
            QToolTip.showText(a0.globalPosition().toPoint(), f"Slot {slot} {how}. Click to show the slot.", self)
        else:
            QToolTip.hideText()

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        slot = self.slot_at(a0.position().toPoint()) if a0 is not None else None
        if slot is not None:
            self.picked.emit(slot)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        colors = current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * 0.8)
        font.setBold(True)
        painter.setFont(font)
        hue = QColor(colors.slot)
        for index in range(STRIPS):
            slot = index + 1
            rect = QRectF(index * (STRIP.width() + GAP) + 0.5, 0.5, STRIP.width() - 1, STRIP.height() - 1)
            shown, controls = slot in self.slots, slot in self.controls
            if shown:
                fill = QColor(hue)
                fill.setAlpha(80)
                painter.setBrush(fill)
                painter.setPen(QPen(hue, 1))
            elif controls:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(hue, 1, Qt.PenStyle.DashLine))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(dim(colors.control_border), 1))
            painter.drawRoundedRect(rect, Radius.SMALL, Radius.SMALL)
            # the number where the display is, a fader track below it
            used = shown or controls
            painter.setPen(QColor(colors.text) if used else dim(colors.text_muted))
            painter.drawText(
                QRectF(rect.left(), rect.top() + 1, rect.width(), 12), Qt.AlignmentFlag.AlignCenter, str(slot)
            )
            track = hue if used else dim(colors.control_border)
            painter.setPen(QPen(track, 2, cap=Qt.PenCapStyle.RoundCap))
            middle = rect.center().x()
            painter.drawLine(QPointF(middle, rect.top() + 15), QPointF(middle, rect.bottom() - 4))


def dim(color: str) -> QColor:
    """A color of a strip that is not used: faint, so the used ones stand out."""
    value = QColor(color)
    value.setAlpha(110)
    return value


class UsedBy(QWidget):
    """
    "Used by", the slots that use it as `SlotStrips`, and the rest (`pool games`, `state call`) in words; `none`
    while nothing uses it.
    """

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Space.S)
        self.title = label("Used by", "hint")
        self.strips = SlotStrips()
        self.rest = label("", "hint", wrap=True)
        layout.addWidget(self.title)
        layout.addWidget(self.strips)
        layout.addWidget(self.rest, 1)

    def show_uses(self, where: tuple[str, ...], none: str) -> None:
        """`where` as `uses` and `state_uses` tell it: `slot 2`, `controls 5`, `pool games`, `state call`."""
        slots = {int(found[1]) for found in (re.fullmatch(r"slot (\d+)", entry) for entry in where) if found}
        controls = {int(found[1]) for found in (re.fullmatch(r"controls (\d+)", entry) for entry in where) if found}
        rest = [entry for entry in where if not re.fullmatch(r"(slot|controls) \d+", entry)]
        self.title.setVisible(bool(where))
        self.strips.setVisible(bool(slots | controls))
        self.strips.show_uses(slots, controls)
        self.rest.setText(", ".join(rest) if where else none)
