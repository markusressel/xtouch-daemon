"""
What an edit changed in the document, so that each view of the GUI updates only what it shows of it (see the GUI
section of docs/architecture.md).
"""

from dataclasses import dataclass
from enum import Enum


class Scope(Enum):
    """How much of the document an edit may have changed."""

    VALUE = "value"
    """One value, in place (`Change.path`): the field that made the change shows it already."""
    STRIPS = "strips"
    """The strips of the layout being edited: added, removed, moved, or of another type."""
    SECTION = "section"
    """A section (`Change.path`, e.g. `("mqtt",)`) was added or removed."""
    ALIASES = "aliases"
    """The list of aliases."""
    LAYOUTS = "layouts"
    """The layouts: one was added, removed or moved, or another one is edited, so the strips are others too."""
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

    @property
    def strips(self) -> bool:
        """Whether the strips may be others: added, moved, retyped, or those of another layout."""
        return self.touches(Scope.STRIPS, Scope.LAYOUTS)


EVERYTHING = Change()
