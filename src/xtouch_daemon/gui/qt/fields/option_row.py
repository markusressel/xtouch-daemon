"""
One option of a form: its label, the field for its type, its help and its problems.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, assert_never

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.domain.schema import Kind, Option, describe
from xtouch_daemon.gui.qt.fields.basics import (
    LABEL_WIDTH,
    NO_SUGGESTIONS,
    NO_SUGGESTIONS_OF,
    Suggest,
    TableSuggest,
    completer,
    flat_button,
    help_label,
    help_text,
    label,
    set_help,
    suggestion_menu,
)
from xtouch_daemon.gui.qt.fields.chips import Chips
from xtouch_daemon.gui.qt.fields.controls import ColorPicker, NumberToggles, Switch
from xtouch_daemon.gui.qt.fields.tables import Tables
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space


class OptionRow(QWidget):
    """
    One option: its name, a field for its kind of value, a button back to the default, the help with the default and
    a link to the documentation (`link`), what the chosen value means, and its problems. `get` returns the value in
    the file (None: not set), `put` sets it (None: removes it, so the default applies).
    """

    edited = pyqtSignal(arguments=[])

    def __init__(
        self,
        option: Option,
        get: Callable[[], Any],
        put: Callable[[Any], None],
        suggest: Suggest | TableSuggest | None = None,
        placeholder: Callable[[], str] | None = None,
        link: str | None = None,
    ):
        """`suggest` is a `TableSuggest` only for an option of `Kind.TABLES`."""
        super().__init__()
        self.option = option
        self._get = get
        self._put = put
        self._placeholder = placeholder
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, Space.XS, 0, Space.XS)
        outer.setSpacing(Space.XS)
        top = QHBoxLayout()
        top.setSpacing(Space.S)
        title = label(option.title + ("  *" if option.required else ""))
        title.setFixedWidth(LABEL_WIDTH)
        title.setToolTip(option.name + (", required" if option.required else ""))
        top.addWidget(title)
        top.addWidget(self._field(option, suggest), 1)
        self.reset = flat_button("restore", f"Back to the default ({describe(option.default)})", self)
        self.reset.clicked.connect(self._reset)
        top.addWidget(self.reset)
        outer.addLayout(top)
        details = QVBoxLayout()
        details.setContentsMargins(LABEL_WIDTH + Space.S, 0, 0, 0)
        details.setSpacing(2)
        # what the chosen value means, for choices that say it (shown by `load` and `_edit`), right under the field
        self.meaning = help_label("", "meaning")
        self.meaning.hide()
        details.addWidget(self.meaning)
        help_parts = [option.help, f"Default: `{option.default_text}`." if option.default_text else ""]
        self.help = help_label(" ".join(part for part in help_parts if part), "help", link)
        if not (option.help or option.default_text or link):
            # hidden only: shown before it is in the row, a widget without a parent is a window of its own
            self.help.hide()
        details.addWidget(self.help)
        if option.kind == Kind.SECRET:
            details.addWidget(label("It is saved as plain text in the configuration file.", "help"))
        self.error = label("", "error", wrap=True)
        self.error.hide()
        details.addWidget(self.error)
        outer.addLayout(details)
        self.load()

    # -- the fields of the kinds ----------------------------------------------------------------------------------

    def _field(self, option: Option, suggest: Suggest | TableSuggest | None) -> QWidget:
        match option.kind:
            case Kind.TEXT | Kind.SECRET | Kind.PATH:
                return self._text_field(option, None if isinstance(suggest, Mapping) else suggest)
            case Kind.INTEGER:
                self.spin: QSpinBox | QDoubleSpinBox = QSpinBox(self)
                minimum = int(option.minimum or 0)
                if option.default is None:
                    # one below the minimum is "not set", shown as text
                    self._unset: float = minimum - 1
                    minimum = self._unset
                self.spin.setRange(int(minimum), int(option.maximum or 1_000_000))
                self.spin.valueChanged.connect(self._edit_number)
                return self._left(self.spin)
            case Kind.NUMBER:
                self.spin = QDoubleSpinBox(self)
                self.spin.setDecimals(1)
                self.spin.setSingleStep(0.5)
                low = option.minimum or 0
                if option.default is None:
                    # a step below the minimum is "not set", shown as text
                    self._unset = low - 0.5
                    low = self._unset
                self.spin.setRange(low, option.maximum or 1_000_000)
                self.spin.valueChanged.connect(self._edit_number)
                return self._left(self.spin)
            case Kind.SWITCH:
                self.switch = Switch(self)
                self.switch.toggled.connect(self._edit)
                return self._left(self.switch)
            case Kind.CHOICE:
                self.combo = QComboBox(self)
                self.combo.addItems(list(option.choices))
                for index, choice in enumerate(option.choices):
                    # what each one means, while the list is open
                    self.combo.setItemData(index, help_text(option.meaning(choice)), Qt.ItemDataRole.ToolTipRole)
                self.combo.setMinimumWidth(160)
                self.combo.currentTextChanged.connect(self._edit)
                return self._left(self.combo)
            case Kind.COLOR:
                self.colors = ColorPicker(option)
                self.colors.picked.connect(self._edit)
                self.input = self.colors
                return self.colors
            case Kind.LIST:
                self.chips = Chips(
                    None if isinstance(suggest, Mapping) else suggest,
                    self._placeholder,
                    NO_SUGGESTIONS_OF.get(option.name, NO_SUGGESTIONS),
                    option.presets,
                )
                self.chips.changed.connect(self._edit)
                self.input = self.chips
                return self.chips
            case Kind.NUMBERS:
                self.numbers = NumberToggles(int(option.minimum or 0), int(option.maximum or 0))
                self.numbers.changed.connect(self._edit)
                self.input = self.numbers
                return self.numbers
            case Kind.TABLES:
                self.tables = Tables(option.columns, suggest)
                self.tables.changed.connect(self._edit)
                self.input = self.tables
                return self.tables
            case _ as unreachable:
                assert_never(unreachable)

    def _left(self, widget: QWidget) -> QWidget:
        """The widget at its own size, on the left."""
        self.input = widget
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
        layout.addStretch()
        return container

    def _text_field(self, option: Option, suggest: Suggest | None) -> QWidget:
        edit = QLineEdit(self)
        self.line = self.input = edit
        if option.max_length is not None:
            edit.setMaxLength(option.max_length)
        edit.textEdited.connect(self._edit_text)
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Space.XS)
        layout.addWidget(edit, 1)
        if suggest is not None:
            completer(edit, suggest).activated.connect(self._pick)
            layout.addWidget(suggestion_menu(container, suggest, self._pick, "Nothing to pick from"))
        if option.kind == Kind.SECRET:
            # hidden, also from someone looking over the shoulder; the eye shows it
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            reveal = flat_button("eye", "Show it", container)
            reveal.setCheckable(True)
            reveal.toggled.connect(
                lambda shown: edit.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
            )
            layout.addWidget(reveal)
        if option.kind == Kind.PATH:
            browse = flat_button("folder-open", "Choose the file", container)
            browse.clicked.connect(self._browse)
            layout.addWidget(browse)
        return container

    def _browse(self) -> None:
        current = self.line.text() or self.line.placeholderText() or "~"
        path, _ = QFileDialog.getOpenFileName(
            self, f"Choose {self.option.title.lower()}", str(Path(current).expanduser())
        )
        if path:
            # the daemon expands ~, which keeps the configuration usable for another user name
            home = str(Path.home())
            self._pick("~" + path[len(home) :] if path.startswith(home + "/") else path)

    def _pick(self, value: str) -> None:
        self.line.setText(value)
        self._edit_text(value)

    def _edit_text(self, text: str) -> None:
        self._edit(text)

    # -- showing and editing --------------------------------------------------------------------------------------

    def load(self) -> None:
        """Shows the value in the file, or the default."""
        value = self._get()
        shown = self.option.default if value is None else value
        self._loading = True
        try:
            match self.option.kind:
                case Kind.TEXT | Kind.SECRET | Kind.PATH:
                    self.line.setText(value if isinstance(value, str) else "")
                    default = self._placeholder() if self._placeholder else self.option.default
                    self.line.setPlaceholderText("" if default is None else str(default))
                case Kind.INTEGER | Kind.NUMBER:
                    # a value of another type shows the default; its problem says what is wrong
                    number = shown if isinstance(shown, int | float) else self.option.default
                    if self.option.default is None:
                        default = self._placeholder() if self._placeholder else "not set"
                        self.spin.setSpecialValueText(f"default: {default}")
                    if isinstance(self.spin, QSpinBox):
                        self.spin.setValue(int(self._unset) if number is None else int(number))
                    else:
                        self.spin.setValue(self._unset if number is None else float(number))
                case Kind.SWITCH:
                    self.switch.setChecked(bool(shown))
                case Kind.CHOICE:
                    self.combo.setCurrentIndex(self.option.choices.index(shown) if shown in self.option.choices else -1)
                    if self._placeholder:
                        # shown while none is chosen
                        self.combo.setPlaceholderText(f"default: {self._placeholder()}")
                    self._show_meaning()
                case Kind.COLOR:
                    self.colors.show_value(str(shown))
                case Kind.LIST:
                    # a single value may stand alone, e.g. `device = "speaker"`
                    self.chips.show_values([shown] if isinstance(shown, str) else [str(item) for item in shown or ()])
                case Kind.NUMBERS:
                    # a value of another type shows none; its problem says what is wrong
                    self.numbers.show_values(list(shown) if isinstance(shown, list | tuple) else [])
                case Kind.TABLES:
                    # a value of another type shows none; its problem says what is wrong
                    tables = shown if isinstance(shown, list | tuple) else ()
                    self.tables.show_values([dict(table) for table in tables if isinstance(table, dict)])
                case _ as unreachable:
                    assert_never(unreachable)
        finally:
            self._loading = False
        self.reset.setVisible(value is not None and not self.option.required)

    def _edit(self, value: Any) -> None:
        if self._loading:
            return
        if value in ("", []):
            # an empty text or list is none: the default applies (or the option is missing, if it is required)
            value = None
        self._put(value)
        self.reset.setVisible(value is not None and not self.option.required)
        if self.option.kind == Kind.CHOICE:
            self._show_meaning()
        self.edited.emit()

    def _show_meaning(self) -> None:
        """What the chosen value means; while none is chosen, what the default (the placeholder) means."""
        value = self.combo.currentText() if self.combo.currentIndex() >= 0 else None
        if value is None and self._placeholder:
            value = self._placeholder()
        meaning = self.option.meaning(value)
        set_help(self.meaning, f"`{value}`: {meaning}" if meaning else "")
        self.meaning.setVisible(bool(meaning))

    def _edit_number(self, value: float) -> None:
        self._edit(None if self.option.default is None and value == self._unset else value)

    def _reset(self) -> None:
        self._put(None)
        self.load()
        self.edited.emit()

    def show_problems(self, problems: list[Problem]) -> None:
        self.error.setText("\n".join(self._problem_text(problem) for problem in problems))
        self.error.setVisible(bool(problems))
        set_role(self.input, bool(problems), "problem")

    def _problem_text(self, problem: Problem) -> str:
        """The message, after the table and column for a problem in one of `TABLES` (e.g. "2. label: ...")."""
        rest = problem.path[problem.path.index(self.option.name) + 1 :] if self.option.name in problem.path else ()
        if self.option.kind != Kind.TABLES or not rest or not isinstance(rest[0], int):
            return problem.message
        where = " ".join([f"{rest[0] + 1}.", *map(str, rest[1:])])
        return f"{where}: {problem.message}"
