"""
What an edit changed in the document, so that each view of the GUI updates only what it shows of it (see
docs/development/architecture/gui.md).
"""

from dataclasses import dataclass
from enum import Enum


class Scope(Enum):
    """How much of the document an edit may have changed."""

    VALUE = "value"
    """One value, in place (`Change.path`): the field that made the change shows it already."""
    CHANNELS = "channels"
    """The channels: one was added, removed, renamed or duplicated."""
    STATES = "states"
    """The states: one was added, removed or renamed."""
    SLOTS = "slots"
    """The stacks of the slots: a candidate was added, removed, moved or changed (not by a field of its options)."""
    SECTION = "section"
    """A section (`Change.path`, e.g. `("mqtt",)`) was added or removed."""
    ALIASES = "aliases"
    """The list of aliases."""
    DOCUMENT = "document"
    """Anything: undo, redo, revert, an unknown option removed through the list of problems."""
    FILE = "file"
    """Nothing in the document: the file was written, so the document is the file now."""


@dataclass(frozen=True)
class Change:
    scope: Scope = Scope.DOCUMENT
    path: tuple[str | int, ...] = ()
    """Where: the value of `VALUE`, the section of `SECTION`."""

    def touches(self, *scopes: Scope) -> bool:
        """Whether a view that shows what changes with `scopes` has to show the document again."""
        return self.scope in scopes or self.scope is Scope.DOCUMENT


EVERYTHING = Change()
