"""
The parts of a configuration being edited, as plain data: the strips and layouts (with the options they keep for
other types), and the sections.
"""

from dataclasses import dataclass, field
from typing import Any

from xtouch_daemon.config.files import Problem
from xtouch_daemon.config.model import Config
from xtouch_daemon.gui.domain.schema import Section, sections

SECTIONS: dict[str, Section] = {section.name: section for section in sections()}
"""The sections with options of their own (`[device]`, `[behavior]`, `[mqtt]`), edited option by option."""

RESTART_SECTIONS: dict[str, str | None] = {"device": "name", "mqtt": None}
"""The sections a reload does not take, with the one option of them that matters (None: all of them)."""
"""What a reload does not change: the daemon keeps the device it opened, and its configuration on a new `[mqtt]`."""


type OptionPath = tuple[int | str, ...]
"""Where an option is in the TOML data, like `Problem.path`, e.g. `("strip", 2, "label")`."""


KEPT_HEADER = '# kept from type = "{type}" (the GUI restores these when the strip is switched back):'
"""
The first line of the comment that keeps the options of a type the strip had before (see `StripDraft.kept`), followed
by the options as TOML, each line commented out.
"""


@dataclass
class StripDraft:
    """A strip being edited: its options as in the file."""

    values: dict[str, Any]
    origin: int | None = None
    """Its position in the file when it was read, which keeps its comments and formatting when it moves."""
    kept: dict[str, dict[str, Any]] = field(default_factory=dict)
    """
    The options of the types the strip had before that its type does not have, by type, so switching back restores
    them. They are in the file as comments in the strip's table (`KEPT_HEADER`), which the daemon ignores.
    """
    unreadable: tuple[str, ...] = ()
    """The types whose kept options in the file are no TOML (e.g. edited by hand): they stay there as they are."""

    @property
    def type(self) -> str | None:
        return self.values.get("type")


@dataclass
class LayoutDraft:
    """A layout (`[[layout]]`) being edited: its own options as in the file, and its strips."""

    values: dict[str, Any]
    strips: list[StripDraft]
    origin: int | None = None
    """Its position in the file when it was read, which keeps its comments and formatting."""

    @property
    def name(self) -> str:
        name = self.values.get("name")
        return name if isinstance(name, str) else ""

    def data(self) -> dict[str, Any]:
        return self.values | ({"strip": [strip.values for strip in self.strips]} if self.strips else {})


@dataclass(frozen=True)
class DocumentState:
    """Everything the editor changes in a document, for undo (see `ConfigDocument.state()`)."""

    sections: dict[str, dict[str, Any] | None]
    aliases: list[tuple[str, str]]
    strips: list[StripDraft]
    extra: dict[str, Any]
    layouts: list[LayoutDraft] = field(default_factory=list[LayoutDraft])
    layout: int | None = None

    def data(self) -> dict[str, Any]:
        """What the configuration is in this state, as `ConfigDocument.data()` (to compare states)."""
        return {
            "sections": self.sections,
            "aliases": self.aliases,
            "strips": [strip.values for strip in self.strips],
            "layouts": [layout.data() for layout in self.layouts],
            "layout": self.layout,
        }


@dataclass(frozen=True)
class Validation:
    config: Config | None
    """The configuration, None while it has problems."""
    problems: list[Problem] = field(default_factory=list)

    def at(self, *path: int | str) -> list[Problem]:
        """The problems of an option, or of a section or strip and everything in it."""
        return [problem for problem in self.problems if problem.path[: len(path)] == path]
