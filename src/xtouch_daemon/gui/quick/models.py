"""
Lists for QML that change row by row: `KeyedListModel` holds rows as (key, values); `show(rows)` compares the keys
with the rows it has and tells QML which rows went, came or changed, so a delegate that stays is changed in place
(its values animate) and QML animates the ones that come and go. A delegate reads its values as `row.<name>` and its
key as `key`.
"""

import difflib
from collections.abc import Mapping, Sequence
from typing import Any

from PyQt6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    pyqtProperty,
    pyqtSignal,
)  # pyright: ignore[reportUnknownVariableType]

Row = tuple[str, Mapping[str, Any]]
NO_PARENT = QModelIndex()
KEY = Qt.ItemDataRole.UserRole + 1
VALUES = Qt.ItemDataRole.UserRole + 2


class KeyedListModel(QAbstractListModel):
    """See the module."""

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
        return {KEY: QByteArray(b"key"), VALUES: QByteArray(b"row")}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        key, values = self.rows[index.row()]
        if role == KEY:
            return key
        if role == VALUES:
            return dict(values)
        return None

    def keys(self) -> list[str]:
        return [key for key, _ in self.rows]

    def show(self, rows: Sequence[Row]) -> None:
        """The new rows: by their keys, rows go, come or change in place. Keys are unique."""
        before = len(self.rows)
        old = self.keys()
        new = [key for key, _ in rows]
        offset = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
            if tag == "equal":
                for step in range(i2 - i1):
                    at = i1 + offset + step
                    if self.rows[at] != rows[j1 + step]:
                        self.rows[at] = rows[j1 + step]
                        self.dataChanged.emit(self.index(at), self.index(at), [VALUES])
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
