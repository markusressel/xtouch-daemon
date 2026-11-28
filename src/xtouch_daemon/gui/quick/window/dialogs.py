"""
The questions and notes of the window, inside it (`DialogHost.qml`): a card over a dimmed window with a text and
buttons, never a window of its own.

`Dialogs.ask()` returns the id of the button pressed. While it waits the event loop keeps running (as `QMessageBox.exec`
does), so the code that asks stays one function: save, ask about overwriting, save again. Tests give the window a fake
with the same methods (`tests/support/dialogs.py`): it answers at once and records what it was asked.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from PyQt6.QtCore import QEventLoop, QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

SAVE, DISCARD, CANCEL, YES, NO, OK = "save", "discard", "cancel", "yes", "no", "ok"
OVERWRITE, RELOAD = "overwrite", "reload"


@dataclass(frozen=True)
class Button:
    id: str
    text: str
    role: str = "plain"
    """`accept` (the one to press: highlighted), `destroy` (drops something), `reject` (what Esc does), or `plain`."""


SAVE_DISCARD_CANCEL = (
    Button(SAVE, "Save", "accept"),
    Button(DISCARD, "Discard", "destroy"),
    Button(CANCEL, "Cancel", "reject"),
)
YES_NO = (Button(YES, "Yes", "accept"), Button(NO, "No", "reject"))
OVERWRITE_RELOAD_CANCEL = (
    Button(OVERWRITE, "Overwrite", "accept"),
    Button(RELOAD, "Reload", "destroy"),
    Button(CANCEL, "Cancel", "reject"),
)


class Asker(Protocol):
    """What the window needs of its dialogs (the real ones and the fakes of the tests)."""

    def ask(self, title: str, text: str, buttons: Sequence[Button]) -> str: ...

    def tell(self, title: str, text: str) -> None: ...


class Dialogs(QObject):
    """The dialog of the window: one at a time, a question with buttons or a note with Ok."""

    changed = pyqtSignal(arguments=[])

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self._title = ""
        self._text = ""
        self._buttons: list[Button] = []
        self._open = False
        self._cancel = CANCEL
        self._waiting: tuple[QEventLoop, list[str]] | None = None
        """The loop of the question that waits, and where its answer goes (a question has its own)."""

    @pyqtProperty(str, notify=changed)
    def title(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._title

    @pyqtProperty(str, notify=changed)
    def text(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._text

    @pyqtProperty("QVariantList", notify=changed)
    def buttons(self) -> list[dict[str, Any]]:  # pyright: ignore[reportRedeclaration]
        return [{"id": b.id, "text": b.text, "role": b.role} for b in self._buttons]

    @pyqtProperty(bool, notify=changed)
    def isOpen(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._open

    def ask(self, title: str, text: str, buttons: Sequence[Button]) -> str:
        """Shows a question and returns the id of the button pressed (Esc: the one that rejects)."""
        if self._open:
            # a question while one waits: the old one is answered with its rejecting button first
            self.answer(self._cancel)
        self._title, self._text, self._buttons, self._open = title, text, list(buttons), True
        reject = next((b.id for b in buttons if b.role == "reject"), None)
        self._cancel = reject if reject is not None else buttons[-1].id
        self.changed.emit()
        loop, answer = QEventLoop(), []
        self._waiting = loop, answer
        loop.exec()
        return answer[0]

    def tell(self, title: str, text: str) -> None:
        """Shows a note with Ok."""
        self.ask(title, text, (Button(OK, "Ok", "accept"),))

    @pyqtSlot(str)
    def answer(self, button: str) -> None:
        """QML: a button was pressed."""
        if not self._open:
            return
        self._open = False
        self.changed.emit()
        if self._waiting is not None:
            loop, answer = self._waiting
            answer.append(button)
            self._waiting = None
            loop.quit()

    @pyqtSlot()
    def reject(self) -> None:
        """QML: Esc."""
        self.answer(self._cancel)
