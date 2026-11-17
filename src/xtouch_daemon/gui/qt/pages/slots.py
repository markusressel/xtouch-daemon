"""
The slots under the drawing of the device: a bar of the states (live, with their overrides), a card per slot with its
stack (the candidates in order, their conditions as chips, a green dot on the one the device shows), and an inspector
for the candidate picked: what it shows, when, the options of its place, its channel and where else that is used, and
the controls of the slot.
"""

import dataclasses
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDropEvent, QKeyEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.channels import CHANNEL_TYPES, uses
from xtouch_daemon.gui.domain.schema import Option, strip_options
from xtouch_daemon.gui.domain.simulate import Inputs, WhatIf, presence_text, simulated
from xtouch_daemon.gui.domain.slot_stacks import (
    ALWAYS,
    EMPTY,
    Row,
    choices,
    controls_text,
    place_options,
    rows,
    stack_value,
    targets,
)
from xtouch_daemon.gui.domain.slots_document import Validation
from xtouch_daemon.gui.domain.states import OVERRIDES, ordered
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import ElidedLabel, entity_label, flat_button, help_label, label
from xtouch_daemon.gui.qt.fields.condition import ConditionEdit
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.pages.base import Audio, Page, Sideways, Stack, button, card, row, scrolled, set_text
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space
from xtouch_daemon.gui.qt.window.splitter import PaneSplitter
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import Request, SetMode, SetOverride, SlotsState, SlotView, Snapshot
from xtouch_daemon.slots.model import AUTO, DEFAULT
from xtouch_daemon.slots.outcomes import Outcome, outcomes
from xtouch_daemon.slots.why import why_channel, why_slot

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
        # picked on a tint: the chips of its row keep their colors
        set_role(self, "stack")

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
    """A part of a condition, a chip of a state; `always` is no condition, so it is a hint."""
    return label(text, "hint") if text == ALWAYS else entity_label(text, Entity.STATE, chip=True)


SHOWS_HELP = "What the slot shows while this candidate wins: a channel, a pool such as `auto`, or `-` for a dark strip."
"""The help under Shows (see Writing help in `AGENTS.md`)."""
WHEN_HELP = (
    "The slot shows this candidate while the condition holds and no candidate above it does. Empty means always. "
    "It takes states, modes, `present`, `and`, `or`, `not` and parentheses, e.g. `call and not gaming`."
)
"""The help under When."""


def _value(value: Any) -> str:
    """A value of an option as in the file, without quotes: `white`, `true`, `[a, b]`."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"  # pyright: ignore[reportUnknownVariableType]
    return str(value)


def _clear(bar: QHBoxLayout) -> None:
    """Removes the widgets of a bar (it has nothing else)."""
    while (item := bar.takeAt(0)) is not None:
        widget = item.widget()
        assert widget is not None
        # off the screen at once: deleted later, it would stay where it was until then
        widget.hide()
        widget.deleteLater()


class SlotsPanel(Page):
    simulated = pyqtSignal(arguments=[])
    """Simulate started, changed or ended: the drawing shows the simulation (`simulation`) or the device again."""

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
        self.what_if: WhatIf | None = None
        """What Simulate shows, None while the cards show what the daemon tells."""
        self.simulation: SlotsState | None = None
        """The slots of `what_if`."""
        self.layout_.setContentsMargins(0, Space.S, 0, 0)
        end = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        end.activated.connect(lambda: self.simulate(None))
        top = QHBoxLayout()
        bars = QHBoxLayout()
        self.state_bar = QHBoxLayout()
        self.state_bar.setSpacing(Space.S)
        self.state_bar_row = row(self.state_bar)
        bars.addWidget(self.state_bar_row)
        self.what_if_bar = QHBoxLayout()
        self.what_if_bar.setSpacing(Space.S)
        self.what_if_row = row(self.what_if_bar)
        self.what_if_row.hide()
        bars.addWidget(self.what_if_row)
        bars.addStretch()
        top.addWidget(Sideways(row(bars)), 1)
        self.simulate_button = button("flask-outline", "Simulate")
        set_role(self.simulate_button, "segment", "variant")
        self.simulate_button.setCheckable(True)
        self.simulate_button.setToolTip(
            "What the slots would show in other modes and states; nothing is sent (Esc ends it)"
        )
        self.simulate_button.clicked.connect(lambda checked: self.simulate(WhatIf() if checked else None))
        top.addWidget(self.simulate_button)
        self.grid_button = button("table", "Grid")
        set_role(self.grid_button, "segment", "variant")
        self.grid_button.setCheckable(True)
        self.grid_button.setToolTip(
            "Every combination that shows something else: a row simulates it, a cell picks its slot"
        )
        self.grid_button.clicked.connect(self.show_grid)
        top.addWidget(self.grid_button)
        self.layout_.addWidget(row(top))
        self.state_buttons: dict[str, QToolButton] = {}
        cards = QWidget()
        self.cards = QVBoxLayout(cards)
        self.cards.setSpacing(Space.S)
        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.card_scroll.setWidget(cards)
        self.grid = QTableWidget()
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.cellClicked.connect(self._grid_cell)
        horizontal = self.grid.horizontalHeader()
        assert horizontal is not None
        horizontal.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        vertical = self.grid.verticalHeader()
        assert vertical is not None
        vertical.sectionClicked.connect(self._grid_row)
        self.outcomes: list[Outcome] = []
        self.middle = QStackedWidget()
        self.middle.addWidget(self.card_scroll)
        self.middle.addWidget(self.grid)
        self.lists: list[StackList] = []
        self.card_frames: list[QFrame] = []
        self.card_contents: list[tuple[list[Row], int | None] | None] = [None] * protocol.STRIPS
        """What each card shows: its candidates and the one the device shows."""
        for slot in range(1, protocol.STRIPS + 1):
            self._card(slot)
        self.cards.addStretch()
        self.inspector, inspector = card()
        self.title = label("", "section")
        inspector.addWidget(self.title)
        self.why = label("", "hint", wrap=True)
        """Why the slot shows what it shows (`xtouch-daemon why <slot>`), while the daemon tells it."""
        inspector.addWidget(self.why)
        what = QHBoxLayout()
        what.addWidget(label("Shows"))
        self.show_box = QComboBox()
        self.show_box.setEditable(True)
        self.show_box.setToolTip("A channel, a pool (`auto`) or `-` for nothing")
        self.show_box.activated.connect(lambda _: self._edit_show())
        self.show_box.lineEdit().editingFinished.connect(self._edit_show)  # pyright: ignore[reportOptionalMemberAccess]
        what.addWidget(self.show_box, 1)
        inspector.addWidget(row(what))
        self.show_help = help_label(SHOWS_HELP, "help", docs.guide_link("slots"))
        inspector.addWidget(self.show_help)
        when = QHBoxLayout()
        when.addWidget(label("When"))
        self.when_edit = ConditionEdit()
        self.when_edit.setPlaceholderText("always")
        self.when_edit.editingFinished.connect(self._edit_when)
        when.addWidget(self.when_edit, 1)
        inspector.addWidget(row(when))
        self.when_help = help_label(WHEN_HELP, "help", docs.guide_link("conditions"))
        inspector.addWidget(self.when_help)
        inspector.addWidget(self.problem)
        self.place = Stack()
        inspector.addWidget(self.place)
        self.place_forms: dict[tuple[str, frozenset[str]], tuple[QWidget, list[OptionRow]]] = {}
        """The forms of the options of a place, by strip type and the options it takes: built once, then reused."""
        self.place_rows: list[OptionRow] = []
        """The rows of the form shown."""
        self.channel = label("", "hint", wrap=True)
        inspector.addWidget(self.channel)
        self.channel_button = button("pencil-outline", "Edit the channel")
        self.channel_button.clicked.connect(lambda: self.show_channel(self._candidate_row().show))
        inspector.addWidget(self.channel_button)
        self.controls = label("", "hint", wrap=True)
        inspector.addWidget(self.controls)
        inspector.addStretch()
        self.inspector_scroll = scrolled(self.inspector)
        self.splitter = PaneSplitter("slots", self.middle, self.inspector_scroll)
        self.layout_.addWidget(self.splitter, 1)
        self._show()

    def _card(self, slot: int) -> None:
        frame, layout = card()
        layout.setContentsMargins(Space.M, Space.S, Space.M, Space.S)
        layout.setSpacing(Space.XS)
        header = QHBoxLayout()
        header.addWidget(entity_label(f"Slot {slot}", Entity.SLOT))
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
        config = self.editor.validation.config
        for toggle in (self.simulate_button, self.grid_button):
            toggle.setEnabled(config is not None)
            toggle.setToolTip(toggle.toolTip() if config is not None else "Only for a file without problems")
        if self.what_if is not None:
            self.simulate(self.what_if if config is not None else None)
        if self.grid_button.isChecked():
            self.show_grid(config is not None)
        self._show_state_bar()
        self._show_cards()
        self._show_inspector()

    def _show_state_bar(self) -> None:
        _clear(self.state_bar)
        self.state_buttons = {}
        for name in ordered(self.document.get(("state",), {})):
            state_button = QToolButton()
            set_role(state_button, Entity.STATE.value, "entity")
            # the label until the daemon tells the state (see `show_live`)
            state_button.setText(str(self.document.get(("state", name, "label")) or name))
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
        self.shown_live = None
        self.show_live(self.snapshot())

    def _show_cards(self) -> None:
        live = self._views()
        for slot, stack in enumerate(self.lists, start=1):
            stack.blockSignals(True)
            view = live.get(slot)
            candidates = rows(self.document.values, slot)
            shown_candidate = view.candidate if view is not None else None
            if self.card_contents[slot - 1] != (candidates, shown_candidate):
                # built again only when a candidate or the dot changed: every build lays out the card again
                self.card_contents[slot - 1] = (candidates, shown_candidate)
                self._fill_card(stack, candidates, shown_candidate)
            if slot == self.slot and self.candidate is not None and self.candidate < stack.count():
                stack.setCurrentRow(self.candidate)
            elif slot != self.slot:
                stack.setCurrentRow(-1)
            stack.blockSignals(False)
            problems = self.editor.validation.at("slots", str(slot)) + self.editor.validation.at("controls", str(slot))
            set_role(self.card_frames[slot - 1], bool(problems), "problem")
            self.card_frames[slot - 1].setToolTip("\n".join(str(problem) for problem in problems))

    def _fill_card(self, stack: StackList, candidates: list[Row], shown: int | None) -> None:
        stack.clear()
        for index, candidate in enumerate(candidates):
            item = QListWidgetItem()
            item.setData(_INDEX, index)
            stack.addItem(item)
            stack.setItemWidget(item, self._row_widget(candidate, shown == index, index, len(candidates)))
            item.setSizeHint(stack.itemWidget(item).sizeHint())  # pyright: ignore[reportOptionalMemberAccess]
        if stack.count() == 0:
            item = QListWidgetItem(f"{AUTO} (no entry)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            stack.addItem(item)
        rows_height = sum(stack.sizeHintForRow(index) for index in range(stack.count()))
        stack.setFixedHeight(rows_height + 2 * stack.frameWidth() + Space.XS)

    @staticmethod
    def _row_widget(candidate: Row, shown: bool, index: int, count: int) -> QWidget:
        """
        A candidate as a rule, read from the top like if, else if, else: `when gaming → auto`, then
        `otherwise → browser` for the last one without a condition. States and what it shows are chips in their colors
        (see `Entity`).
        """
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(Space.S, Space.XS, Space.S, Space.XS)
        layout.setSpacing(Space.S)
        # a lit LED, not ▶: an arrow in front of a row reads as "opens"
        marker = label("●" if shown else "", "live")
        marker.setFixedWidth(14)
        marker.setToolTip("The device shows this one now" if shown else "")
        layout.addWidget(marker)
        if candidate.chips == (ALWAYS,):
            word = "otherwise" if index == count - 1 and count > 1 else ALWAYS
            layout.addWidget(label(word, "hint"))
        else:
            layout.addWidget(label("when", "hint"))
            for part in candidate.chips:
                layout.addWidget(chip(part))
        layout.addWidget(label("→", "hint"))
        layout.addWidget(
            label(candidate.show, "hint")
            if candidate.show == EMPTY
            else entity_label(candidate.show, Entity.CHANNEL, True)
        )
        if candidate.options:
            options = ElidedLabel(", ".join(f"{name} = {_value(value)}" for name, value in candidate.options.items()))
            set_role(options, "hint")
            options.own_tip = True
            options.setToolTip("Options of the strip in this slot only: " + options.text())
            layout.addWidget(options, 1)
        else:
            layout.addStretch()
        return widget

    def _show_inspector(self) -> None:
        stack = rows(self.document.values, self.slot)
        if self.candidate is not None and self.candidate >= len(stack):
            self.candidate = len(stack) - 1 if stack else None
        self._show_why()
        controls = controls_text(self.document.values, self.slot)
        set_text(self.controls, "Controls: " + "; ".join(controls) if controls else "No controls of its own.")
        for widget in (self.show_box, self.when_edit, self.channel):
            widget.parentWidget().setVisible(self.candidate is not None)  # pyright: ignore[reportOptionalMemberAccess]
        for widget in (self.channel, self.show_help, self.when_help):
            widget.setVisible(self.candidate is not None)
        self.place.setVisible(False)
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
        self.when_edit.set_names([*self.document.values.get("state", {}), DEFAULT], targets(self.document.values))
        self.when_edit.setText(candidate.when)
        channel = self.document.get(("channel", candidate.show))
        self.channel_button.setVisible(isinstance(channel, dict))
        if isinstance(channel, dict):
            kind = CHANNEL_TYPES.get(str(channel.get("type")))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            elsewhere = [use for use in uses(self.document.values, candidate.show) if use != f"slot {self.slot}"]
            set_text(
                self.channel,
                f"Channel {candidate.show} ({kind.title if kind else '?'}). "
                + (f"Also used in: {', '.join(elsewhere)}." if elsewhere else "Used nowhere else.")
                + self._channel_why(candidate.show),
            )
            strip = kind.strip if kind else None
        else:
            set_text(self.channel, "Nothing: the strip is dark." if candidate.show == EMPTY else "")
            strip = "auto" if candidate.show == AUTO else "voip" if candidate.show != EMPTY else None
        if strip is not None:
            form, self.place_rows = self._place_form(strip, place_options(candidate.show))
            self.place.show_part(form)
            self.place.setVisible(True)
            self._load_rows(self.place_rows)
        self.show_problems(self.editor.validation)

    def _channel_why(self, name: str) -> str:
        slots = self.shown_slots()
        if slots is None:
            return ""
        return f"\n{'What if' if self.simulation else 'Now'}: {why_channel(slots, name)}"

    def _show_why(self) -> None:
        live = self.shown_slots()
        self.why.setVisible(live is not None)
        if live is not None:
            set_text(self.why, why_slot(live, self.slot))

    def _place_form(self, strip: str, allowed: frozenset[str]) -> tuple[QWidget, list[OptionRow]]:
        """The form of the options of a place of `strip`, for the candidate picked."""
        key = (strip, allowed)
        if key not in self.place_forms:
            form = QWidget()
            layout = QVBoxLayout(form)
            layout.setContentsMargins(0, 0, 0, 0)
            # at a place every option is optional: the channel has its own
            option_rows = [
                self._place_row(dataclasses.replace(option, required=False))
                for option in strip_options(strip)
                if option.name in allowed
            ]
            for option_row in option_rows:
                layout.addWidget(option_row)
            self.place_forms[key] = form, option_rows
        return self.place_forms[key]

    def _place_row(self, option: Option) -> OptionRow:
        """A row for an option of the place of the candidate picked, whichever it is when it is shown or edited."""
        name = option.name

        def get() -> Any:
            assert self.candidate is not None
            return rows(self.document.values, self.slot)[self.candidate].options.get(name)

        def put(value: Any) -> None:
            assert self.candidate is not None
            stack = rows(self.document.values, self.slot)
            candidate = stack[self.candidate]
            options = {key: each for key, each in candidate.options.items() if key != name}
            if value is not None:
                options[name] = value
            stack[self.candidate] = Row(candidate.show, candidate.when, options)
            self._put(self.slot, stack)

        option_row = OptionRow(option, get, put)

        def edited() -> None:
            assert self.candidate is not None
            self.editor.edited(Change(Scope.VALUE, ("slots", str(self.slot), self.candidate, name)))

        option_row.edited.connect(edited)
        return option_row

    def show_problems(self, validation: Validation) -> None:
        if self.candidate is None:
            self._show_rest([str(problem) for problem in validation.at("slots", str(self.slot))])
            return
        here = validation.at("slots", str(self.slot), self.candidate)
        names = {option_row.option.name for option_row in self.place_rows}
        self._show_rest([problem.message for problem in here if problem.path[3:4] not in [(name,) for name in names]])
        for option_row in self.place_rows:
            option_row.show_problems(validation.at("slots", str(self.slot), self.candidate, option_row.option.name))

    def shown_slots(self, snapshot: Snapshot | None = None) -> SlotsState | None:
        """What the cards show: the simulation, else what the daemon tells."""
        if self.simulation is not None:
            return self.simulation
        snapshot = snapshot if snapshot is not None else self.snapshot()
        return snapshot.slots if snapshot is not None else None

    def show_live(self, snapshot: Snapshot | None) -> None:
        """The states in the bar, and the dot on the candidates the device shows (or would), when they changed."""
        slots = self.shown_slots(snapshot)
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
        states = {state.name: state for state in slots.states} if slots is not None else {}
        for name, state_button in self.state_buttons.items():
            state = states.get(name)
            dot = "" if state is None else "● " if state.value else "○ "
            override = "" if state is None or state.override == "auto" else f" ({state.override})"
            if picked == name:
                override = " (picked)"
            state_button.setText(f"{dot}{self.document.get(('state', name, 'label')) or name}{override}")
            state_button.setToolTip(f"{name}: {state.source or 'off'}" if state is not None else name)
        self._show_cards()
        self._show_why()

    def _views(self) -> dict[int, SlotView]:
        slots = self.shown_slots()
        return {view.slot: view for view in slots.slots} if slots is not None else {}

    # -- simulate and the grid ---------------------------------------------------------------------------------------

    def simulate(self, what_if: WhatIf | None) -> None:
        """Shows what the slots would show in `what_if`; None goes back to what the daemon tells."""
        config = self.editor.validation.config
        self.what_if = what_if
        self.simulation = simulated(config.slots, what_if) if what_if is not None and config is not None else None
        self.simulate_button.setChecked(self.simulation is not None)
        self.state_bar_row.setVisible(self.simulation is None)
        self.what_if_row.setVisible(self.simulation is not None)
        if config is not None and what_if is not None:
            self._show_what_if_bar(Inputs.of(config.slots), what_if)
        self.shown_live = None
        self.show_live(self.snapshot())
        self.simulated.emit()

    def _show_what_if_bar(self, inputs: Inputs, what_if: WhatIf) -> None:
        _clear(self.what_if_bar)
        self.what_if_bar.addWidget(label("What if", "hint"))
        mode = QComboBox()
        mode.addItems(inputs.modes)
        mode.setCurrentText(what_if.mode)
        mode.setToolTip("The mode")
        mode.currentTextChanged.connect(lambda name: self.simulate(dataclasses.replace(what_if, mode=name)))
        self.what_if_bar.addWidget(mode)
        for name, flip, checked in (
            *((name, False, name in what_if.on) for name in inputs.states),
            *((name, True, name in what_if.flipped) for name in inputs.presence),
        ):
            toggle = QPushButton(presence_text(name) if flip else name)
            set_role(toggle, "segment", "variant")
            toggle.setCheckable(True)
            toggle.setChecked(checked)
            toggle.clicked.connect(lambda _=False, name=name, flip=flip: self.simulate(what_if.toggled(name, flip)))
            self.what_if_bar.addWidget(toggle)

    def show_grid(self, shown: bool) -> None:
        """The grid of distinct outcomes in place of the cards (or the cards again)."""
        config = self.editor.validation.config
        self.grid_button.setChecked(shown)
        self.middle.setCurrentWidget(self.grid if shown else self.card_scroll)
        if not shown or config is None:
            return
        self.outcomes = outcomes(config.slots.scene)
        self.grid.clear()
        self.grid.setRowCount(len(self.outcomes))
        self.grid.setColumnCount(protocol.STRIPS)
        self.grid.setHorizontalHeaderLabels([str(slot) for slot in range(1, protocol.STRIPS + 1)])
        self.grid.setVerticalHeaderLabels([outcome.label for outcome in self.outcomes])
        for index, outcome in enumerate(self.outcomes):
            for column, shows in enumerate(outcome.slots):
                self.grid.setItem(index, column, QTableWidgetItem(shows))

    def _grid_row(self, index: int) -> None:
        self.simulate(WhatIf.of(self.outcomes[index]))

    def _grid_cell(self, index: int, column: int) -> None:
        """Simulates the row and picks the card of the slot."""
        self._grid_row(index)
        self.show_grid(False)
        self.select_slot(column + 1)

    # -- picking --------------------------------------------------------------------------------------------------

    def select_slot(self, slot: int) -> None:
        """A strip of the drawing was clicked: its card, with the candidate the device shows."""
        view = self._views().get(slot)
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
