"""The cards of the page Slots for QML: a `SlotCard` per slot, with its rows in a model that moves rows too."""

from typing import Any

from PyQt6.QtCore import QModelIndex, QObject, pyqtProperty, pyqtSignal  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon.gui.quick.models import KeyedListModel


class MovableRows(KeyedListModel):
    """Rows by key that can also move one row (a candidate dragged, or moved with Ctrl+Up/Down): it slides."""

    def move(self, source: int, target: int) -> bool:
        """Moves the row at `source` to `target`; False for a move that changes nothing or leaves the rows."""
        count = len(self.rows)
        if source == target or not (0 <= source < count and 0 <= target < count):
            return False
        # Qt wants the place before which the row goes
        self.beginMoveRows(QModelIndex(), source, source, QModelIndex(), target + 1 if target > source else target)
        self.rows.insert(target, self.rows.pop(source))
        self.endMoveRows()
        return True


class SlotCard(QObject):
    """A card: its slot, its rows, which row is picked, whether the slot is picked and its problems."""

    changed = pyqtSignal(arguments=[])

    def __init__(self, number: int, parent: QObject) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self._number = number
        self.model = MovableRows(self)
        self._current = -1
        self._picked = False
        self._problem = ""
        self._candidates = 0

    @pyqtProperty(int, constant=True)
    def number(self) -> int:  # pyright: ignore[reportRedeclaration]
        return self._number

    @pyqtProperty(QObject, constant=True)
    def rows(self) -> MovableRows:  # pyright: ignore[reportRedeclaration]
        return self.model

    @pyqtProperty(int, notify=changed)
    def current(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The row picked, -1 for none."""
        return self._current

    @pyqtProperty(bool, notify=changed)
    def picked(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._picked

    @pyqtProperty(str, notify=changed)
    def problem(self) -> str:  # pyright: ignore[reportRedeclaration]
        """The problems of the slot and its controls, a line each; the card has a red outline while there are some."""
        return self._problem

    @pyqtProperty(int, notify=changed)
    def candidates(self) -> int:  # pyright: ignore[reportRedeclaration]
        """How many rows are candidates (the dark end and `auto` of an empty slot are not)."""
        return self._candidates

    def show(self, current: int, picked: bool, problem: str, candidates: int) -> None:
        state: tuple[Any, ...] = (current, picked, problem, candidates)
        if state != (self._current, self._picked, self._problem, self._candidates):
            self._current, self._picked, self._problem, self._candidates = state
            self.changed.emit()
