"""
Lists of tables (e.g. the `choices` of a strip) as an editable table.
"""

from collections.abc import Mapping

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from xtouch_daemon.gui.domain.schema import Kind, Option
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt import theme
from xtouch_daemon.gui.qt.fields.basics import (
    ColumnSuggest,
    Suggest,
    TableSuggest,
    completer,
    flat_button,
    help_text,
    suggestion_menu,
)


class Tables(QWidget):
    """
    A list of tables with texts and numbers (e.g. the profiles of a strip): a line of fields for each, a button to add
    one. A `Suggest` is for the value: the first text column without a length limit (a label has one); a
    `TableSuggest` names the columns, which get the other values of their line (e.g. the profiles of its card).
    """

    changed = pyqtSignal(list, arguments=["values"])

    def __init__(self, columns: tuple[Option, ...], suggest: Suggest | TableSuggest | None):
        super().__init__()
        self.columns = columns
        if isinstance(suggest, Mapping):
            self._suggest: dict[str, ColumnSuggest] = dict(suggest)
        elif suggest is not None:
            value = next(column for column in columns if column.kind == Kind.TEXT and column.max_length is None)
            self._suggest = {value.name: lambda _line, suggest=suggest: suggest()}
        else:
            self._suggest = {}
        self.values: list[dict[str, str | int]] = []
        self.lines: list[list[QLineEdit]] = []
        self._row_widgets: list[QWidget] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.Space.XS)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(theme.Space.XS)
        layout.addLayout(self.rows)
        self.add_button = QPushButton("Add", self)
        theme.set_icon(self.add_button, "plus")
        self.add_button.clicked.connect(self.add)
        add = QHBoxLayout()
        add.addWidget(self.add_button)
        add.addStretch()
        layout.addLayout(add)

    def show_values(self, values: list[dict[str, str | int]]) -> None:
        self.values = [dict(value) for value in values]
        for widget in self._row_widgets:
            self.rows.removeWidget(widget)
            widget.deleteLater()
        self.lines = []
        self._row_widgets = [self._row(index, value) for index, value in enumerate(self.values)]
        for widget in self._row_widgets:
            self.rows.addWidget(widget)

    def _row(self, index: int, value: dict[str, str | int]) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.Space.XS)
        lines: list[QLineEdit] = []
        for column in self.columns:
            edit = QLineEdit(str(value.get(column.name, "")), row)
            edit.setPlaceholderText(column.title)
            edit.setToolTip(help_text(column.help))
            if column.max_length is not None:
                edit.setMaxLength(column.max_length)
            edit.textEdited.connect(lambda text, name=column.name: self._edit(index, name, text))
            lines.append(edit)
        for column, edit in zip(self.columns, lines, strict=True):
            wide = column.kind == Kind.TEXT and column.max_length is None
            if not wide:
                # a label, a number: narrow
                edit.setMaximumWidth(120 if column.kind == Kind.TEXT else 110)
            layout.addWidget(edit, 1 if wide else 0)
            column_suggest = self._suggest.get(column.name)
            if column_suggest is not None:
                name = column.name

                def suggest(column_suggest: ColumnSuggest = column_suggest) -> tuple[Suggestion, ...]:
                    return column_suggest(self.values[index])

                completer(edit, suggest).activated.connect(lambda text, name=name: self._edit(index, name, text))
                layout.addWidget(
                    suggestion_menu(
                        row, suggest, lambda text, name=name: self._pick(index, name, text), "The sound server has none"
                    )
                )
        remove = flat_button("close", "Remove it", row)
        remove.clicked.connect(lambda: self.remove(index))
        layout.addWidget(remove)
        self.lines.append(lines)
        return row

    def _edit(self, index: int, name: str, text: str) -> None:
        column = next(column for column in self.columns if column.name == name)
        if text:
            # a number that isn't one stays text: its problem says so
            self.values[index][name] = int(text) if column.kind == Kind.INTEGER and text.isdigit() else text
        else:
            # a missing value: its problem says it is required
            self.values[index].pop(name, None)
        self.changed.emit([dict(value) for value in self.values])

    def _pick(self, index: int, name: str, text: str) -> None:
        column = next(i for i, column in enumerate(self.columns) if column.name == name)
        self.lines[index][column].setText(text)
        self._edit(index, name, text)

    def add(self) -> None:
        self.show_values([*self.values, {}])
        self.changed.emit([dict(value) for value in self.values])
        self.lines[-1][0].setFocus()

    def remove(self, index: int) -> None:
        self.show_values(self.values[:index] + self.values[index + 1 :])
        self.changed.emit([dict(value) for value in self.values])
