"""
The cards of the page Slots: the candidates of a slot on a rail (`StackList`), each as a rule (`candidate_rule`):
its condition as chips, what it shows (with the colors of its LCD, see `ShowChip`), and where it stands against the
one the device shows.
"""

import copy
import math
from collections.abc import Callable, Mapping
from functools import partial
from typing import Any

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QDropEvent, QIcon, QKeyEvent, QPainter, QPaintEvent, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
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
    ends_dark,
    free_text,
    free_words,
    is_pool,
    lcd_colors,
    readable,
    row_state,
)
from xtouch_daemon.gui.qt.fields.basics import ElidedLabel, entity_label, label
from xtouch_daemon.gui.qt.fields.controls import LcdBadge
from xtouch_daemon.gui.qt.fields.sound import SoundBadge, sound_of
from xtouch_daemon.gui.qt.motion import Fade, moving, picture_of
from xtouch_daemon.gui.qt.theme.style import current_colors, set_role
from xtouch_daemon.gui.qt.theme.tokens import LCD_COLORS, Entity, Motion, Space
from xtouch_daemon.slots.model import AUTO

_INDEX = Qt.ItemDataRole.UserRole
CANDIDATE_FLAGS = (
    Qt.ItemFlag.ItemIsSelectable
    | Qt.ItemFlag.ItemIsUserCheckable
    | Qt.ItemFlag.ItemIsEnabled
    | Qt.ItemFlag.ItemIsDragEnabled
)
"""The flags of the row of a candidate, those of a new item: it can be picked and moved."""


NODE = 5
"""The radius of a node of the rail: the dot of a candidate, filled green while the device shows it."""


def paint_node(painter: QPainter, center: QPointF, on: bool, ring: str, fill: str) -> None:
    """A node of the rail at `center`: green and filled while `on`, else a ring of `ring` filled with `fill`."""
    colors = current_colors()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(colors.tone_good if on else ring), 2))
    painter.setBrush(QColor(colors.tone_good if on else fill))
    painter.drawEllipse(center, NODE, NODE)
    painter.restore()


NODE_ICON = QSize(2 * NODE + 2 + Space.XS, 2 * NODE + 2)
"""The size of `node_icon`: the node with its ring, and room before the text after it."""


def node_icon(on: bool, ring: str, ratio: float) -> QIcon:
    """A node of the rail (`paint_node`) as an icon of `NODE_ICON`, e.g. before a text, hollow while off."""
    side = NODE_ICON.height()
    pixmap = QPixmap(math.ceil(NODE_ICON.width() * ratio), math.ceil(side * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_node(painter, QPointF(side / 2, side / 2), on, ring, "transparent")
    painter.end()
    return QIcon(pixmap)


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
        self.keys: list[object] = []
        """What makes each row, as `fill` showed it: a row whose key stays is kept as it is."""
        self.values: dict[str, Any] = {}
        """The configuration the rows show (a copy): its names and colors are in every row, a change makes all anew."""
        self.resize_animation = QVariantAnimation(self)
        self.resize_animation.setDuration(Motion.RESIZE)
        self.resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.resize_animation.valueChanged.connect(lambda height: self.setFixedHeight(int(height)))

    def grow_to(self, height: int) -> None:
        """
        Grows or shrinks to `height` (its rows) smoothly, so a card that gets a line more or less doesn't jump; at
        once while it doesn't move (see `motion.moving`).
        """
        animation = self.resize_animation
        target = animation.endValue() if animation.state() == QAbstractAnimation.State.Running else self.height()
        if target == height:
            return
        animation.stop()
        if not moving(self):
            self.setFixedHeight(height)
            return
        animation.setStartValue(self.height())
        animation.setEndValue(height)
        animation.start()

    def order(self) -> list[int]:
        # without the end of a dark slot (see `fill`), which is no candidate
        indexes = [self.item(index).data(_INDEX) for index in range(self.count())]  # pyright: ignore[reportOptionalMemberAccess]
        return [index for index in indexes if index is not None]

    def end_row(self) -> int:
        """The row that is no candidate (the dark end of the rail, or `auto` of an empty slot), -1 for none."""
        last = self.count() - 1
        item = self.item(last)
        return last if item is not None and item.data(_INDEX) is None else -1

    def keyPressEvent(self, e: QKeyEvent | None) -> None:
        assert e is not None
        step = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}.get(Qt.Key(e.key()))
        current = self.currentRow()
        if step is None or not e.modifiers() & Qt.KeyboardModifier.ControlModifier or current < 0:
            super().keyPressEvent(e)
            return
        if current == self.end_row():
            # the end of the rail stays where it is, and stays picked
            return
        target = current + step
        if 0 <= target < len(self.order()):
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
        The candidates of a slot on its rail, which ends in a row of its own, the dark strip (see `ends_dark`);
        `dark`: none of them has anything to show, so the dark strip is the one shown. `member`: what the pool of
        the one shown hands out, and who else waits for a slot (see `member_summary`).
        """
        count = len(candidates) + ends_dark(candidates)
        rows: list[tuple[object, Callable[[QListWidgetItem], QWidget | None]]] = []
        for index, candidate in enumerate(candidates):
            state = row_state(index, shown, dark)
            reason = why.get(index, "")
            shows = member if state == "shown" else None
            # what makes the row: of the count only whether it is the last one ("otherwise")
            key = ("candidate", candidate, state, index, index == count - 1, count > 1, reason, shows)
            rows.append((key, partial(self._candidate, candidate, state, index, count, values, reason, shows)))
        if ends_dark(candidates):
            # always the last option, so the card keeps its rows when the strip goes dark or lights up
            state = "shown" if dark else "" if shown is None else "unreached"
            rows.append(
                (("end", len(candidates), dark, state), partial(self._end, len(candidates), count, dark, state))
            )
        if not rows:
            rows.append((("auto",), self._no_entry))
        if values != self.values:
            # the names, colors and channels of the rows: every row is made anew (the document changes in place)
            self.values = copy.deepcopy(dict(values))
            self.keys = [None] * len(self.keys)
        self._show_rows(rows)
        rows_height = sum(self.sizeHintForRow(index) for index in range(self.count()))
        self.grow_to(rows_height)
        self.setMinimumWidth(self.sizeHintForColumn(0) + 2 * self.frameWidth())

    def _show_rows(self, rows: list[tuple[object, Callable[[QListWidgetItem], QWidget | None]]]) -> None:
        """
        The rows of `rows` (a key, and what makes the row for its item): a row whose key is the one it had stays as it
        is; one that changes fades through the card to its new look, one that comes fades in, one that goes fades out
        (see `gui/qt/motion.py`), so a change of one row moves only that row.
        """
        moves = moving(self) and bool(self.keys)
        behind = QColor(current_colors().raised)
        going: list[tuple[QRect, QPixmap]] = []
        while self.count() > len(rows):
            item = self.item(self.count() - 1)
            assert item is not None
            widget = self.itemWidget(item)
            if moves and widget is not None:
                going.append((self.visualItemRect(item), picture_of(widget)))
            self.takeItem(self.count() - 1)
        fades: list[tuple[QListWidgetItem, QPixmap]] = []
        for index, (key, make) in enumerate(rows):
            if index < len(self.keys) and index < self.count() and self.keys[index] == key:
                continue
            item = self.item(index)
            if item is None:
                item = QListWidgetItem()
                self.addItem(item)
                before = self._blank() if moves else None
            else:
                widget = self.itemWidget(item)
                before = picture_of(widget) if moves and widget is not None else None
                self.removeItemWidget(item)
            widget = make(item)
            if widget is not None:
                self.setItemWidget(item, widget)
                item.setSizeHint(widget.sizeHint())
            if before is not None:
                fades.append((item, before))
        self.keys = [key for key, _ in rows]
        if not fades and not going:
            return
        # where the rows are now
        self.executeDelayedItemsLayout()
        viewport = self.viewport()
        assert viewport is not None
        for item, before in fades:
            Fade(viewport, before, behind=behind, at=self.visualItemRect(item))
        for rect, before in going:
            Fade(viewport, before, at=rect)

    def _blank(self) -> QPixmap:
        """A picture of nothing: a row that comes fades in from it."""
        blank = QPixmap(1, 1)
        blank.fill(Qt.GlobalColor.transparent)
        return blank

    def _candidate(
        self,
        candidate: Row,
        state: RowState,
        index: int,
        count: int,
        values: Mapping[str, Any],
        reason: str,
        member: tuple[str, str] | None,
        item: QListWidgetItem,
    ) -> QWidget:
        item.setText("")
        item.setData(_INDEX, index)
        item.setFlags(CANDIDATE_FLAGS)
        return candidate_rule(candidate, state, index, count, values, reason, member)

    def _end(self, index: int, count: int, dark: bool, state: RowState, item: QListWidgetItem) -> QWidget:
        """The dark strip at the end of the rail."""
        item.setText("")
        item.setData(_INDEX, None)
        # no candidate: it can be picked (its slot, with why the strip is dark), not moved or dropped on
        item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        end = CandidateRow(index, count, state, "", numbered=False)
        text = "nothing to show: the strip is dark" if dark else "nothing to show: the strip goes dark"
        end.rule.addWidget(label(text, "hint"))
        end.rule.addWidget(LcdBadge("off", "off: the LCD is dark"))
        end.rule.addStretch()
        end.setToolTip(
            "No candidate has anything to show now, so the strip is dark"
            if dark
            else "When no candidate above has anything to show, the strip goes dark"
        )
        return end

    def _no_entry(self, item: QListWidgetItem) -> None:
        """A slot without candidates: `auto`. It picks the slot, with what it shows without candidates."""
        item.setText(f"{AUTO} (no entry)")
        item.setData(_INDEX, None)
        item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        item.setSizeHint(QSize())


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
        # the middle of the rule, below the margin the first one has at its top
        line = self.line.geometry()
        top = self.rule.contentsMargins().top()
        node = line.top() + top + (line.height() - top) / 2
        painter.setPen(QPen(QColor(colors.control_border), 2))
        painter.drawLine(
            QPointF(x, 0 if not self.first else node), QPointF(x, self.height() if not self.last else node)
        )
        paint_node(
            painter,
            QPointF(x, node),
            self.state == "shown",
            colors.text_muted if self.state == "passed" else colors.control_border,
            colors.raised,
        )
        if not self.first:
            painter.setPen(QColor(colors.text_muted))
            band = QRectF(RAIL, 0, self.width() - RAIL, self.fontMetrics().height() + 2 * Space.XS)
            painter.drawText(band, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "else")


SWATCH = 10
"""The side of a swatch of an LCD color in the chip of what a slot shows."""


class ShowChip(QLabel):
    """
    What a candidate shows as a filled chip in the color of the channels, with the backlights its LCD can have as
    small swatches before the name: one for a channel, several for a pool that hands out channels of other colors.
    """

    def __init__(self, text: str, colors: tuple[str, ...]):
        super().__init__(text)
        set_role(self, "chip")
        set_role(self, Entity.CHANNEL.value, "entity")
        self.colors = colors
        if colors:
            # room for the swatches, before the padding of the chip
            self.setContentsMargins(len(colors) * (SWATCH + Space.XS) - Space.XS // 2, 0, 0, 0)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)
        if not self.colors:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(current_colors().control_border), 1))
        # on the middle of the text as it looks, not of its line: the line has room for descenders below and accents
        # above, which a name like `browser` doesn't use; between the middle of capitals and of lowercase letters
        metrics = self.fontMetrics()
        contents = self.contentsRect()
        baseline = contents.top() + (contents.height() - metrics.height()) / 2 + metrics.ascent()
        top = baseline - (metrics.capHeight() + metrics.xHeight()) / 4 - SWATCH / 2
        for index, color in enumerate(self.colors):
            painter.setBrush(QColor(LCD_COLORS[color]))
            left = Space.S + index * (SWATCH + Space.XS)
            painter.drawRoundedRect(QRectF(left + 0.5, top + 0.5, SWATCH - 1, SWATCH - 1), 2, 2)


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
    # a color the LCD has no backlight for has no swatch: the problems name it
    colors = tuple((color, where) for color, where in lcd_colors(values, candidate) if color in LCD_COLORS)
    lcd = "\n".join(f"The LCD: {color} ({where})" for color, where in colors)
    if candidate.show == EMPTY:
        layout.addWidget(label(candidate.show, "hint"))
        for color, where in colors:
            layout.addWidget(LcdBadge(color, f"{color}: {where}"))
    else:
        text = candidate.show if member is None else f"{candidate.show} · {member[0]}"
        shows = ShowChip(text, tuple(color for color, _ in colors))
        tip = ""
        if member is not None:
            tip = f"{candidate.show} hands out {member[0]} here. " + (member[1] or "Nobody else waits for a slot.")
        shows.setToolTip("\n\n".join(part for part in (tip, lcd) if part))
        layout.addWidget(shows)
        channel = values.get("channel", {}).get(candidate.show)
        sound = sound_of(channel.get("type")) if isinstance(channel, Mapping) else None
        if sound is not None:
            # moves while the channel has sound (see `fields.sound`)
            layout.addWidget(SoundBadge(candidate.show, sound))
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
