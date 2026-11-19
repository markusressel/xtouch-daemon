"""
Lists of tables (e.g. the `choices` of a strip): an entry each, a summary of it that opens into its fields.
"""

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import QMimeData, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from xtouch_daemon.gui.domain.schema import Kind, Option
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt.fields.basics import ColumnSuggest, Suggest, TableSuggest, flat_button, label
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space

MIME = "application/x-xtouch-daemon-entry"
"""What a dragged entry carries: its place in the list."""
FOLDED = ("card", "profile")
"""Columns that stay folded while unset, behind a button of their own (`FOLD_TEXT`), when the table has a `device`."""
FOLD_TEXT = "Switch the sound card first"
TABLE_PLACEHOLDERS = {
    "min_volume": "the channel's",
    "max_volume": "the channel's",
    "label": "the start of the description of the device",
}
"""What an unset column takes, by name."""


class Handle(QLabel):
    """The grip of an entry: dragging it moves the entry in the list."""

    def __init__(self, index: int, parent: QWidget):
        super().__init__("⠿", parent)
        self.index = index
        set_role(self, "hint")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to move it (or Ctrl+Up/Down): the order is the order they are picked in")
        self._start: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        assert event is not None
        self._start = event.position().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        assert event is not None
        if self._start is None or (event.position().toPoint() - self._start).manhattanLength() < 4:
            return
        self._start = None
        data = QMimeData()
        data.setData(MIME, str(self.index).encode())
        drag = QDrag(self)
        drag.setMimeData(data)
        entry = self.parentWidget()
        assert entry is not None
        drag.setPixmap(entry.grab())
        drag.exec(Qt.DropAction.MoveAction)


class Entry(QFrame):
    """
    One table of the list: a summary (what it is, what it needs, its range), and its fields while it is open (an
    `OptionRow` per column, built when it opens first).
    """

    def __init__(self, tables: Tables, index: int):
        super().__init__(tables)
        self.tables = tables
        self.index = index
        set_role(self, "entry")
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Space.S, Space.S, Space.S, Space.S)
        layout.setSpacing(Space.S)
        head = QHBoxLayout()
        head.setSpacing(Space.S)
        self.handle = Handle(index, self)
        head.addWidget(self.handle, 0, Qt.AlignmentFlag.AlignTop)
        summary = QVBoxLayout()
        summary.setSpacing(0)
        self.title = label("", "entry_title", wrap=True)
        self.detail = label("", "hint", wrap=True)
        summary.addWidget(self.title)
        summary.addWidget(self.detail)
        head.addLayout(summary, 1)
        self.edit_button = flat_button("pencil", "Edit it (or a double click)", self)
        self.edit_button.setCheckable(True)
        self.edit_button.toggled.connect(lambda shown: tables.open(index if shown else None))
        self.remove_button = flat_button("delete-outline", "Remove it", self)
        self.remove_button.clicked.connect(lambda: tables.remove(index))
        head.addWidget(self.edit_button, 0, Qt.AlignmentFlag.AlignTop)
        head.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(head)
        self.fields = QWidget(self)
        self.fields.hide()
        layout.addWidget(self.fields)
        self.rows: dict[str, Any] = {}
        """The `OptionRow` of each column, by name, once the entry was open."""
        self.fold: QToolButton | None = None
        self.folded: QWidget | None = None
        self.show_summary()

    @property
    def value(self) -> dict[str, str | int]:
        return self.tables.values[self.index]

    def show_summary(self) -> None:
        """What the entry is, in a line, and below what it needs and its range, each only when it says something."""
        value = self.value
        described = {
            name: self.tables.describe(self.index, name)
            for name in ("label", "device", "profile", "card")
            if value.get(name) not in (None, "")
        }
        title = described.get("label") or described.get("device") or described.get("profile") or "New"
        lines: list[str] = []
        if "label" in described and "device" in described:
            lines.append(described["device"])
        if "profile" in described and "device" in value:
            lines.append(f'Switches its sound card to "{described["profile"]}" first')
        elif "profile" in described and "label" in described:
            lines.append(described["profile"])
        bottom, top = value.get("min_volume"), value.get("max_volume")
        if bottom is not None or top is not None:
            lines.append(
                f"Volume up to {top} %"
                if bottom is None
                else f"Volume from {bottom} %"
                if top is None
                else f"Volume {bottom} – {top} %"
            )
        self.title.setText(str(title))
        self.detail.setText("\n".join(lines))
        self.detail.setVisible(bool(lines))

    def set_open(self, shown: bool) -> None:
        if shown and not self.rows:
            self._build_fields()
        self.fields.setVisible(shown)
        self.edit_button.blockSignals(True)
        self.edit_button.setChecked(shown)
        self.edit_button.blockSignals(False)
        set_role(self, shown, "open")

    def _build_fields(self) -> None:
        # not at the top: option_row builds a `Tables` for a list of tables
        from xtouch_daemon.gui.qt.fields.option_row import OptionRow

        layout = QVBoxLayout(self.fields)
        layout.setContentsMargins(Space.L, 0, 0, 0)
        layout.setSpacing(0)
        names = {column.name for column in self.tables.columns}
        folds = "device" in names and all(name in names for name in FOLDED)
        folded = QWidget(self.fields)
        folded_layout = QVBoxLayout(folded)
        folded_layout.setContentsMargins(Space.L, 0, 0, 0)
        folded_layout.setSpacing(0)
        for column in self.tables.columns:
            placeholder = TABLE_PLACEHOLDERS.get(column.name)
            option_row = OptionRow(
                column,
                lambda name=column.name: self.value.get(name),
                lambda value, name=column.name: self.tables.put(self.index, name, value),
                self.tables.suggest_for(self.index, column.name),
                None if placeholder is None else lambda text=placeholder: text,
            )
            self.rows[column.name] = option_row
            if folds and column.name in FOLDED:
                folded_layout.addWidget(option_row)
            else:
                layout.addWidget(option_row)
            if folds and column.name == "device":
                fold = QToolButton(self.fields)
                fold.setText(FOLD_TEXT)
                fold.setToolTip(
                    "For a device that is there only in a profile of its sound card, e.g. the digital output while "
                    "the card is in its analog profile"
                )
                fold.setCheckable(True)
                fold.setAutoRaise(True)
                fold.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                fold.toggled.connect(self._unfold)
                layout.addWidget(fold)
                layout.addWidget(folded)
                self.fold, self.folded = fold, folded
        if self.fold is not None:
            shown = any(self.value.get(name) not in (None, "") for name in FOLDED)
            self.fold.setChecked(shown)
            self._unfold(shown)

    def _unfold(self, shown: bool) -> None:
        assert self.fold is not None
        assert self.folded is not None
        self.folded.setVisible(shown)
        self.fold.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

    def focus_first(self) -> None:
        first = self.rows.get(self.tables.columns[0].name)
        if first is not None:
            first.input.setFocus()

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        self.tables.open(None if self.fields.isVisible() else self.index)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        assert event is not None
        if event.key() == Qt.Key.Key_Escape and self.fields.isVisible():
            self.tables.open(None)
            self.setFocus()
        elif event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() in (
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            self.tables.move_entry(self.index, self.index + (-1 if event.key() == Qt.Key.Key_Up else 1))
        else:
            super().keyPressEvent(event)


class Tables(QWidget):
    """
    A list of tables with texts and numbers (e.g. the choices of a strip): an entry for each that opens into its
    fields, a button to add one. Entries are dragged (or Ctrl+Up/Down) into their order. A `Suggest` is for the value:
    the first text column without a length limit (a label has one); a `TableSuggest` names the columns, which get the
    other values of their entry (e.g. the profiles of its card).
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
        self.entries: list[Entry] = []
        self.opened: int | None = None
        """The entry whose fields show."""
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Space.XS)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(Space.XS)
        layout.addLayout(self.rows)
        self.add_button = QPushButton("Add", self)
        set_icon(self.add_button, "plus")
        self.add_button.clicked.connect(self.add)
        add = QHBoxLayout()
        add.addWidget(self.add_button)
        add.addStretch()
        layout.addLayout(add)

    # -- what the columns know ------------------------------------------------------------------------------------

    def suggest_for(self, index: int, name: str) -> Suggest | None:
        """The suggestions of a column of an entry, given the other values of the entry; None without any."""
        column_suggest = self._suggest.get(name)
        if column_suggest is None:
            return None
        return lambda: column_suggest(self.values[index])

    def describe(self, index: int, name: str) -> str:
        """A value of an entry for people: what the sound server says it is (a device by its description), or it."""
        value = str(self.values[index].get(name, ""))
        suggest = self.suggest_for(index, name)
        found: Suggestion | None = next(
            (suggestion for suggestion in (suggest() if suggest else ()) if suggestion.value == value), None
        )
        if found is None or not found.detail:
            return value
        # "Analog Stereo Output (active)", "Family 17h HD Audio, alsa_output...": what it is, not its state now
        return found.detail.split(" (")[0].split(", ")[0]

    # -- showing --------------------------------------------------------------------------------------------------

    def show_values(self, values: list[dict[str, str | int]]) -> None:
        self.values = [dict(value) for value in values]
        for entry in self.entries:
            self.rows.removeWidget(entry)
            entry.hide()
            entry.deleteLater()
        self.entries = [Entry(self, index) for index in range(len(self.values))]
        for entry in self.entries:
            self.rows.addWidget(entry)
        if self.opened is not None and self.opened >= len(self.entries):
            self.opened = None
        if self.opened is not None:
            self.entries[self.opened].set_open(True)

    def open(self, index: int | None) -> None:
        """Shows the fields of one entry (None: of none); the one open before closes."""
        if self.opened is not None and self.opened < len(self.entries):
            self.entries[self.opened].set_open(False)
        self.opened = index
        if index is not None:
            self.entries[index].set_open(True)

    # -- editing --------------------------------------------------------------------------------------------------

    def put(self, index: int, name: str, value: Any) -> None:
        if value is None:
            # a missing value: its problem says if it is required
            self.values[index].pop(name, None)
        else:
            self.values[index][name] = value
        self.entries[index].show_summary()
        self._changed()

    def _changed(self) -> None:
        self.changed.emit([dict(value) for value in self.values])

    def add(self) -> None:
        # an entry with nothing in it is not the document's yet: its first value is (no "required" before one is typed)
        self.show_values([*self.values, {}])
        self.open(len(self.entries) - 1)
        self.entries[-1].focus_first()

    def remove(self, index: int) -> None:
        if self.opened == index:
            self.opened = None
        elif self.opened is not None and self.opened > index:
            self.opened -= 1
        self.show_values(self.values[:index] + self.values[index + 1 :])
        self._changed()

    def move_entry(self, index: int, to: int) -> None:
        """Moves an entry to another place in the list; the open one stays open."""
        if not 0 <= to < len(self.values) or to == index:
            return
        values = list(self.values)
        opened = None if self.opened is None else values[self.opened]
        values.insert(to, values.pop(index))
        self.opened = None if opened is None else next(i for i, value in enumerate(values) if value is opened)
        self.show_values(values)
        self._changed()
        self.entries[to].setFocus()

    def _dragged(self, event: QDragEnterEvent | QDragMoveEvent) -> None:
        mime = event.mimeData()
        if mime is not None and mime.hasFormat(MIME) and event.source() in [entry.handle for entry in self.entries]:
            event.acceptProposedAction()

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        assert event is not None
        self._dragged(event)

    def dragMoveEvent(self, event: QDragMoveEvent | None) -> None:
        assert event is not None
        self._dragged(event)

    def dropEvent(self, event: QDropEvent | None) -> None:
        assert event is not None
        mime = event.mimeData()
        assert mime is not None
        index = int(bytes(mime.data(MIME).data()).decode())
        y = event.position().y()
        # before the first entry whose middle is below the drop
        to = next((i for i, entry in enumerate(self.entries) if y < entry.geometry().center().y()), len(self.entries))
        self.move_entry(index, to - 1 if to > index else to)
        event.acceptProposedAction()
