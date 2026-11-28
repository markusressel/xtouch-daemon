"""
What every page has for the window: the Edit menu works on the entry of a page's list (`editable`, `edit`), and the
window can show an option of the page (`reveal`, e.g. from the list of problems).
"""

from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.app import App

EDIT_ACTIONS = ("cut", "copy", "paste", "duplicate", "remove", "rename")
"""What the Edit menu does to the entry picked in a page's list (Ctrl+X, C, V, D, Delete, F2)."""


class PageBackend(QObject):
    editableChanged = pyqtSignal(arguments=[])

    def __init__(self, app: App) -> None:
        super().__init__(app)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.app = app

    @pyqtProperty("QStringList", notify=editableChanged)
    def editable(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        """The actions of `EDIT_ACTIONS` the Edit menu can do now (while the page's list has the focus)."""
        return []

    @pyqtSlot(str)
    def edit(self, action: str) -> None:
        """Does an action of `EDIT_ACTIONS` to the entry picked in the page's list."""

    @pyqtSlot("QVariantList")
    def reveal(self, path: list[str]) -> None:
        """Shows the option at `path` of the document (e.g. `["channel", "mic", "color"]`) and gives it the focus."""
