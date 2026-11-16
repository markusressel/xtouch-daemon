"""
A copied strip, to paste at another place, also of another layout: as it is, or as an `inherit` strip that refers to
it.
"""

import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any

from xtouch_daemon.config.values import DEFAULT_LAYOUT
from xtouch_daemon.gui.domain.drafts import StripDraft


class Paste(Enum):
    """How a copied strip is pasted."""

    COPY = "copy"
    """With all its options: the two strips go their own ways from then on."""
    INHERIT = "inherit"
    """As an `inherit` strip that refers to the copied one, so it changes with it."""


@dataclass(frozen=True)
class CopiedStrip:
    """A strip as it was when it was copied, and where it was."""

    layout: str
    """The name of the layout it was copied from."""
    index: int
    """Its place in that layout."""
    values: dict[str, Any]
    kept: dict[str, dict[str, Any]]
    """The options of the types it had before (see `StripDraft.kept`): a copy can switch back to them, too."""

    @classmethod
    def of(cls, layout: str, index: int, strip: StripDraft) -> CopiedStrip:
        return cls(layout, index, copy.deepcopy(strip.values), copy.deepcopy(strip.kept))

    def __str__(self) -> str:
        return f"strip {self.index + 1} of the layout {self.layout}"

    def can_inherit(self, layout: str, index: int) -> bool:
        """
        Whether the place `index` of `layout` can inherit it: only strips of a [[layout]] inherit, and not from
        themselves.
        """
        return layout != DEFAULT_LAYOUT and (layout, index) != (self.layout, self.index)

    def draft(self, paste: Paste) -> StripDraft:
        """The strip to paste."""
        if paste is Paste.INHERIT:
            return StripDraft({"type": "inherit", "layout": self.layout, "strip": self.index + 1})
        return StripDraft(copy.deepcopy(self.values), kept=copy.deepcopy(self.kept))
