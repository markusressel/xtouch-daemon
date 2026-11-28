"""
What a pill opens in full: a heading, an intro and rows (`Entry`, `Group`), each with a status, an explanation and
buttons. `Details` shows them in QML: the rows are built when the popover
opens (and again while it is open and something changes), and QML calls back by the index of a row and its button.
The popover is `DetailsPopover` of `XTouch.Controls`.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.domain.tokens import Entity
from xtouch_daemon.gui.quick.window.rich import Rich

Action = tuple[str, Callable[[], object]]


@dataclass(frozen=True)
class Entry:
    title: str
    """What the row is about, e.g. "Home Assistant"; "" for none (the popover is about one thing, its heading)."""
    status: Status | None = None
    """How it is doing, as a pill (none without a text: only the color of the bar); None for none."""
    text: str = ""
    """The explanation (the tip of the status when empty), with `code` as in the help."""
    actions: tuple[tuple[str, Callable[[], object]], ...] = ()
    """Buttons: their text and what they do (the popover closes first). The first one of a problem stands out."""
    entity: Entity | None = None
    """What the title names (a state, a channel, a slot), in its color; None for something else."""
    path: str | None = None
    """A path to show under the text, in a monospace font (its middle goes where it doesn't fit)."""
    items: tuple[tuple[str, str], ...] = ()
    """A list under the text, a line each: the item and a note on it (muted, "" for none)."""
    icon: str = ""
    """An icon before the title (an `image://icon/` name), e.g. a speaker for the outputs; "" for none."""
    toggles: tuple[tuple[str, bool, Callable[[bool], object]], ...] = ()
    """
    Switches in a row under the text: their text, whether they are on, and what a click does with the new value. Unlike
    the buttons of `actions`, they leave the popover open, so several can be switched at once.
    """


@dataclass(frozen=True)
class Group:
    """A heading between the rows of a popover: the rows after it are of another kind, e.g. states after the mode."""

    title: str
    text: str = ""
    """What the rows of the group have in common, under the title; "" for nothing."""


@dataclass(frozen=True)
class Content:
    """What a popover shows now."""

    heading: str
    entries: Sequence[Entry | Group] = ()
    intro: str = ""
    actions: Sequence[Action] = ()
    """Buttons next to the heading, which leave the popover open (e.g. to read something again)."""


class Details(QObject):
    """The rows of one popover (see the module); `build` makes them from the state of the window each time."""

    changed = pyqtSignal(arguments=[])
    openChanged = pyqtSignal(arguments=[])

    def __init__(self, build: Callable[[], Content], rich: Rich, parent: QObject | None = None) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self._build = build
        self._rich = rich
        self._open = False
        self._content = Content("")

    # -- what QML shows -------------------------------------------------------------------------------------------

    @pyqtProperty(str, notify=changed)
    def heading(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._content.heading

    @pyqtProperty(str, notify=changed)
    def intro(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._rich(self._content.intro) if self._content.intro else ""

    @pyqtProperty("QStringList", notify=changed)
    def headerActions(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        return [text for text, _ in self._content.actions]

    @pyqtProperty("QVariantList", notify=changed)
    def entries(self) -> list[dict[str, Any]]:  # pyright: ignore[reportRedeclaration]
        return [self._row(entry) for entry in self._content.entries]

    def _row(self, entry: Entry | Group) -> dict[str, Any]:
        if isinstance(entry, Group):
            return {"group": True, "title": entry.title, "text": self._rich(entry.text) if entry.text else ""}
        status = entry.status
        explanation = entry.text or (status.tip if status is not None else "")
        return {
            "group": False,
            "title": entry.title,
            "tone": status.tone.value if status is not None else Tone.NEUTRAL.value,
            "status": status.text if status is not None else "",
            "text": self._rich(explanation) if explanation else "",
            "actions": [text for text, _ in entry.actions],
            "entity": entry.entity.value if entry.entity is not None else "",
            "path": entry.path or "",
            "items": [{"item": item, "note": note} for item, note in entry.items],
            "icon": entry.icon,
            "toggles": [{"text": text, "on": on} for text, on, _ in entry.toggles],
        }

    @pyqtProperty(bool, notify=openChanged)
    def isOpen(self) -> bool:  # pyright: ignore[reportRedeclaration]
        """Whether the popover shows: QML sets it, and Python refreshes the rows only then."""
        return self._open

    @isOpen.setter
    def isOpen(self, value: bool) -> None:
        if value != self._open:
            self._open = value
            self.openChanged.emit()

    # -- QML calls ------------------------------------------------------------------------------------------------

    @pyqtSlot()
    def refresh(self) -> None:
        """Builds the rows from the state of the window now."""
        self._content = self._build()
        self.changed.emit()

    def refresh_if_open(self) -> None:
        """The state changed: the popover that is open shows it."""
        if self._open:
            self.refresh()

    @pyqtSlot(int, int)
    def run(self, row: int, action: int) -> None:
        """A button of a row (QML closes the popover first)."""
        entry = self._content.entries[row]
        assert isinstance(entry, Entry)
        entry.actions[action][1]()

    @pyqtSlot(int)
    def header(self, action: int) -> None:
        """A button next to the heading (the popover stays open)."""
        self._content.actions[action][1]()

    @pyqtSlot(int, int, bool)
    def toggle(self, row: int, toggle: int, on: bool) -> None:
        """A switch of a row (the popover stays open and shows the new state)."""
        entry = self._content.entries[row]
        assert isinstance(entry, Entry)
        entry.toggles[toggle][2](on)
        self.refresh()
