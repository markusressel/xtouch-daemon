"""
The field of a part of a strip that can be bound (`Kind.BINDING`, see docs/development/design/bindings.md): the field
of its words as without bindings (a list, a switch or colors), and a button that binds the part to Home Assistant, to
an entity of Home Assistant (`Option.entity`) or to a program of your own. Bound to a program or an entity, its
options show below the field (`set`, `watch`, `min`, ... or `entity`, `attribute`, ...), each a row of its own; the
entity and its attribute with suggestions of what Home Assistant has. A fader or an encoder of `[controls]` can set
the value of a `custom` channel too (`Option.channel`): a list of those channels.
"""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, cast

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QMenu, QToolButton, QVBoxLayout, QWidget

from xtouch_daemon.config.bindings import HOME_ASSISTANT
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.gui.domain.schema import Kind, Option, describe
from xtouch_daemon.gui.qt.fields.basics import help_label, help_text, label
from xtouch_daemon.gui.qt.fields.choice import Choice
from xtouch_daemon.gui.qt.fields.controls import ColorPicker, Switch
from xtouch_daemon.gui.qt.fields.entity_table import EntityTable
from xtouch_daemon.gui.qt.fields.menu import attach_menu
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space

if TYPE_CHECKING:
    from xtouch_daemon.gui.qt.fields.option_row import OptionRow

PROGRAM = "program"
"""The mode of a part bound to a program of your own (a table)."""
WORDS = "words"
"""The mode of a part that is not bound: its words, or its default."""
CHANNEL = "channel"
"""The mode of a fader or an encoder of `[controls]` that sets the value of a `custom` channel (`{ channel = ... }`)."""
ENTITY = "entity"
"""The mode of a part bound to an entity of Home Assistant (`{ entity = ... }`)."""

MODE_TITLES = {
    HOME_ASSISTANT: "Home Assistant",
    ENTITY: "An entity",
    PROGRAM: "A program",
    CHANNEL: "A channel",
    WORDS: "Not bound",
}
"""The modes of a part for people, as the menu of the button and the button show them."""

COLUMN_PLACEHOLDERS: dict[str, Callable[[], str]] = {
    "step": lambda: "behavior.encoder_step % of the range",
    "push": lambda: "none: a push does nothing",
    "watch": lambda: "none: the value shows what was set last",
}
"""What an unset option of a program does, where its default is no value."""
DEFAULT_ENCODER_STEP = BehaviorConfig.model_fields["encoder_step"].default
"""Percent of the range one step of the encoder is by default (`behavior.encoder_step`)."""


def mode_of(value: object) -> str:
    """
    How a part is bound: `CHANNEL` for a table with `channel`, `ENTITY` for one with `entity`, `PROGRAM` for another
    table, `HOME_ASSISTANT`, or `WORDS` for a word, a switch or nothing.
    """
    if isinstance(value, Mapping):
        return CHANNEL if "channel" in value else ENTITY if "entity" in value else PROGRAM
    return HOME_ASSISTANT if value == HOME_ASSISTANT else WORDS


class BindingField(QWidget):
    """
    A part that can be bound. `changed` has the value for the file: a word, a bool, a table of the program, or None
    (not set: the default). `placeholder` tells what an unset part does where it is no plain value, `channels` the
    `custom` channels a part with `Option.channel` can set.
    """

    changed = pyqtSignal(object, arguments=["value"])

    def __init__(self, option: Option, placeholder: Callable[[], str] | None = None):
        super().__init__()
        self.option = option
        self._placeholder = placeholder
        self._value: Any = None
        self._table: dict[str, Any] = {}
        """The options of the program: those in the file, or the last ones while the part is bound otherwise."""
        self._entity: dict[str, Any] = {"entity": ""}
        """The options of the entity, as `_table` those of the program."""
        self._loading = False
        self.channels: Callable[[], list[str]] = list
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(Space.XS)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(Space.XS)
        self.words = self._words_field(option)
        top.addWidget(self.words)
        self.channel = Choice(self)
        """The `custom` channel whose value the part sets, in `CHANNEL`: typed, or picked from `channels`."""
        self.channel.setEditable(True)
        self.channel.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.channel.setMinimumWidth(160)
        self.channel.setToolTip("The `custom` channel whose value it sets")
        self.channel.lineEdit().setPlaceholderText("a custom channel")  # pyright: ignore[reportOptionalMemberAccess]
        self.channel.activated.connect(lambda _: self._channel())
        self.channel.lineEdit().editingFinished.connect(self._channel)  # pyright: ignore[reportOptionalMemberAccess]
        self.channel.hide()
        top.addWidget(self.channel)
        self.bind = QToolButton(self)
        set_icon(self.bind, "link-variant")
        self.bind.setAutoRaise(True)
        set_role(self.bind, "flat", "variant")
        self.bind.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.menu = QMenu(self.bind)
        self.actions_: dict[str, QAction] = {}
        modes = [
            *([HOME_ASSISTANT] if option.home_assistant else []),
            *([ENTITY] if option.entity is not None else []),
            PROGRAM,
            *([CHANNEL] if option.channel else []),
            WORDS,
        ]
        for mode in modes:
            action = self.menu.addAction(MODE_TITLES[mode])
            assert action is not None
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, mode=mode: self.bind_to(mode))
            self.actions_[mode] = action
        attach_menu(self.bind, self.menu)
        top.addWidget(self.bind)
        top.addStretch()
        outer.addLayout(top)
        # the options of the program, indented under the field
        self.program = QWidget(self)
        program = QVBoxLayout(self.program)
        program.setContentsMargins(Space.M, 0, 0, 0)
        program.setSpacing(0)
        program.addWidget(help_label(option.binding, "hint"))
        self.rows: dict[str, OptionRow] = {}
        self._add_rows(program)
        self.program.hide()
        outer.addWidget(self.program)
        # the options of the entity, likewise
        self.entity: EntityTable | None = None
        if option.entity is not None:
            skip = ("push",) if option.name == "fader" else ()
            self.entity = EntityTable(option.entity, "entity", skip)
            self.entity.setContentsMargins(Space.M, 0, 0, 0)
            self.entity.changed.connect(self._entity_changed)
            self.entity.hide()
            outer.addWidget(self.entity)

    def _words_field(self, option: Option) -> QWidget:
        """The field of the words of the part, as an option of them has it without bindings."""
        match option.base:
            case Kind.CHOICE:
                self.combo = Choice(self)
                self.combo.addItems([str(choice) for choice in option.choices])
                for index, choice in enumerate(option.choices):
                    self.combo.setItemData(index, help_text(option.meaning(choice)), Qt.ItemDataRole.ToolTipRole)
                self.combo.setMinimumWidth(160)
                self.combo.currentTextChanged.connect(self._word)
                return self.combo
            case Kind.SWITCH:
                self.switch = Switch(self)
                self.switch.toggled.connect(self._word)
                return self.switch
            case Kind.COLOR:
                self.colors = ColorPicker(option)
                self.colors.picked.connect(self._word)
                return self.colors
            case _:
                # nothing to pick: unbound, the part does what its default says
                self.unbound = label("", "hint")
                return self.unbound

    def _add_rows(self, layout: QVBoxLayout) -> None:
        # here, not at the top: option_row imports this module for its field
        from xtouch_daemon.gui.qt.fields.option_row import NumberSpin, OptionRow, align_titles

        for column in self.option.columns:
            row = OptionRow(
                column,
                lambda name=column.name: self._table.get(name),
                lambda value, name=column.name: self._put(name, value),
                placeholder=None if column.required else COLUMN_PLACEHOLDERS.get(column.name),
            )
            if isinstance(spin := getattr(row, "spin", None), NumberSpin):
                spin.start = self._start_of(column.name)
            self.rows[column.name] = row
            layout.addWidget(row)
        align_titles(self.rows.values())

    def _start_of(self, name: str) -> Callable[[], float]:
        """Where a number of the program starts once it is set: `step` at one step of the range, the rest at `min`."""

        def bounds() -> tuple[float, float]:
            low, high = self._table.get("min", 0), self._table.get("max", 100)
            if not isinstance(low, int | float) or not isinstance(high, int | float) or high <= low:
                return 0, 100
            return float(low), float(high)

        def start() -> float:
            low, high = bounds()
            return (high - low) * DEFAULT_ENCODER_STEP / 100 if name == "step" else low

        return start

    # -- showing --------------------------------------------------------------------------------------------------

    @property
    def mode(self) -> str:
        return mode_of(self._value)

    def show_value(self, value: object) -> None:
        """Shows the value in the file (None: not set), the default as a placeholder."""
        self._value = value
        mode = self.mode
        if mode == PROGRAM:
            self._table = dict(cast(Mapping[str, Any], value))
        if mode == ENTITY:
            self._entity = dict(cast(Mapping[str, Any], value))
        self._loading = True
        try:
            self._show_words(value)
            if mode == CHANNEL:
                self._show_channel(cast(Mapping[str, Any], value).get("channel"))
            for row in self.rows.values():
                row.load()
            if self.entity is not None:
                self.entity.show_table(self._entity)
        finally:
            self._loading = False
        in_words = mode == WORDS or (mode == HOME_ASSISTANT and HOME_ASSISTANT in self.option.choices)
        self.words.setVisible(in_words)
        self.channel.setVisible(mode == CHANNEL)
        self.program.setVisible(mode == PROGRAM)
        if self.entity is not None:
            self.entity.setVisible(mode == ENTITY)
            if mode == ENTITY:
                self.entity.want()
        bound = not in_words
        self.bind.setText(MODE_TITLES[mode] if bound else "")
        targets = [
            *(["Home Assistant"] if self.option.home_assistant else []),
            *(
                ["one of its entities" if self.option.home_assistant else "an entity of Home Assistant"]
                if self.option.entity is not None
                else []
            ),
            "a program of your own",
            *(["a custom channel"] if self.option.channel else []),
        ]
        self.bind.setToolTip(
            f"Bound to {MODE_TITLES[mode] if mode == HOME_ASSISTANT else MODE_TITLES[mode].lower()}: click to change"
            if bound
            else "Bind it to " + (", ".join(targets[:-1]) + " or " if len(targets) > 1 else "") + targets[-1]
        )
        for each, action in self.actions_.items():
            action.setChecked(each == mode)
        self.actions_[WORDS].setVisible(value is not None)

    def _show_channel(self, name: object) -> None:
        """The channel of `CHANNEL` and the ones it could be: the `custom` channels of the file."""
        self.channel.clear()
        self.channel.addItems(self.channels())
        self.channel.setCurrentIndex(-1)
        self.channel.setEditText(name if isinstance(name, str) else "")

    def _default_text(self) -> str:
        return self._placeholder() if self._placeholder is not None else describe(self.option.default)

    def _show_words(self, value: object) -> None:
        shown = self.option.default if value is None else value
        match self.option.base:
            case Kind.CHOICE:
                choices = [str(choice) for choice in self.option.choices]
                self.combo.setCurrentIndex(choices.index(shown) if isinstance(shown, str) and shown in choices else -1)
                self.combo.setPlaceholderText(f"default: {self._default_text()}")
            case Kind.SWITCH:
                self.switch.setChecked(shown is True)
            case Kind.COLOR:
                self.colors.show_value(str(shown))
            case _:
                self.unbound.setText(f"default: {self._default_text()}" if value is None else "")

    def word(self) -> object:
        """The word shown (or what it is by default), None while the part is bound to a program or a channel."""
        if self.mode in (PROGRAM, CHANNEL, ENTITY):
            return None
        if self._value is None and self.option.default is None and self._placeholder is not None:
            return self._placeholder()
        return self.option.default if self._value is None else self._value

    # -- editing --------------------------------------------------------------------------------------------------

    def bind_to(self, mode: str) -> None:
        """
        Binds the part to Home Assistant, a program (with the options it had last) or a channel (the first `custom`
        one), or not (its default).
        """
        if mode == CHANNEL:
            channels = self.channels()
            self._emit({"channel": channels[0] if channels else ""})
            return
        value: object = {
            HOME_ASSISTANT: HOME_ASSISTANT,
            PROGRAM: dict(self._table),
            ENTITY: dict(self._entity),
            WORDS: None,
        }[mode]
        self._emit(value)

    def _channel(self) -> None:
        """A channel was picked or typed."""
        name = self.channel.currentText().strip()
        if self._loading or self.mode != CHANNEL or name == cast(Mapping[str, Any], self._value).get("channel"):
            return
        self._value = {"channel": name}
        self.changed.emit(self._value)

    def _word(self, value: object) -> None:
        if self._loading:
            return
        if self.option.base == Kind.CHOICE and self.combo.currentIndex() < 0:
            value = None
        self._emit(value)

    def _put(self, name: str, value: Any) -> None:
        """An option of the program changed: the table goes to the file (an empty one stays: the part is bound)."""
        if value is None:
            self._table.pop(name, None)
        else:
            self._table[name] = value
        # the rows stay as they are: one of them is being edited
        self._value = dict(self._table)
        self.changed.emit(self._value)

    def _entity_changed(self, table: dict[str, Any]) -> None:
        """An option of the entity changed: the table goes to the file."""
        self._entity = table
        self._value = dict(table)
        self.changed.emit(self._value)

    def shown_rows(self) -> dict[str, OptionRow]:
        """The rows of the options shown below the field: of the program, of the entity, or none."""
        if self.mode == ENTITY and self.entity is not None:
            return self.entity.rows
        return self.rows if self.mode == PROGRAM else {}

    @property
    def entity_rows(self) -> dict[str, OptionRow]:
        """The rows of the options of the entity, none for a part that takes none."""
        return self.entity.rows if self.entity is not None else {}

    def _emit(self, value: object) -> None:
        self.show_value(value)
        self.changed.emit(value)
