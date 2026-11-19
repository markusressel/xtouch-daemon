"""
One option of a form: its label, the field for its type, its help and its problems.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, assert_never

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.domain import sources
from xtouch_daemon.gui.domain.schema import Kind, Option, describe
from xtouch_daemon.gui.qt.fields.basics import (
    LABEL_WIDTH,
    NO_SUGGESTIONS,
    NO_SUGGESTIONS_OF,
    Suggest,
    TableSuggest,
    flat_button,
    help_label,
    help_text,
    indent_text,
    label,
    set_help,
)
from xtouch_daemon.gui.qt.fields.buttons import ButtonField
from xtouch_daemon.gui.qt.fields.chips import Chips
from xtouch_daemon.gui.qt.fields.controls import ColorPicker, NumberToggles, Switch
from xtouch_daemon.gui.qt.fields.names import NameCompleter
from xtouch_daemon.gui.qt.fields.tables import Tables
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space

MATCHED = frozenset({"device", "card", "profile"})
"""The options whose value names something of the sound server, with what it matches under the field."""
FIELD_WIDTH = 320
"""The least room for a field beside its name: below it, the name goes above the field."""
NARROW_BELOW = LABEL_WIDTH + Space.S + FIELD_WIDTH
"""Below it, a row with the widest column of names puts its name above its field."""
WIDEST_TITLE = LABEL_WIDTH + 2 * Space.L
"""The widest column of names `align_titles` makes: a longer name wraps."""


def text_width(widget: QLabel) -> int:
    """The width a label needs for its text in one line: not its size hint, which a fixed width already set."""
    margins = widget.contentsMargins()
    return (
        widget.fontMetrics().horizontalAdvance(widget.text())
        + margins.left()
        + margins.right()
        + 2 * widget.margin()
        + 2
    )


def align_titles(rows: Iterable[OptionRow], indented: Iterable[OptionRow] = (), least: int = 0) -> int:
    """
    Makes the column of names of rows that are shown together as wide as their longest name (up to WIDEST_TITLE), so
    their fields line up close to the names; rows in `indented` are moved right by Space.L, and their names are that
    much narrower; `least` is the longest of other names in the column. Returns the width.
    """
    rows = list(rows)
    moved = {id(row) for row in indented}
    width = min(WIDEST_TITLE, max((text_width(row.title) for row in rows), default=least))
    width = max(width, min(WIDEST_TITLE, least))
    for row in rows:
        row.set_title_width(width - (Space.L if id(row) in moved else 0))
    return width


def divider() -> QFrame:
    """A thin line between the options of a form, so each reads as one."""
    line = QFrame()
    set_role(line, "divider")
    line.setFixedHeight(1)
    return line


def add_rows(layout: QBoxLayout, widgets: Iterable[QWidget]) -> None:
    """The rows of a form, with a line between each two."""
    for index, widget in enumerate(widgets):
        if index:
            layout.addWidget(divider())
        layout.addWidget(widget)


def add_groups(layout: QBoxLayout, groups: Iterable[tuple[str, Sequence[QWidget]]]) -> None:
    """
    Groups of rows (e.g. the display, the buttons, the fader of a place), each under its title, with a line between
    each two rows and more room between the groups.
    """
    for index, (title, widgets) in enumerate(groups):
        if index:
            layout.addSpacing(Space.M)
        layout.addWidget(label(title.upper(), "group"))
        add_rows(layout, widgets)


class OptionRow(QWidget):
    """
    One option: its name, a field for its kind of value, a button back to the default, the help with the default and
    a link to the documentation (`link`), what the chosen value means, and its problems. `get` returns the value in
    the file (None: not set), `put` sets it (None: removes it, so the default applies).
    """

    edited = pyqtSignal(arguments=[])
    picked = pyqtSignal(object, arguments=["suggestion"])
    """A name was picked from the list of a text field: what is known of it (a `Suggestion`)."""

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
        self.resettable = True
        """Shows the button back to the default while a value is set; off where the page removes it another way."""
        self.names: tuple[str, ...] = (option.name,)
        """The options of the file the row edits: its problems are theirs (e.g. `device` and `choices`)."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, Space.XS, 0, Space.XS)
        outer.setSpacing(Space.XS)
        self.top = QGridLayout()
        self.top.setHorizontalSpacing(Space.S)
        self.top.setVerticalSpacing(Space.XS)
        self.title = label(option.title + ("  *" if option.required else ""))
        self.title.setToolTip(option.name + (", required" if option.required else ""))
        self.field = self._field(option, suggest)
        self.reset = flat_button("restore", f"Back to the default ({describe(option.default)})", self)
        self.reset.clicked.connect(self._reset)
        outer.addLayout(self.top)
        self.details = QVBoxLayout()
        details = self.details
        details.setSpacing(2)
        self.title_width = LABEL_WIDTH
        """The width of the column of names (see `align_titles`)."""
        self.narrow: bool | None = None
        """Whether the name is above the field (the row is too narrow for both side by side); None before a size."""
        self._arrange(narrow=False)
        # what the chosen value means, for choices that say it (shown by `load` and `_edit`), right under the field
        self.meaning = help_label("", "meaning")
        self.meaning.hide()
        details.addWidget(self.meaning)
        # what a name matches of what is known, right under its field (see `_show_matches`)
        self.matches = label("", "help", wrap=True)
        self.matches.hide()
        details.addWidget(self.matches)
        self.help = help_label(option.help, "help", link, option.default_text or None)
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

    # -- the layout -----------------------------------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        width = self.width()
        # a margin both ways: the scroll bar that comes with a taller row must not switch it back
        narrow_below = self.title_width + Space.S + FIELD_WIDTH
        if self.narrow is not True and width < narrow_below:
            self._arrange(narrow=True)
        elif self.narrow is not False and width > narrow_below + Space.M:
            self._arrange(narrow=False)

    def set_title_width(self, width: int) -> None:
        """The width of the column of names, for the rows shown with it (see `align_titles`)."""
        self.title_width = width
        if self.narrow is False:
            self.title.setFixedWidth(width)
            self.details.setContentsMargins(width + Space.S, 0, 0, 0)

    def _arrange(self, narrow: bool) -> None:
        """The name left of the field (in the column of the names), or above it in a narrow row."""
        if narrow == self.narrow:
            return
        self.narrow = narrow
        for widget in (self.title, self.field, self.reset):
            self.top.removeWidget(widget)
        if narrow:
            self.title.setMinimumWidth(0)
            self.title.setMaximumWidth(16_777_215)
            self.top.addWidget(self.title, 0, 0, 1, 2)
            self.top.addWidget(self.field, 1, 0)
            self.top.addWidget(self.reset, 1, 1)
        else:
            # a list of entries: its name and reset at the top, not beside its middle
            top = Qt.AlignmentFlag.AlignTop if self.option.kind in (Kind.TABLES, Kind.BUTTON) else Qt.AlignmentFlag(0)
            self.title.setFixedWidth(self.title_width)
            self.top.addWidget(self.title, 0, 0, top)
            self.top.addWidget(self.field, 0, 1)
            self.top.addWidget(self.reset, 0, 2, top)
        self.top.setColumnStretch(0, 1 if narrow else 0)
        self.top.setColumnStretch(1, 0 if narrow else 1)
        self.top.setColumnStretch(2, 0)
        self.details.setContentsMargins(0 if narrow else self.title_width + Space.S, 0, 0, 0)

    # -- the fields of the kinds ----------------------------------------------------------------------------------

    def _field(self, option: Option, suggest: Suggest | TableSuggest | None) -> QWidget:
        match option.kind:
            case Kind.TEXT | Kind.SECRET | Kind.PATH | Kind.ACTION:
                return self._text_field(option, None if isinstance(suggest, Mapping) else suggest)
            case Kind.INTEGER:
                self.spin: QSpinBox | QDoubleSpinBox = QSpinBox(self)
                indent_text(self.spin)
                minimum = int(option.minimum or 0)
                if option.default is None:
                    # one below the minimum is "not set", shown as text
                    self._unset: float = minimum - 1
                    minimum = self._unset
                self.spin.setRange(int(minimum), int(option.maximum or 1_000_000))
                if option.name.endswith("_volume"):
                    self.spin.setSuffix(" %")
                self.spin.valueChanged.connect(self._edit_number)
                return self._left(self.spin)
            case Kind.NUMBER:
                self.spin = QDoubleSpinBox(self)
                indent_text(self.spin)
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
            case Kind.BUTTON:
                self.buttons = ButtonField(option.name, option.columns)
                self.buttons.changed.connect(self._edit)
                self.input = self.buttons
                return self.buttons
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
        self.completer: NameCompleter | None = None
        if suggest is not None:
            self.completer = NameCompleter(edit, suggest, NO_SUGGESTIONS_OF.get(option.name, NO_SUGGESTIONS))
            self.completer.activated.connect(self._pick)
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
        if self.completer is not None and (suggestion := self.completer.suggestion(value)) is not None:
            self.picked.emit(suggestion)

    def _show_matches(self) -> None:
        """Under a name: which of the known ones it matches, or that it matches none (nothing while it is empty)."""
        value = self.line.text()
        if self.completer is None or not value or self.option.name not in MATCHED:
            self.matches.hide()
            return
        text, found = sources.matches_text(value, self.completer.suggest())
        self.matches.setText(text)
        set_role(self.matches, "help" if found else "warn")
        self.matches.show()

    def _edit_text(self, text: str) -> None:
        self._edit(text)
        self._show_matches()

    # -- showing and editing --------------------------------------------------------------------------------------

    def load(self) -> None:
        """Shows the value in the file, or the default."""
        value = self._get()
        shown = self.option.default if value is None else value
        self._loading = True
        try:
            match self.option.kind:
                case Kind.TEXT | Kind.SECRET | Kind.PATH | Kind.ACTION:
                    self.line.setText(value if isinstance(value, str) else "")
                    self._show_matches()
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
                case Kind.BUTTON:
                    self.buttons.show_value(value)
                case _ as unreachable:
                    assert_never(unreachable)
        finally:
            self._loading = False
        self.reset.setVisible(self.resettable and value is not None and not self.option.required)

    def _edit(self, value: Any) -> None:
        if self._loading:
            return
        if value in ("", []):
            # an empty text or list is none: the default applies (or the option is missing, if it is required)
            value = None
        self._put(value)
        self.reset.setVisible(self.resettable and value is not None and not self.option.required)
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
        name = next((name for name in self.names if name in problem.path), None)
        rest = () if name is None else problem.path[problem.path.index(name) + 1 :]
        if self.option.kind != Kind.TABLES or not rest or not isinstance(rest[0], int):
            return problem.message
        where = " ".join([f"{rest[0] + 1}.", *map(str, rest[1:])])
        return f"{where}: {problem.message}"
