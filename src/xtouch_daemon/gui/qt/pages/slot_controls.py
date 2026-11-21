"""
The controls of a slot on the page Slots (`[controls].<n>`): its entries, each with its `when`, the parts it claims
(the same fields as on the page Channels: a binding for the fader, the encoder, the meter, the color and the line of
the LCD, the press and the LED of Select, Rec and Solo) and its `id`. Only the parts an entry sets show; "Add a part"
adds one. Edits go through the editor like the others: a step to undo, then the file.
"""

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.schema import Kind, Option, controls_options
from xtouch_daemon.gui.domain.slot_controls import (
    PART_TITLES,
    START,
    Entry,
    controls_value,
    custom_channels,
    entries,
    entry_path,
    entry_problems,
    entry_text,
    listed,
    missing,
    modes_and_states,
    moved,
    parts,
    uses_home_assistant,
)
from xtouch_daemon.gui.domain.slot_stacks import targets
from xtouch_daemon.gui.domain.slots_document import OptionPath, Validation
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import flat_button, help_label, help_text, label, set_help
from xtouch_daemon.gui.qt.fields.choice import Choice
from xtouch_daemon.gui.qt.fields.condition import ConditionEdit
from xtouch_daemon.gui.qt.fields.option_row import OptionRow, add_rows, align_titles
from xtouch_daemon.gui.qt.pages.base import row, set_text
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.slots.model import DEFAULT

OPTIONS: dict[str, Option] = {option.name: option for option in controls_options()}
"""The options of an entry of `[controls]`, by name: its parts, `when` and `id`."""
WHEN_HELP = (
    "The entry acts while this condition of states and modes holds. Empty means always. Of several entries, the "
    "first whose condition holds acts."
)
"""The help under When of an entry."""
PRESS_UNSET = "As on what the slot shows"
"""The placeholder of a press an entry leaves unset: a press goes to what the slot shows."""


def section_help(slot: int) -> str:
    """The help under the title of the controls."""
    return (
        f"Parts of slot {slot} that act the same whatever the slot shows. While its `when` holds, an entry overrides "
        "what the slot shows."
    )


def empty_help(slot: int) -> str:
    """What the controls say while the slot has none."""
    return f"`[controls]` claims no part of slot {slot}. Add a part, e.g. a meter that always shows the CPU load."


class EntryBox(QFrame):
    """One entry of the controls of a slot: its header, When, the parts it sets, Id, and "Add a part"."""

    def __init__(self, controls: SlotControls, index: int, entry: Entry, count: int):
        super().__init__()
        self.controls = controls
        self.index = index
        set_role(self, "popover_row")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Space.M, Space.S, Space.S, Space.S)
        layout.setSpacing(Space.XS)
        header = QHBoxLayout()
        header.setSpacing(Space.XS)
        self.title = label("", "group")
        header.addWidget(self.title)
        header.addStretch()
        self.up = flat_button("arrow-up", "Move the entry up: it acts before the ones below")
        self.up.clicked.connect(lambda: controls.move_entry(index, -1))
        self.up.setVisible(count > 1)
        self.up.setEnabled(index > 0)
        header.addWidget(self.up)
        self.down = flat_button("arrow-down", "Move the entry down")
        self.down.clicked.connect(lambda: controls.move_entry(index, 1))
        self.down.setVisible(count > 1)
        self.down.setEnabled(index < count - 1)
        header.addWidget(self.down)
        self.remove = flat_button("delete-outline", "Remove the entry")
        self.remove.clicked.connect(lambda: controls.remove_entry(index))
        header.addWidget(self.remove)
        layout.addWidget(row(header))
        when = QHBoxLayout()
        when.setSpacing(Space.S)
        when_title = label("When")
        when.addWidget(when_title)
        self.when = ConditionEdit(present=False)
        self.when.setPlaceholderText("always")
        values = controls.document_values()
        self.when.set_names([*values.get("state", {}), DEFAULT], targets(values))
        self.when.setText(str(entry.get("when") or ""))
        self.when.editingFinished.connect(self._edit_when)
        when.addWidget(self.when, 1)
        layout.addWidget(row(when))
        when_help = help_label(WHEN_HELP, "help", docs.guide_link("conditions"))
        layout.addWidget(when_help)
        self.when_error = label("", "error", wrap=True)
        self.when_error.hide()
        layout.addWidget(self.when_error)
        self.rows: dict[str, OptionRow] = {}
        """The rows of the parts it sets, and of `id`."""
        for name in parts(entry):
            self.rows[name] = self._row(OPTIONS[name])
        self.rows["id"] = self._row(OPTIONS["id"], placeholder=lambda: f"slot_{controls.slot}")
        add_rows(layout, list(self.rows.values()))
        # When in the column of the names of the parts
        width = align_titles(self.rows.values(), least=when_title.sizeHint().width())
        when_title.setFixedWidth(width)
        for under in (when_help, self.when_error):
            under.setContentsMargins(width + Space.S, 0, 0, 0)
        add = QHBoxLayout()
        self.add = Choice()
        self.add.setPlaceholderText("Add a part")
        self.add.setToolTip("Claims another part of the slot in this entry")
        self.add.activated.connect(self._add)
        add.addWidget(self.add)
        add.addStretch()
        layout.addWidget(row(add))
        self.error = label("", "error", wrap=True)
        self.error.hide()
        layout.addWidget(self.error)
        self.refresh()

    @property
    def path(self) -> OptionPath:
        return self.controls.entry_path(self.index)

    def entry(self) -> Entry:
        found = entries(self.controls.document_values(), self.controls.slot)
        return found[self.index] if self.index < len(found) else {}

    def _row(self, option: Option, placeholder: Callable[[], str] | None = None) -> OptionRow:
        name = option.name
        option_row = OptionRow(
            option,
            lambda: self.entry().get(name),
            lambda value: self.controls.put((*self.path, name), value),
            placeholder=placeholder,
            link=docs.guide_link("controls"),
        )
        # as the device names the part, e.g. "LCD line"
        option_row.title.setText(PART_TITLES.get(name, option.title))
        if option.kind == Kind.CLAIM:
            option_row.buttons.extra = lambda: modes_and_states(self.controls.document_values())
            option_row.buttons.inherited = lambda part: self._button_placeholder(name, part)
            option_row.load()
        elif option.kind == Kind.BINDING and option.channel:
            option_row.binding.channels = lambda: custom_channels(self.controls.document_values())
            option_row.load()
        option_row.reset.setToolTip("Remove the part: it goes back to what the slot shows" if name != "id" else "Unset")
        option_row.edited.connect(lambda: self._edited(name))
        return option_row

    def _button_placeholder(self, name: str, part: str) -> str:
        """What a press or an LED the entry leaves unset does: as the slot shows it, or what the press does."""
        value = self.entry().get(name)
        # a press: an action, `{ launch }` or `{ run }`, or the `press` of a table
        pressed = isinstance(value, str) or (isinstance(value, dict) and bool({"press", "launch", "run"} & set(value)))  # pyright: ignore[reportUnknownArgumentType]
        if part == "led" and pressed:
            return "What the press does"
        return PRESS_UNSET

    def _edited(self, name: str) -> None:
        if self.entry().get(name) is None:
            # a part went: its row goes too
            self.controls.edited(Change(Scope.SLOTS, ("controls", str(self.controls.slot))))
        else:
            self.refresh()
            self.controls.edited(Change(Scope.VALUE, (*self.path, name)))

    def _edit_when(self) -> None:
        when = self.when.text().strip()
        if when != (self.entry().get("when") or ""):
            self.controls.put((*self.path, "when"), when or None)
            self.controls.edited(Change(Scope.VALUE, (*self.path, "when")))

    def _add(self, _index: int) -> None:
        name = self.add.currentData()
        if isinstance(name, str):
            self.controls.add_part(self.index, name)

    def refresh(self) -> None:
        """What changes with an edit of a field: the title, Id (for Home Assistant), the parts still to add."""
        entry = self.entry()
        count = len(entries(self.controls.document_values(), self.controls.slot))
        set_text(self.title, (f"{self.index + 1}. " if count > 1 else "") + entry_text(entry))
        self.rows["id"].setVisible("id" in entry or uses_home_assistant(entry))
        self.add.blockSignals(True)
        self.add.clear()
        for name in missing(entry):
            self.add.addItem(PART_TITLES[name], name)
            self.add.setItemData(self.add.count() - 1, help_text(OPTIONS[name].help), Qt.ItemDataRole.ToolTipRole)
        self.add.setCurrentIndex(-1)
        self.add.blockSignals(False)
        self.add.parentWidget().setVisible(self.add.count() > 0)  # pyright: ignore[reportOptionalMemberAccess]

    def show_problems(self, problems: list[Problem]) -> None:
        path = self.path
        for name, option_row in self.rows.items():
            option_row.show_problems(
                [problem for problem in problems if problem.path[: len(path) + 1] == (*path, name)]
            )
        when = [problem.message for problem in problems if problem.path[: len(path) + 1] == (*path, "when")]
        set_text(self.when_error, "\n".join(when))
        self.when_error.setVisible(bool(when))
        set_role(self.when, bool(when), "problem")
        rest = [problem.message for problem in entry_problems(problems, path)]
        set_text(self.error, "\n".join(rest))
        self.error.setVisible(bool(rest))
        set_role(self, bool(rest), "problem")


class SlotControls(QWidget):
    """The controls of the slot picked: a box per entry, and a way to add one."""

    def __init__(self, editor: Editor):
        super().__init__()
        self.editor = editor
        self.slot = 1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, Space.M, 0, 0)
        layout.setSpacing(Space.XS)
        self.title = label("", "section")
        layout.addWidget(self.title)
        self.help = help_label("", "help", docs.guide_link("controls"))
        layout.addWidget(self.help)
        self.boxes_layout = QVBoxLayout()
        self.boxes_layout.setSpacing(Space.S)
        layout.addWidget(row(self.boxes_layout))
        self.boxes: list[EntryBox] = []
        add = QHBoxLayout()
        self.add = Choice()
        self.add.setPlaceholderText("Add controls")
        self.add.setToolTip("A new entry that claims a part of the slot, e.g. for another `when`")
        for name, title in PART_TITLES.items():
            self.add.addItem(title, name)
            self.add.setItemData(self.add.count() - 1, help_text(OPTIONS[name].help), Qt.ItemDataRole.ToolTipRole)
        self.add.setCurrentIndex(-1)
        self.add.activated.connect(self._add_entry)
        add.addWidget(self.add)
        add.addStretch()
        layout.addWidget(row(add))
        self.error = label("", "error", wrap=True)
        self.error.hide()
        layout.addWidget(self.error)

    def document_values(self) -> dict[str, Any]:
        return self.editor.document.values

    def entry_path(self, index: int) -> OptionPath:
        return entry_path(self.slot, index, listed(self.document_values(), self.slot))

    def show_slot(self, slot: int) -> None:
        """Shows the controls of the slot, as the file has them now."""
        self.slot = slot
        set_text(self.title, f"Controls of slot {slot}")
        found = entries(self.document_values(), slot)
        set_help(self.help, section_help(slot) if found else empty_help(slot), docs.guide_link("controls"))
        for box in self.boxes:
            box.hide()
            box.deleteLater()
        self.boxes = [EntryBox(self, index, entry, len(found)) for index, entry in enumerate(found)]
        for box in self.boxes:
            self.boxes_layout.addWidget(box)
        self.add.setPlaceholderText("Add controls" if found else "Add a part")
        self.add.setToolTip(
            "A new entry that claims a part of the slot, e.g. for another `when`"
            if found
            else "Claims a part of the slot, whatever it shows"
        )
        self.add.setCurrentIndex(-1)

    def show_problems(self, validation: Validation) -> None:
        problems = validation.at("controls", str(self.slot))
        for box in self.boxes:
            box.show_problems(problems)
        # of the slot as a whole: a list that is no list of tables, ...
        rest = [
            problem.message
            for problem in problems
            if problem.path == ("controls", str(self.slot)) and listed(self.document_values(), self.slot)
        ]
        set_text(self.error, "\n".join(rest))
        self.error.setVisible(bool(rest))

    # -- editing --------------------------------------------------------------------------------------------------

    def put(self, path: OptionPath, value: Any) -> None:
        """Sets a value of an entry (None: removes it; an entry left empty goes too)."""
        if value is None:
            self.editor.document.unset(path)
            found = entries(self.document_values(), self.slot)
            if len(found) == 1 and listed(self.document_values(), self.slot):
                # the one entry left of a list: a table again, as "Remove the entry" leaves it
                self.editor.document.set(("controls", str(self.slot)), found[0])
        else:
            self.editor.document.set(path, value)

    def edited(self, change: Change) -> None:
        self.editor.edited(change)

    def _write(self, found: list[Entry]) -> None:
        value = controls_value(found)
        if value is None:
            self.editor.document.unset(("controls", str(self.slot)))
        else:
            self.editor.document.set(("controls", str(self.slot)), value)
        self.editor.edited(Change(Scope.SLOTS, ("controls", str(self.slot))))

    def _add_entry(self, _index: int) -> None:
        name = self.add.currentData()
        self.add.setCurrentIndex(-1)
        if isinstance(name, str):
            self._write([*entries(self.document_values(), self.slot), {name: START[name]}])

    def add_part(self, index: int, name: str) -> None:
        """Adds a part to an entry, as it starts (see `START`)."""
        found = entries(self.document_values(), self.slot)
        found[index][name] = START[name]
        self._write(found)

    def remove_entry(self, index: int) -> None:
        found = entries(self.document_values(), self.slot)
        del found[index]
        self._write(found)

    def move_entry(self, index: int, offset: int) -> None:
        self._write(moved(entries(self.document_values(), self.slot), index, offset))
