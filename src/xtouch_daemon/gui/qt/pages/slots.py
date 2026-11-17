"""
The slots under the drawing of the device: a bar of the states (live, with their overrides), a card per slot with its
stack (the candidates in order, their conditions as chips, ▶ on the one the device shows), and an inspector for the
candidate picked: what it shows, when, the options of its place, its channel and where else that is used, and the
controls of the slot.
"""

import dataclasses
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDropEvent, QKeyEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.channels import CHANNEL_TYPES, uses
from xtouch_daemon.gui.domain.schema import Option, strip_options
from xtouch_daemon.gui.domain.slot_stacks import (
    ALWAYS,
    EMPTY,
    Row,
    choices,
    controls_text,
    place_options,
    rows,
    stack_value,
)
from xtouch_daemon.gui.domain.slots_document import Validation
from xtouch_daemon.gui.domain.states import OVERRIDES, live_state, ordered
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import flat_button, label
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.pages.base import Audio, Page, button, card, row, set_text
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import Request, SetMode, SetOverride, SlotView, Snapshot
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
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def order(self) -> list[int]:
        return [self.item(index).data(_INDEX) for index in range(self.count())]  # pyright: ignore[reportOptionalMemberAccess]

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


def chip(text: str) -> QWidget:
    """A part of a condition; `always` is no condition, so it is a hint."""
    return label(text, "hint" if text == ALWAYS else "chip")


class SlotsPanel(Page):
    def __init__(
        self,
        editor: Editor,
        audio: Audio,
        snapshot: Callable[[], Snapshot | None],
        request: Callable[[Request], bool],
        show_channel: Callable[[str], None],
    ):
        """`show_channel` opens a channel on the page Channels."""
        super().__init__(editor, audio)
        self.snapshot = snapshot
        self.request = request
        self.show_channel = show_channel
        self.slot = 1
        """The slot picked (1 for the leftmost one)."""
        self.candidate: int | None = None
        """The candidate of the slot the inspector shows, None for none."""
        self.shown_live: tuple[object, ...] | None = None
        self.layout_.setContentsMargins(0, Space.S, 0, 0)
        self.state_bar = QHBoxLayout()
        self.state_bar.setSpacing(Space.S)
        self.layout_.addWidget(row(self.state_bar))
        self.state_buttons: dict[str, QToolButton] = {}
        body = QHBoxLayout()
        body.setSpacing(Space.L)
        cards = QWidget()
        self.cards = QVBoxLayout(cards)
        self.cards.setSpacing(Space.S)
        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.card_scroll.setWidget(cards)
        body.addWidget(self.card_scroll, 1)
        self.lists: list[StackList] = []
        self.card_frames: list[QFrame] = []
        for slot in range(1, protocol.STRIPS + 1):
            self._card(slot)
        self.cards.addStretch()
        self.inspector, inspector = card()
        self.title = label("", "section")
        inspector.addWidget(self.title)
        what = QHBoxLayout()
        what.addWidget(label("Shows"))
        self.show_box = QComboBox()
        self.show_box.setEditable(True)
        self.show_box.setToolTip("A channel, a pool (`auto`) or `-` for nothing")
        self.show_box.activated.connect(lambda _: self._edit_show())
        self.show_box.lineEdit().editingFinished.connect(self._edit_show)  # pyright: ignore[reportOptionalMemberAccess]
        what.addWidget(self.show_box, 1)
        inspector.addWidget(row(what))
        when = QHBoxLayout()
        when.addWidget(label("When"))
        self.when_edit = QLineEdit()
        self.when_edit.setPlaceholderText("always")
        self.when_edit.setToolTip("States and modes with `and`, `or`, `not`, parentheses and `present`")
        self.when_edit.editingFinished.connect(self._edit_when)
        when.addWidget(self.when_edit, 1)
        inspector.addWidget(row(when))
        inspector.addWidget(self.problem)
        self.place = QVBoxLayout()
        inspector.addWidget(row(self.place))
        self.place_rows: list[OptionRow] = []
        self.channel = label("", "hint", wrap=True)
        inspector.addWidget(self.channel)
        self.channel_button = button("pencil-outline", "Edit the channel")
        self.channel_button.clicked.connect(lambda: self.show_channel(self._candidate_row().show))
        inspector.addWidget(self.channel_button)
        self.controls = label("", "hint", wrap=True)
        inspector.addWidget(self.controls)
        inspector.addStretch()
        # the options of a place need more room than the space under the drawing has
        self.inspector_scroll = QScrollArea()
        self.inspector_scroll.setWidgetResizable(True)
        self.inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inspector_scroll.setWidget(self.inspector)
        self.inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inspector_scroll.setFixedWidth(560)
        body.addWidget(self.inspector_scroll)
        self.layout_.addWidget(row(body), 1)
        self._show()

    def _card(self, slot: int) -> None:
        frame, layout = card()
        layout.setContentsMargins(Space.M, Space.S, Space.M, Space.S)
        layout.setSpacing(Space.XS)
        header = QHBoxLayout()
        header.addWidget(label(f"Slot {slot}"))
        header.addStretch()
        add = flat_button("plus", "Add a candidate (at the end; Ctrl+Up moves it up)")
        add.clicked.connect(lambda: self.add(slot))
        header.addWidget(add)
        remove = flat_button("delete-outline", "Remove the candidate picked")
        remove.clicked.connect(lambda: self.remove(slot))
        header.addWidget(remove)
        layout.addWidget(row(header))
        stack = StackList()
        stack.currentRowChanged.connect(lambda index: self._picked(slot, index))
        stack.reordered.connect(lambda order, current: self.reorder(slot, order, current))
        layout.addWidget(stack)
        self.lists.append(stack)
        self.card_frames.append(frame)
        self.cards.addWidget(frame)

    # -- showing --------------------------------------------------------------------------------------------------

    def show_document(self, change: Change) -> None:
        if change.scope is Scope.VALUE and change.path[:1] == ("slots",):
            # an option of the place, from a row of the inspector: it shows it already
            self._show_cards()
        else:
            self._show()

    def _show(self) -> None:
        self._show_state_bar()
        self._show_cards()
        self._show_inspector()

    def _show_state_bar(self) -> None:
        while (item := self.state_bar.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                widget.deleteLater()
        self.state_buttons = {}
        for name in ordered(self.document.get(("state",), {})):
            state_button = QToolButton()
            state_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(state_button)
            mode = bool(self.document.get(("state", name, "mode")))
            for value in OVERRIDES:
                if mode and value == "off":
                    continue
                action = menu.addAction("pick" if mode and value == "on" else value)
                assert action is not None
                action.triggered.connect(lambda _=False, name=name, value=value: self.override(name, value))
            state_button.setMenu(menu)
            self.state_bar.addWidget(state_button)
            self.state_buttons[name] = state_button
        self.state_bar.addStretch()
        self.shown_live = None
        self.show_live(self.snapshot())

    def _show_cards(self) -> None:
        live = self._live_slots(self.snapshot())
        for slot, stack in enumerate(self.lists, start=1):
            stack.blockSignals(True)
            stack.clear()
            view = live.get(slot)
            for index, candidate in enumerate(rows(self.document.values, slot)):
                item = QListWidgetItem()
                item.setData(_INDEX, index)
                stack.addItem(item)
                stack.setItemWidget(item, self._row_widget(candidate, view is not None and view.candidate == index))
                item.setSizeHint(stack.itemWidget(item).sizeHint())  # pyright: ignore[reportOptionalMemberAccess]
            if stack.count() == 0:
                item = QListWidgetItem(f"{AUTO} (no entry)")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                stack.addItem(item)
            if slot == self.slot and self.candidate is not None and self.candidate < stack.count():
                stack.setCurrentRow(self.candidate)
            rows_height = sum(stack.sizeHintForRow(index) for index in range(stack.count()))
            stack.setFixedHeight(rows_height + 2 * stack.frameWidth() + Space.XS)
            stack.blockSignals(False)
            problems = self.editor.validation.at("slots", str(slot)) + self.editor.validation.at("controls", str(slot))
            set_role(self.card_frames[slot - 1], bool(problems), "problem")
            self.card_frames[slot - 1].setToolTip("\n".join(str(problem) for problem in problems))

    @staticmethod
    def _row_widget(candidate: Row, shown: bool) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(Space.S, Space.XS, Space.S, Space.XS)
        layout.setSpacing(Space.S)
        marker = label("▶" if shown else "")
        marker.setFixedWidth(14)
        marker.setToolTip("What the device shows" if shown else "")
        layout.addWidget(marker)
        layout.addWidget(label(candidate.show))
        for part in candidate.chips:
            layout.addWidget(chip(part))
        if candidate.options:
            layout.addWidget(label(", ".join(candidate.options), "hint"))
        layout.addStretch()
        return widget

    def _show_inspector(self) -> None:
        stack = rows(self.document.values, self.slot)
        if self.candidate is not None and self.candidate >= len(stack):
            self.candidate = len(stack) - 1 if stack else None
        controls = controls_text(self.document.values, self.slot)
        set_text(self.controls, "Controls: " + "; ".join(controls) if controls else "No controls of its own.")
        for widget in (self.show_box, self.when_edit, self.channel):
            widget.parentWidget().setVisible(self.candidate is not None)  # pyright: ignore[reportOptionalMemberAccess]
        self.channel.setVisible(self.candidate is not None)
        for option_row in self.place_rows:
            option_row.deleteLater()
        self.place_rows = []
        if self.candidate is None:
            set_text(self.title, f"Slot {self.slot}")
            self.channel_button.hide()
            self.show_problems(self.editor.validation)
            return
        candidate = stack[self.candidate]
        set_text(self.title, f"Slot {self.slot} · candidate {self.candidate + 1}")
        self.show_box.blockSignals(True)
        self.show_box.clear()
        self.show_box.addItems(choices(self.document.values))
        self.show_box.setCurrentText(candidate.show)
        self.show_box.blockSignals(False)
        self.when_edit.setText(candidate.when)
        channel = self.document.get(("channel", candidate.show))
        self.channel_button.setVisible(isinstance(channel, dict))
        if isinstance(channel, dict):
            kind = CHANNEL_TYPES.get(str(channel.get("type")))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            elsewhere = [use for use in uses(self.document.values, candidate.show) if use != f"slot {self.slot}"]
            set_text(
                self.channel,
                f"Channel {candidate.show} ({kind.title if kind else '?'}). "
                + (f"Also used in: {', '.join(elsewhere)}." if elsewhere else "Used nowhere else."),
            )
            strip = kind.strip if kind else None
        else:
            set_text(self.channel, "Nothing: the strip is dark." if candidate.show == EMPTY else "")
            strip = "auto" if candidate.show == AUTO else "voip" if candidate.show != EMPTY else None
        if strip is not None:
            allowed = place_options(candidate.show)
            for option in strip_options(strip):
                if option.name in allowed:
                    # at a place every option is optional: the channel has its own
                    self._place_row(dataclasses.replace(option, required=False))
        self.show_problems(self.editor.validation)

    def _place_row(self, option: Option) -> None:
        name = option.name
        slot, index = self.slot, self.candidate
        assert index is not None

        def put(value: Any) -> None:
            stack = rows(self.document.values, slot)
            candidate = stack[index]
            options = {key: each for key, each in candidate.options.items() if key != name}
            if value is not None:
                options[name] = value
            stack[index] = Row(candidate.show, candidate.when, options)
            self._put(slot, stack)

        option_row = OptionRow(option, lambda: rows(self.document.values, slot)[index].options.get(name), put)
        option_row.edited.connect(lambda: self.editor.edited(Change(Scope.VALUE, ("slots", str(slot), index, name))))
        self.place_rows.append(option_row)
        self.place.addWidget(option_row)

    def show_problems(self, validation: Validation) -> None:
        if self.candidate is None:
            self._show_rest([str(problem) for problem in validation.at("slots", str(self.slot))])
            return
        here = validation.at("slots", str(self.slot), self.candidate)
        names = {option_row.option.name for option_row in self.place_rows}
        self._show_rest([problem.message for problem in here if problem.path[3:4] not in [(name,) for name in names]])
        for option_row in self.place_rows:
            option_row.show_problems(validation.at("slots", str(self.slot), self.candidate, option_row.option.name))

    def show_live(self, snapshot: Snapshot | None) -> None:
        """The states in the bar, and ▶ on the candidates the device shows, when they changed."""
        slots = snapshot.slots if snapshot is not None else None
        live = (
            (
                *((state.name, state.value, state.override) for state in slots.states),
                slots.mode_pick,
                *(view.candidate for view in slots.slots),
            )
            if slots is not None
            else None
        )
        if live == self.shown_live:
            return
        self.shown_live = live
        picked = slots.mode_pick if slots is not None else None
        for name, state_button in self.state_buttons.items():
            state = live_state(snapshot, name)
            dot = "" if state is None else "● " if state.value else "○ "
            override = "" if state is None or state.override == "auto" else f" ({state.override})"
            if picked == name:
                override = " (picked)"
            state_button.setText(f"{dot}{self.document.get(('state', name, 'label')) or name}{override}")
            state_button.setToolTip(f"{name}: {state.source or 'off'}" if state is not None else name)
        self._show_cards()

    @staticmethod
    def _live_slots(snapshot: Snapshot | None) -> dict[int, SlotView]:
        if snapshot is None or snapshot.slots is None:
            return {}
        return {view.slot: view for view in snapshot.slots.slots}

    # -- picking --------------------------------------------------------------------------------------------------

    def select_slot(self, slot: int) -> None:
        """A strip of the drawing was clicked: its card, with the candidate the device shows."""
        view = self._live_slots(self.snapshot()).get(slot)
        count = len(rows(self.document.values, slot))
        self.slot = slot
        self.candidate = view.candidate if view is not None and view.candidate is not None else 0 if count else None
        self._show_cards()
        self._show_inspector()
        stack = self.lists[slot - 1]
        stack.setFocus()
        self.card_scroll.ensureWidgetVisible(self.card_frames[slot - 1])

    def _picked(self, slot: int, index: int) -> None:
        if index < 0:
            return
        for other, stack in enumerate(self.lists, start=1):
            if other != slot:
                stack.blockSignals(True)
                stack.clearSelection()
                stack.setCurrentRow(-1)
                stack.blockSignals(False)
        self.slot, self.candidate = slot, index
        self._show_inspector()

    def _candidate_row(self) -> Row:
        assert self.candidate is not None
        return rows(self.document.values, self.slot)[self.candidate]

    # -- editing --------------------------------------------------------------------------------------------------

    def _put(self, slot: int, stack: list[Row]) -> None:
        value = stack_value(stack)
        if value is None:
            self.document.unset(("slots", str(slot)))
        else:
            self.document.set(("slots", str(slot)), value)

    def _write(self, slot: int, stack: list[Row], candidate: int | None) -> None:
        self._put(slot, stack)
        self.slot, self.candidate = slot, candidate
        self.editor.edited(Change(Scope.SLOTS, ("slots", str(slot))))

    def add(self, slot: int) -> None:
        """A new candidate at the end of the stack: `auto` (Ctrl+Up moves it up)."""
        stack = rows(self.document.values, slot)
        stack.append(Row(AUTO))
        self._write(slot, stack, len(stack) - 1)

    def remove(self, slot: int) -> None:
        """Removes the candidate picked in the slot (the last one when none is)."""
        stack = rows(self.document.values, slot)
        if not stack:
            return
        index = self.candidate if slot == self.slot and self.candidate is not None else len(stack) - 1
        del stack[index]
        self._write(slot, stack, min(index, len(stack) - 1) if stack else None)

    def reorder(self, slot: int, order: list[int], current: int) -> None:
        stack = rows(self.document.values, slot)
        self._write(slot, [stack[index] for index in order], current)

    def _edit_show(self) -> None:
        candidate = self._candidate_row()
        show = self.show_box.currentText().strip()
        if show and show != candidate.show:
            self._replace(Row(show, candidate.when, candidate.options))

    def _edit_when(self) -> None:
        candidate = self._candidate_row()
        when = self.when_edit.text().strip()
        if when != candidate.when:
            self._replace(Row(candidate.show, when, candidate.options))

    def _replace(self, candidate: Row) -> None:
        assert self.candidate is not None
        stack = rows(self.document.values, self.slot)
        # options that the new place does not take go
        allowed = place_options(candidate.show)
        stack[self.candidate] = Row(
            candidate.show, candidate.when, {key: value for key, value in candidate.options.items() if key in allowed}
        )
        self._write(self.slot, stack, self.candidate)

    def override(self, name: str, value: str) -> None:
        """Asks the daemon to override a state, or to pick a mode (`auto`: the rules decide again)."""
        if self.document.get(("state", name, "mode")):
            self.request(SetMode(name if value == "on" else "auto"))
        else:
            self.request(SetOverride(name, value))
