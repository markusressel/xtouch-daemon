"""
The one source of truth of the window: the document being edited, its undo history and its validation. Views read
from here and change the document through here; the signal tells them what changed, so each one updates what it
shows in place (see docs/development/architecture/gui.md).
"""

from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from xtouch_daemon.gui.domain.changes import EVERYTHING, Change, Scope
from xtouch_daemon.gui.domain.channels import CHANNEL_TYPES, free_id
from xtouch_daemon.gui.domain.history import History
from xtouch_daemon.gui.domain.slots_document import OptionPath, SlotsDocument, Validation


class Editor(QObject):
    changed = pyqtSignal(object, arguments=["change"])
    """The document changed (a `Change`), and `validation` already says what that means."""

    def __init__(self, document: SlotsDocument, history: History[SlotsDocument] | None = None):
        super().__init__()
        self.document = document
        self.history = history if history is not None else History(document)
        self.validation: Validation = document.validate()

    def edited(self, change: Change = EVERYTHING) -> None:
        """After an edit of the document: a step to undo, the new validation, and the views show it."""
        self.history.record()
        self._show(change)

    def _show(self, change: Change) -> None:
        self.validation = self.document.validate()
        self.changed.emit(change)

    # -- edits that change more than a value ----------------------------------------------------------------------

    def add_section(self, name: str) -> None:
        self.document.add_section(name)
        self.edited(Change(Scope.SECTION, (name,)))

    def remove_section(self, name: str) -> None:
        self.document.remove_section(name)
        self.edited(Change(Scope.SECTION, (name,)))

    def unset(self, path: OptionPath) -> None:
        """Removes an option, e.g. an unknown one from the list of problems: no field made that change."""
        self.document.unset(path)
        self.edited()

    def add_channel(self, channel_type: str, options: dict[str, Any] | None = None) -> str:
        """Adds a channel of the type, with an id after it and these options; returns the id."""
        name = free_id(self.document.get(("channel",), {}), CHANNEL_TYPES[channel_type].strip)
        self.document.set(("channel", name), {"type": channel_type, **(options or {})})
        self.edited(Change(Scope.CHANNELS))
        return name

    def duplicate_channel(self, name: str) -> str:
        """Adds a copy of a channel, with an id after it; returns the id."""
        channels: dict[str, Any] = self.document.get(("channel",))
        copy = free_id(channels, name)
        self.document.set(("channel", copy), channels[name])
        self.edited(Change(Scope.CHANNELS))
        return copy

    def remove_channel(self, name: str) -> None:
        self.document.unset(("channel", name))
        self.edited(Change(Scope.CHANNELS))

    def rename_channel(self, name: str, new: str) -> None:
        """Another id for a channel; the stacks, pools and states that name it are the user's to change."""
        self.document.rename(("channel", name), new)
        self.edited(Change(Scope.CHANNELS))

    def add_state(self, mode: bool, name: str | None = None, options: dict[str, Any] | None = None) -> str:
        """Adds a state (or a mode) with an id after `name` (default: its kind) and these options; returns the id."""
        name = free_id(self.document.get(("state",), {}), name or ("mode" if mode else "state"))
        self.document.set(("state", name), {**({"mode": True} if mode else {}), **(options or {})})
        self.edited(Change(Scope.STATES))
        return name

    def remove_state(self, name: str) -> None:
        self.document.unset(("state", name))
        self.edited(Change(Scope.STATES))

    def rename_state(self, name: str, new: str) -> None:
        """Another id for a state; the conditions that name it are the user's to change."""
        self.document.rename(("state", name), new)
        self.edited(Change(Scope.STATES))

    def move_slot(self, source: int, target: int) -> None:
        """Moves a slot with its candidates and controls; the slots between make room (see `move_slot`)."""
        self.document.move_slot(source, target)
        self.edited()

    # -- history and the file -------------------------------------------------------------------------------------

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
