"""
The one source of truth of the window: the document being edited, its undo history, its validation, and which strip is
selected. Views read from here and change the document through here; the signals tell them what changed, so each one
updates what it shows in place (see the GUI section of docs/architecture.md).
"""

from PyQt6.QtCore import QObject, pyqtSignal

from xtouch_daemon.gui.domain.changes import EVERYTHING, Change, Scope
from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.domain.drafts import Validation
from xtouch_daemon.gui.domain.history import History
from xtouch_daemon.hardware import protocol


class Editor(QObject):
    changed = pyqtSignal(object, arguments=["change"])
    """The document changed (a `Change`), and `validation` already says what that means."""
    selected = pyqtSignal(int, arguments=["index"])
    """Another strip is selected. Selecting changes nothing in the document, so nothing is validated or built again."""

    def __init__(self, document: ConfigDocument, history: History | None = None):
        super().__init__()
        self.document = document
        self.history = history if history is not None else History(document)
        self.validation: Validation = document.validate()
        self.selection = 0
        """The strip whose options the editor shows."""

    # -- what changed ---------------------------------------------------------------------------------------------

    def edited(self, change: Change = EVERYTHING) -> None:
        """After an edit of the document: a step to undo, the new validation, and the views show it."""
        self.history.record()
        self._show(change)

    def _show(self, change: Change) -> None:
        self.validation = self.document.validate()
        # the selected strip beyond the 8 of the device is gone (removed, undone): the last one there is
        gone = self.selection > self._last
        if gone:
            self.selection = self._last
        self.changed.emit(change)
        if gone:
            self.selected.emit(self.selection)

    @property
    def _last(self) -> int:
        """The last strip that can be selected: one of the device's 8, or one of the layout beyond them."""
        return max(protocol.STRIPS, len(self.document.strips)) - 1

    def select(self, index: int) -> None:
        index = max(0, min(index, self._last))
        if index != self.selection:
            self.selection = index
            self.selected.emit(index)

    # -- edits that change more than a value ----------------------------------------------------------------------

    def set_strip_type(self, index: int, strip_type: str) -> None:
        self.document.set_strip_type(index, strip_type)
        self.edited(Change(Scope.STRIPS))

    def configure_up_to(self, index: int) -> None:
        self.document.configure_up_to(index)
        self.edited(Change(Scope.STRIPS))
        self.select(index)

    def add_strip(self) -> None:
        """Adds an `auto` strip at the end and selects it (see `ConfigDocument.add_strip()`)."""
        index = self.document.add_strip()
        self.edited(Change(Scope.STRIPS))
        self.select(index)

    def move_strip(self, index: int, to: int) -> None:
        self.document.move_strip(index, to)
        self.edited(Change(Scope.STRIPS))
        self.select(to)

    def remove_strip(self, index: int) -> None:
        self.document.remove_strip(index)
        self.edited(Change(Scope.STRIPS))

    def add_section(self, name: str) -> None:
        self.document.add_section(name)
        self.edited(Change(Scope.SECTION, (name,)))

    def remove_section(self, name: str) -> None:
        self.document.remove_section(name)
        self.edited(Change(Scope.SECTION, (name,)))

    def unset(self, path: tuple[str | int, ...]) -> None:
        """Removes an option, e.g. an unknown one from the list of problems: no field made that change."""
        self.document.unset(path)
        self.edited()

    def edit_layout(self, index: int | None) -> None:
        """Shows the strips of another layout (an index of the layouts, None for the default one)."""
        if index != self.document.layout:
            self.document.edit_layout(index)
            self._show(Change(Scope.LAYOUTS))

    def add_layout(self, copy_strips: bool) -> None:
        self.document.add_layout(copy_strips)
        self.edited(Change(Scope.LAYOUTS))

    def remove_layout(self) -> None:
        assert self.document.layout is not None
        # the default layout is edited then
        self.document.remove_layout(self.document.layout)
        self.edited(Change(Scope.LAYOUTS))

    def move_layout(self, to: int) -> None:
        assert self.document.layout is not None
        # it stays the one being edited
        self.document.move_layout(self.document.layout, to)
        self.edited(Change(Scope.LAYOUTS))

    def undo(self) -> bool:
        if not self.history.can_undo:
            return False
        self.history.undo()
        self._show(EVERYTHING)
        return True

    def redo(self) -> bool:
        if not self.history.can_redo:
            return False
        self.history.redo()
        self._show(EVERYTHING)
        return True

    def revert(self) -> None:
        self.document.revert()
        self.edited()

    def saved(self) -> None:
        """The file was written: the document is the same, only whether it differs from the file changed."""
        self._show(Change(Scope.FILE))
