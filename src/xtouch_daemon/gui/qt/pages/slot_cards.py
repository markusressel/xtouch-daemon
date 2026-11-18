"""
The cards of the page Slots: the candidates of a slot on a rail (`StackList`), each as a rule (`candidate_rule`):
its condition as chips, what it shows, and where it stands against the one the device shows.
"""

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QDropEvent, QKeyEvent, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.gui.domain.slot_stacks import (
    ALWAYS,
    EMPTY,
    Row,
    RowState,
    free_text,
    free_words,
    is_pool,
    lcd_colors,
    readable,
    row_state,
)
from xtouch_daemon.gui.qt.fields.basics import ElidedLabel, entity_label, label
from xtouch_daemon.gui.qt.fields.controls import LcdBadge
from xtouch_daemon.gui.qt.theme.style import current_colors, set_role
from xtouch_daemon.gui.qt.theme.tokens import LCD_COLORS, Entity, Motion, Space
from xtouch_daemon.slots.model import AUTO

_INDEX = Qt.ItemDataRole.UserRole


class StackList(QListWidget):
    """The candidates of a slot: dragged or moved with Ctrl+Up/Down into another order."""

    reordered = pyqtSignal(list, int, arguments=["order", "current"])
    """The candidates in their new order (their indexes before), and where the moved one is now."""

    def __init__(self) -> None:
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        # as high as its rows (see `grow_to`) and as wide as the widest (see `fill`): a scroll bar would cover a row,
        # the column of the cards scrolls instead
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # picked on a tint: the chips of its row keep their colors; no frame of its own, the card is the frame
        set_role(self, "stack")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.resize_animation = QVariantAnimation(self)
        self.resize_animation.setDuration(Motion.RESIZE)
        self.resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.resize_animation.valueChanged.connect(lambda height: self.setFixedHeight(int(height)))

    def grow_to(self, height: int) -> None:
        """
        Grows or shrinks to `height` (its rows) smoothly, so a card that gets a line more or less doesn't jump; at
        once while it is not shown yet.
        """
        animation = self.resize_animation
        target = animation.endValue() if animation.state() == QAbstractAnimation.State.Running else self.height()
        if target == height:
            return
        animation.stop()
        if not self.isVisible():
            self.setFixedHeight(height)
            return
        animation.setStartValue(self.height())
        animation.setEndValue(height)
        animation.start()

    def order(self) -> list[int]:
        # without the end of a dark slot (see `fill`), which is no candidate
        indexes = [self.item(index).data(_INDEX) for index in range(self.count())]  # pyright: ignore[reportOptionalMemberAccess]
        return [index for index in indexes if index is not None]

    def keyPressEvent(self, e: QKeyEvent | None) -> None:
        assert e is not None
        step = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}.get(Qt.Key(e.key()))
        current = self.currentRow()
        if step is None or not e.modifiers() & Qt.KeyboardModifier.ControlModifier or current < 0:
            super().keyPressEvent(e)
            return
        target = current + step
        if 0 <= target < self.count():
            order = self.order()
            order.insert(target, order.pop(current))
            self.reordered.emit(order, target)

    def dropEvent(self, event: QDropEvent | None) -> None:
        super().dropEvent(event)
        self.reordered.emit(self.order(), self.currentRow())

    def fill(
        self,
        candidates: list[Row],
        shown: int | None,
        why: dict[int, str],
        values: Mapping[str, Any],
        dark: bool = False,
        member: tuple[str, str] | None = None,
    ) -> None:
        """
        The candidates of a slot on its rail; `dark`: none of them has anything to show, so the rail ends in a row
        of its own, the dark strip, which is the one shown. `member`: what the pool of the one shown hands out, and
        who else waits for a slot (see `member_summary`).
        """
        self.clear()
        count = len(candidates) + dark
        for index, candidate in enumerate(candidates):
            item = QListWidgetItem()
            item.setData(_INDEX, index)
            self.addItem(item)
            state = row_state(index, shown, dark)
            widget = candidate_rule(
                candidate,
                state,
                index,
                count,
                values,
                why.get(index, ""),
                member if state == "shown" else None,
            )
            self.setItemWidget(item, widget)
            item.setSizeHint(self.itemWidget(item).sizeHint())  # pyright: ignore[reportOptionalMemberAccess]
        if dark and candidates:
            item = QListWidgetItem()
            # no candidate: it can't be picked, moved or dropped on
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(item)
            end = CandidateRow(len(candidates), count, "shown", "", numbered=False)
            end.rule.addWidget(label("nothing to show: the strip is dark", "hint"))
            end.rule.addWidget(LcdBadge("off", "off: the LCD is dark"))
            end.rule.addStretch()
            end.setToolTip("No candidate has anything to show now, so the strip is dark")
            self.setItemWidget(item, end)
            item.setSizeHint(end.sizeHint())
        if self.count() == 0:
            item = QListWidgetItem(f"{AUTO} (no entry)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(item)
        rows_height = sum(self.sizeHintForRow(index) for index in range(self.count()))
        self.grow_to(rows_height)
        self.setMinimumWidth(self.sizeHintForColumn(0) + 2 * self.frameWidth())


RAIL = 24
"""The width of the rail on the left of a card: a line through its candidates, with a node on each."""
DIMMED = {"passed": 0.55, "unreached": 0.4}
"""How much of a rule shows above the candidate shown and below it."""


class CandidateRow(QWidget):
    """
    A candidate on the rail of its card, which joins the candidates from the top: `else` between two, a node on each
    (green on the one the device shows), its number and its rule (`rule`, filled by the page). Above the one shown its
    rule is dimmed, with why it did not win under it; below it, dimmed more: not reached.
    """

    def __init__(self, index: int, count: int, state: RowState, reason: str, numbered: bool = True):
        super().__init__()
        self.first = index == 0
        self.last = index == count - 1
        self.state = state
        outer = QVBoxLayout(self)
        outer.setContentsMargins(RAIL, 0, Space.S, Space.XS if self.last else 0)
        outer.setSpacing(0)
        if not self.first:
            # the band of `else` on the rail, painted by `paintEvent`
            outer.addSpacing(self.fontMetrics().height() + 2 * Space.XS)
        self.line = QWidget()
        self.rule = QHBoxLayout(self.line)
        self.rule.setContentsMargins(0, Space.XS if self.first else 0, 0, 0)
        self.rule.setSpacing(Space.S)
        number = label(str(index + 1) if numbered else "", "hint")
        number.setFixedWidth(Space.M)
        self.rule.addWidget(number)
        outer.addWidget(self.line)
        if state in DIMMED:
            effect = QGraphicsOpacityEffect(self.line)
            effect.setOpacity(DIMMED[state])
            self.line.setGraphicsEffect(effect)
        if reason:
            why = label(f"✗ {reason}", "hint")
            why.setContentsMargins(Space.M + Space.S, 0, 0, 0)
            outer.addWidget(why)
        if state == "shown":
            self.setToolTip("The device shows this one now")
        elif state == "unreached":
            self.setToolTip("Not reached: a candidate above it is shown")

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        colors = current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = RAIL / 2
        node = self.line.geometry().center().y()
        painter.setPen(QPen(QColor(colors.control_border), 2))
        painter.drawLine(
            QPointF(x, 0 if not self.first else node), QPointF(x, self.height() if not self.last else node)
        )
        if self.state == "shown":
            painter.setPen(QPen(QColor(colors.tone_good), 2))
            painter.setBrush(QColor(colors.tone_good))
        else:
            painter.setPen(QPen(QColor(colors.text_muted if self.state == "passed" else colors.control_border), 2))
            painter.setBrush(QColor(colors.raised))
        painter.drawEllipse(QPointF(x, node), 5, 5)
        if not self.first:
            painter.setPen(QColor(colors.text_muted))
            band = QRectF(RAIL, 0, self.width() - RAIL, self.fontMetrics().height() + 2 * Space.XS)
            painter.drawText(band, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "else")


def chip(text: str, show: str, values: Mapping[str, Any]) -> QWidget:
    """
    A part of a condition as an outlined chip: in words (`present` says what has to be present, see `readable`), in
    the color of presence when it asks only about presence, else of a state; `always` is no condition, so it is a
    hint.
    """
    if text == ALWAYS:
        return label(text, "hint")
    words, presence = readable(text, show, values)
    widget = entity_label(words, Entity.PRESENCE if presence else Entity.STATE, chip=True)
    # outlined: a condition, apart from the filled chip of what the slot shows
    set_role(widget, "outline", "variant")
    widget.setToolTip(f"In the file: {text}")
    return widget


def option_text(value: Any) -> str:
    """A value of an option as in the file, without quotes: `white`, `true`, `[a, b]`."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return "[" + ", ".join(option_text(item) for item in value) + "]"  # pyright: ignore[reportUnknownVariableType]
    return str(value)


def candidate_rule(
    candidate: Row,
    state: RowState,
    index: int,
    count: int,
    values: Mapping[str, Any],
    reason: str = "",
    member: tuple[str, str] | None = None,
) -> QWidget:
    """
    A candidate as a rule, read from the top like if, else if, else: `when gaming → auto`, then
    `otherwise → browser` for the last one without a condition, `when (app without a slot) → apps` for a pool
    without one (it shows only while it has a member no other slot has). States and what it shows are chips
    in their colors (see `Entity`). On the rail of its card (see `CandidateRow`), with why it did not win
    (`reason`). On the one shown, the chip of a pool names what it hands out (`member`: `apps · firefox`), its
    tooltip who waits.
    """
    widget = CandidateRow(index, count, state, reason)
    layout = widget.rule
    if candidate.chips == (ALWAYS,) and is_pool(values, candidate.show):
        layout.addWidget(label("when", "hint"))
        word = entity_label(free_words(values, candidate.show), Entity.PRESENCE, chip=True)
        # outlined like the other conditions: a member is there, as `present` of a channel
        set_role(word, "outline", "variant")
        word.setToolTip(free_text(values, candidate.show))
        layout.addWidget(word)
    elif candidate.chips == (ALWAYS,):
        word = "otherwise" if index == count - 1 and count > 1 else ALWAYS
        layout.addWidget(label(word, "hint"))
    else:
        layout.addWidget(label("when", "hint"))
        for position, part in enumerate(candidate.chips):
            if position:
                layout.addWidget(label("or", "hint"))
            layout.addWidget(chip(part, candidate.show, values))
    layout.addWidget(label("→", "hint"))
    if candidate.show == EMPTY:
        layout.addWidget(label(candidate.show, "hint"))
    elif member is not None:
        name, waiting = member
        shows = entity_label(f"{candidate.show} · {name}", Entity.CHANNEL, True)
        shows.setToolTip(f"{candidate.show} hands out {name} here. " + (waiting or "Nobody else waits for a slot."))
        layout.addWidget(shows)
    else:
        layout.addWidget(entity_label(candidate.show, Entity.CHANNEL, True))
    for color, where in lcd_colors(values, candidate):
        if color in LCD_COLORS:
            layout.addWidget(LcdBadge(color, f"{color}: {where}"))
    # a color the LCD has no backlight for stays as text, for the problems to name
    rest = {
        name: value
        for name, value in candidate.options.items()
        if name != "color" or not (isinstance(value, str) and value in LCD_COLORS)
    }
    if rest:
        options = ElidedLabel(", ".join(f"{name} = {option_text(value)}" for name, value in rest.items()))
        set_role(options, "hint")
        options.own_tip = True
        options.setToolTip("Options of the strip in this slot only: " + options.text())
        layout.addWidget(options, 1)
    else:
        layout.addStretch()
    return widget
