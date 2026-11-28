"""
The rows of a form for QML: a list whose rows have a `spec` (what the option is: it stays while the row is there) and
an `info` (what it shows now: value, placeholder, problems). A delegate reads them as `spec` and `info`, so a new
value changes the bindings on `info` only, and what the columns of a table or a binding are is never made anew by one.
"""

import dataclasses
import difflib
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from PyQt6.QtCore import (  # pyright: ignore[reportUnknownVariableType]
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    pyqtProperty,
    pyqtSignal,
)

from xtouch_daemon.config.bindings import ServiceAction
from xtouch_daemon.gui.domain.schema import Kind, Option, options
from xtouch_daemon.gui.quick.forms.entity_table import sets_value
from xtouch_daemon.gui.quick.forms.tables import folds

KEY = Qt.ItemDataRole.UserRole + 1
SPEC = Qt.ItemDataRole.UserRole + 2
STATE = Qt.ItemDataRole.UserRole + 3
NO_PARENT = QModelIndex()

type Row = tuple[str, Mapping[str, Any], Mapping[str, Any]]


def plain(value: Any) -> Any:
    """A value of the file as QML takes it: lists and maps of plain values (no tuples, paths or enums)."""
    match value:
        case Mapping():
            return {str(key): plain(item) for key, item in value.items()}  # pyright: ignore[reportUnknownVariableType]
        case list() | tuple() | set() | frozenset():
            return [plain(item) for item in value]  # pyright: ignore[reportUnknownVariableType]
        case Enum():
            return value.value
        case Path():
            return str(value)
        case _:
            return value


def table_model(option: Option) -> tuple[type[BaseModel], str] | None:
    """The model of the table below a field and what marks it (`entity`, `service`): of an entity or a service."""
    if option.kind == Kind.ACTION:
        return ServiceAction, "service"
    return (option.entity, "entity") if option.entity is not None else None


def table_columns(option: Option) -> tuple[Option, ...]:
    """The options of the table of an entity or a service (`entity`, `attribute`, `min`, ...), none without one."""
    found = table_model(option)
    if found is None:
        return ()
    return tuple(
        dataclasses.replace(column, signed=True) if column.kind == Kind.NUMBER else column
        for column in options(found[0], skip=("push",) if option.name == "fader" else ())
    )


def spec_of(option: Option) -> dict[str, Any]:
    """What an option is, for QML (its columns too)."""
    return {
        "name": option.name,
        "title": option.title,
        "kind": option.kind.name.lower(),
        "help": option.help,
        "required": option.required,
        "default": plain(option.default),
        "defaultText": option.default_text,
        "choices": [str(choice) for choice in option.choices],
        "meanings": dict(option.meanings),
        "minimum": option.minimum,
        "maximum": option.maximum,
        "maxLength": option.max_length,
        "columns": [spec_of(column) for column in option.columns],
        "presets": str(option.presets.value if isinstance(option.presets, Enum) else option.presets or ""),
        "base": option.base.name.lower() if option.base is not None else "",
        "homeAssistant": option.home_assistant,
        "binding": option.binding,
        "channel": option.channel,
        "entity": option.entity is not None,
        "tableColumns": [spec_of(column) for column in table_columns(option)],
        "tableMarker": found[1] if (found := table_model(option)) is not None else "",
        "tableSets": sets_value(found[0] if found is not None else None) if (found := table_model(option)) else False,
        "tableHelp": " ".join(((found[0].__doc__ or "") if (found := table_model(option)) else "").split()),
        "folds": folds(option.columns),
        "signed": option.signed,
        "percent": option.name.endswith("_volume"),
    }


class FormRowsModel(QAbstractListModel):
    """See the module. `show(rows)`: rows by key; a row that stays changes in place."""

    countChanged = pyqtSignal(arguments=[])

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.rows: list[Row] = []

    @pyqtProperty(int, notify=countChanged)
    def count(self) -> int:  # pyright: ignore[reportRedeclaration]
        return len(self.rows)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def roleNames(self) -> dict[int, QByteArray]:
        return {KEY: QByteArray(b"key"), SPEC: QByteArray(b"spec"), STATE: QByteArray(b"info")}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        key, spec, state = self.rows[index.row()]
        return {KEY: key, SPEC: dict(spec), STATE: dict(state)}.get(role)

    def keys(self) -> list[str]:
        return [key for key, _, _ in self.rows]

    def state(self, key: str) -> Mapping[str, Any] | None:
        return next((state for each, _, state in self.rows if each == key), None)

    def show(self, rows: Sequence[Row]) -> None:
        before = len(self.rows)
        new = [key for key, _, _ in rows]
        offset = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=self.keys(), b=new, autojunk=False).get_opcodes():
            if tag == "equal":
                for step in range(i2 - i1):
                    at = i1 + offset + step
                    _, spec, state = self.rows[at]
                    _, new_spec, new_state = rows[j1 + step]
                    roles = [*([SPEC] if spec != new_spec else []), *([STATE] if state != new_state else [])]
                    if roles:
                        self.rows[at] = rows[j1 + step]
                        self.dataChanged.emit(self.index(at), self.index(at), roles)
                continue
            at = i1 + offset
            if i2 > i1:
                self.beginRemoveRows(QModelIndex(), at, at + i2 - i1 - 1)
                del self.rows[at : at + i2 - i1]
                self.endRemoveRows()
            if j2 > j1:
                self.beginInsertRows(QModelIndex(), at, at + j2 - j1 - 1)
                self.rows[at:at] = list(rows[j1:j2])
                self.endInsertRows()
            offset += (j2 - j1) - (i2 - i1)
        if len(self.rows) != before:
            self.countChanged.emit()
