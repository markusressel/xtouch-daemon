"""The page Slots: its backend for QML (a stub of the foundation)."""

from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon.gui.quick.pages.base import PageBackend


class SlotsPage(PageBackend):
    slotChanged = pyqtSignal(arguments=[])

    _slot = 0

    @pyqtProperty(int, notify=slotChanged)
    def slot(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The slot picked (1..8), 0 for none: the drawing of the device marks its strip."""
        return self._slot

    @pyqtSlot(int)
    def selectSlot(self, slot: int) -> None:
        """Picks a slot (0: none), e.g. after a click on its strip in the drawing of the device."""
        if slot != self._slot:
            self._slot = slot
            self.slotChanged.emit()
