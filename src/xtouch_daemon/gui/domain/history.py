"""
Undo and redo of the edits of a document. Every edit can be taken back, also removing a strip or a section, so the
editor needs no "are you sure?" questions. Typing into one option is one step, not one per character.
"""

from typing import Any

from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.domain.drafts import DocumentState

type Path = tuple[Any, ...]


def _at(data: Any, path: Path) -> Any:
    for key in path:
        data = data.get(key) if isinstance(data, dict) else data[key]
    return data


def changed_paths(before: Any, after: Any, path: Path = ()) -> set[Path]:
    """Where two states differ: the options that changed, or a whole list whose length changed."""
    if isinstance(before, dict) and isinstance(after, dict):
        return {
            changed
            for key in before.keys() | after.keys()
            for changed in changed_paths(before.get(key), after.get(key), (*path, key))
        }
    if isinstance(before, list | tuple) and isinstance(after, list | tuple) and len(before) == len(after):
        return {
            changed
            for index, (one, other) in enumerate(zip(before, after, strict=True))
            for changed in changed_paths(one, other, (*path, index))
        }
    return set() if before == after else {path}


class History:
    """The states of `document` before its edits. Call `record()` after every edit."""

    def __init__(self, document: ConfigDocument):
        self.document = document
        self._current = document.state()
        self._undo: list[DocumentState] = []
        self._redo: list[DocumentState] = []
        self._last_change: set[Path] = set()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def record(self) -> None:
        """Notes the state after an edit; another edit of the same single option joins the step before it."""
        state = self.document.state()
        change = changed_paths(self._current.data(), state.data())
        if not change:
            return
        if not (self._undo and change == self._last_change and self._one_value(change, state)):
            self._undo.append(self._current)
        self._current = state
        self._last_change = change
        self._redo.clear()

    def _one_value(self, change: set[Path], state: DocumentState) -> bool:
        """Whether the change is of a single value, like a text being typed, rather than of a list or a table."""
        if len(change) != 1:
            return False
        (path,) = change
        values = (_at(self._current.data(), path), _at(state.data(), path))
        return not any(isinstance(value, dict | list | tuple) for value in values)

    def undo(self) -> None:
        self._redo.append(self._current)
        self._go(self._undo.pop())

    def redo(self) -> None:
        self._undo.append(self._current)
        self._go(self._redo.pop())

    def _go(self, state: DocumentState) -> None:
        self._current = state
        # the next edit is a step of its own, even of the same option
        self._last_change = set()
        self.document.restore(state)
