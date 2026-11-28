"""What the pages Channels and States share: the id of an entry, the clipboard and the share of their panes."""

import re

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtGui import QGuiApplication

from xtouch_daemon.gui.qt.theme.settings import load_split, save_split

ID = re.compile(r"[a-z0-9_]+")
"""What a channel, a pool or a state can be called."""
LEFT_SHARE = 0.3
"""The share of the width the list has until the handle is dragged: most of it is for what is picked."""
NO_ID = "{!r} can't be the id: lowercase letters, digits and _, and not taken"


def clipboard_text() -> str:
    board = QGuiApplication.clipboard()
    return board.text() if board is not None else ""


def set_clipboard_text(text: str) -> None:
    board = QGuiApplication.clipboard()
    if board is not None:
        board.setText(text)


class PaneShare(QObject):
    """The share of the width the list of a page has, kept for the next start (once the handle is let go)."""

    shareChanged = pyqtSignal(arguments=[])

    def __init__(self, name: str, parent: QObject) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.name = name
        self._share = load_split(name) or LEFT_SHARE

    @pyqtProperty(float, notify=shareChanged)
    def share(self) -> float:  # pyright: ignore[reportRedeclaration]
        return self._share

    @share.setter
    def share(self, share: float) -> None:
        if 0 < share < 1 and share != self._share:
            self._share = share
            self.shareChanged.emit()

    @pyqtSlot()
    def keep(self) -> None:
        """The handle was let go: the share stays for the next start (not on every move: writing it is slow)."""
        save_split(self.name, self._share)
