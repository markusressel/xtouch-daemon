"""
The field of a button (`select`, `rec`, `solo`, and `mute` of a `custom` channel): what a press does, what a hold does
and what its LED shows, each a list of its choices; unset, each shows what the strip type does by default. A program
is a table in the file and a text in the list: `launch: mumble`, `run: sysctrl display reset`, `watch: led-state
--follow`. So is a service of Home Assistant a press calls (`service: light.toggle`) and an entity an LED shows
(`entity: light.desk`): their options show below the list, the entity with suggestions. A button of `[controls]`
(`claim`) has a press and an LED only, and a text or a program alone is its press.
"""

import shlex
from collections.abc import Callable, Mapping
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QGridLayout, QWidget

from xtouch_daemon.config.bindings import ServiceAction
from xtouch_daemon.config.buttons import ButtonSetup, describe_action, table_of
from xtouch_daemon.gui.domain.places import HOME_ASSISTANT_KEYS, PROGRAM_KEYS, program_text
from xtouch_daemon.gui.domain.schema import Kind, Option
from xtouch_daemon.gui.qt.fields.basics import help_label, help_text, label, set_help
from xtouch_daemon.gui.qt.fields.choice import Choice
from xtouch_daemon.gui.qt.fields.entity_table import EntityTable
from xtouch_daemon.gui.qt.theme.tokens import Space

PART_TITLES = {"press": "Press", "hold": "Hold", "led": "LED"}
"""The names of the parts of a button, for people."""


def parts_of(name: str, value: object, claim: bool = False) -> dict[str, Any]:
    """
    The parts of a button in the file (see `table_of`): {} for a value that is no table. Of a button of `[controls]`
    (`claim`), an action alone (a text, `{ launch }`, `{ run }`) is the press.
    """
    if claim:
        if isinstance(value, str) or (isinstance(value, Mapping) and {"launch", "run", "service"} & set(value)):  # pyright: ignore[reportUnknownArgumentType]
            return {"press": value}
        return dict(value) if isinstance(value, Mapping) else {}  # pyright: ignore[reportUnknownArgumentType]
    table = table_of(name, value)
    return dict(table) if isinstance(table, Mapping) else {}


PROGRAM_MEANINGS = {
    "launch": "Starts the program.",
    "run": "Runs the program to its end. `{value}` is the value of the fader, else of the encoder.",
    "watch": "Lit while the program's newest line is `on`, `1`, `true` or `yes`; it flashes on `flash`.",
    "service": "Calls the service of Home Assistant, with the entity and the data below.",
    "entity": "Lit while the entity of Home Assistant is `on`, `open`, `playing` or `home`.",
}


def program_table(text: str) -> dict[str, Any] | None:
    """
    The table of a text typed as `run: prog arg` (or `launch:`, `watch:`), `service: light.toggle` or `entity:
    light.desk`; None for other text.
    """
    key, colon, rest = text.partition(":")
    if colon and key.strip() in HOME_ASSISTANT_KEYS:
        return {key.strip(): rest.strip()}
    if not colon or key.strip() not in PROGRAM_KEYS:
        return None
    try:
        command = shlex.split(rest)
    except ValueError:
        # an open quote: the program as it is, its problem says what is wrong
        command = rest.split()
    return {key.strip(): command}


class ButtonField(QWidget):
    """
    The press, the hold and the LED of a button, each a list (press and hold take typed actions too, e.g.
    `mode:gaming`). `changed` has the table (None: none of them is set). `defaults` tells what the strip type does
    without a table, `extra` the actions of the modes and states there are.
    """

    changed = pyqtSignal(object, arguments=["value"])

    def __init__(self, name: str, columns: tuple[Option, ...], claim: bool = False):
        super().__init__()
        self.name = name
        self.columns = columns
        self.claim = claim
        """A button of `[controls]`: its short form is the press alone, not the LED."""
        self.defaults: Callable[[], ButtonSetup] = ButtonSetup
        self.extra: Callable[[], list[str]] = list
        self.inherited: Callable[[str], str] | None = None
        """
        The placeholder of an unset part where it takes no default of the type, by part, e.g. "As on the channel:
        muted" at a place.
        """
        self._unknown: set[str] = set()
        """Parts whose value in the file is none of the list: they mean nothing (their problem says why)."""
        self._kept: dict[str, Any] = {}
        """Parts that are no text (a launch table): kept while their text in the list stays."""
        self._loading = False
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(Space.S)
        grid.setVerticalSpacing(Space.XS)
        self.combos: dict[str, QComboBox] = {}
        self.tables: dict[str, EntityTable] = {}
        """The options of a service a press or a hold calls, of an entity an LED shows: below the list, by part."""
        for index, column in enumerate(columns):
            row = 2 * index
            combo = Choice(self)
            combo.setMinimumWidth(180)
            combo.setToolTip(help_text(column.help))
            if column.kind in (Kind.ACTION, Kind.BINDING):
                # actions typed (`mode:gaming`), programs typed (`run: ...`, `watch: ...`)
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                combo.editTextChanged.connect(self._edited)
            else:
                combo.currentTextChanged.connect(self._edited)
            self.combos[column.name] = combo
            grid.addWidget(label(PART_TITLES.get(column.name, column.title)), row, 0)
            grid.addWidget(combo, row, 1)
            model = ServiceAction if column.kind == Kind.ACTION else column.entity
            if model is not None:
                table = EntityTable(model, "service" if model is ServiceAction else "entity", intro=False)
                table.changed.connect(lambda value, name=column.name: self._table_changed(name, value))
                table.hide()
                self.tables[column.name] = table
                grid.addWidget(table, row + 1, 1, 1, 2)
        grid.setColumnStretch(2, 1)
        # what the parts that are set (or their defaults) mean
        self.meaning = help_label("", "meaning")
        grid.addWidget(self.meaning, 2 * len(columns), 0, 1, 3)

    def _fill(self, combo: QComboBox, column: Option) -> None:
        combo.clear()
        choices = [*column.choices, *(name for name, _ in column.meanings if name not in column.choices)]
        if column.kind == Kind.ACTION:
            choices += [extra for extra in self.extra() if extra not in choices]
        if column.name in self.tables:
            # a service, an entity: picked, the rest of its options shows below
            choices.append("service:" if column.kind == Kind.ACTION else "entity:")
        for index, choice in enumerate(choices):
            combo.addItem(choice)
            meaning = column.meaning(choice) or PROGRAM_MEANINGS.get(choice.removesuffix(":"), "")
            combo.setItemData(index, help_text(meaning), Qt.ItemDataRole.ToolTipRole)

    def show_value(self, value: object) -> None:
        """Shows the table of the button in the file (or a shorthand of it), the defaults as placeholders."""
        parts = parts_of(self.name, value, self.claim)
        defaults = self.defaults()
        self._loading = True
        try:
            self._kept = {}
            self._unknown = set()
            for column in self.columns:
                combo = self.combos[column.name]
                self._fill(combo, column)
                part = parts.get(column.name)
                default = getattr(defaults, column.name)
                shown = describe_action(default) if column.kind == Kind.ACTION else default
                placeholder = self.inherited(column.name) if self.inherited is not None else f"default: {shown}"
                if isinstance(part, Mapping):
                    self._kept[column.name] = dict(part)
                    part = program_text(part)
                text = "" if part is None else str(part)
                if combo.isEditable():
                    combo.setCurrentIndex(-1)
                    combo.setEditText(text)
                    edit = combo.lineEdit()
                    if edit is not None:
                        edit.setPlaceholderText(placeholder)
                    combo.setPlaceholderText(placeholder)
                else:
                    combo.setCurrentIndex(combo.findText(text) if text else -1)
                    if text and combo.currentIndex() < 0:
                        self._unknown.add(column.name)
                    combo.setPlaceholderText(placeholder)
        finally:
            self._loading = False
        self._show_tables()
        self._show_meaning()

    def value(self) -> dict[str, Any] | str | bool | None:
        """The table of the button: the parts that are set (or its short form); None for none."""
        table: dict[str, Any] = {}
        for name, combo in self.combos.items():
            text = combo.currentText().strip() if combo.isEditable() or combo.currentIndex() >= 0 else ""
            kept = self._kept.get(name)
            if kept is not None and text == program_text(kept):
                table[name] = kept
            elif (program := program_table(text)) is not None:
                key = next(iter(program))
                # another service or entity typed: its other options stay
                table[name] = {**kept, **program} if kept is not None and key in kept else program
            elif text:
                table[name] = text
        if self.claim:
            # the short form of `[controls]`: the press alone, e.g. `rec = "toggle:call"`
            return table["press"] if set(table) == {"press"} else table or None
        # the shorthands where they say it all: `rec = "muted"`, `select = false`
        if self.name != "select" and set(table) == {"led"} and isinstance(table["led"], str):
            return table["led"]
        if self.name == "select" and table == {"press": "off"}:
            return False
        return table or None

    def _edited(self, _text: str) -> None:
        if self._loading:
            return
        self._unknown = {name for name in self._unknown if self.combos[name].currentIndex() < 0}
        value = self.value()
        # what is in the list now is what the parts are
        parts = parts_of(self.name, value, self.claim)
        self._kept = {name: dict(part) for name, part in parts.items() if isinstance(part, Mapping)}
        self._show_tables()
        self._show_meaning()
        self.changed.emit(value)

    def _show_tables(self) -> None:
        """The options of the service or the entity of a part below its list, while it is one."""
        for name, table in self.tables.items():
            kept = self._kept.get(name)
            shown = kept is not None and table.marker in kept
            if shown and kept is not None:
                table.show_table(kept)
            table.setVisible(shown)
            if shown:
                table.want()

    def _table_changed(self, name: str, value: dict[str, Any]) -> None:
        """An option of the service or the entity of a part changed: its text in the list, and the file."""
        self._kept[name] = value
        combo = self.combos[name]
        self._loading = True
        try:
            combo.setEditText(program_text(value))
        finally:
            self._loading = False
        self._show_meaning()
        self.changed.emit(self.value())

    def _show_meaning(self) -> None:
        defaults = self.defaults()
        lines: list[str] = []
        for column in self.columns:
            combo = self.combos[column.name]
            text = combo.currentText().strip() if combo.isEditable() or combo.currentIndex() >= 0 else ""
            if not text and (column.name in self._unknown or self.inherited is not None):
                continue
            shown = text or (describe_action(getattr(defaults, column.name)))
            program = program_table(shown)
            meaning = column.meaning(shown) or (
                PROGRAM_MEANINGS[next(iter(program))]
                if program is not None
                else "Picks the mode."
                if shown.startswith("mode:")
                else "Turns the state or mode on and back."
                if shown.startswith("toggle:")
                else ""
            )
            if meaning and shown != "off":
                lines.append(f"{PART_TITLES.get(column.name, column.title)} `{shown}`: {meaning}")
        set_help(self.meaning, " ".join(lines))
        self.meaning.setVisible(bool(lines))
