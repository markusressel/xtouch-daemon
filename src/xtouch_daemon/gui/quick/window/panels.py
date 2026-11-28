"""
Where the panels of the window are: the Device above the configuration at first, the Log under it (hidden at first).
Each can go to any side of the configuration, or into a window of its own (a `Window` of QML, not a popup), and
the window remembers it. The configuration is what the window edits: it stays and takes the room that is left.
"""

from PyQt6.QtCore import QObject, QSettings, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

PLACES = ("top", "bottom", "left", "right", "window")
"""Where a panel can be: at a side of the configuration, or in a window of its own."""
PLACE_TITLES = {
    "top": "Above",
    "bottom": "Under",
    "left": "At the left",
    "right": "At the right",
    "window": "In a window",
}
"""How the View menu names the places."""
DEVICE_SIZE = 380
"""The height of the Device above the configuration until it is made larger or smaller."""
LOG_SIZE = 220
SIZES = {"device": DEVICE_SIZE, "log": LOG_SIZE}
MINIMUM = 40
"""The smallest extent a panel is kept at: its bar and a line."""


class Panel(QObject):
    """One panel: whether it shows, at which side (or in a window of its own), and how large."""

    changed = pyqtSignal(arguments=[])

    def __init__(self, name: str, title: str, place: str, shown: bool, parent: QObject | None = None) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.name = name
        self._title = title
        settings = QSettings()
        stored = settings.value(self._key("place"), place)
        self._place = stored if stored in PLACES else place
        self._shown = settings.value(self._key("shown"), shown, type=bool) is True
        size = settings.value(self._key("size"), SIZES[name])
        try:
            self._size = max(MINIMUM, int(size))  # pyright: ignore[reportArgumentType]
        except TypeError, ValueError:
            self._size = SIZES[name]

    def _key(self, field: str) -> str:
        return f"panels/{self.name}/{field}"

    @pyqtProperty(str, constant=True)
    def title(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._title

    @pyqtProperty(str, notify=changed)
    def place(self) -> str:  # pyright: ignore[reportRedeclaration]
        """`top`, `bottom`, `left`, `right` or `window`."""
        return self._place

    @pyqtProperty(bool, notify=changed)
    def shown(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._shown

    @pyqtProperty(int, notify=changed)
    def size(self) -> int:  # pyright: ignore[reportRedeclaration]
        """Its height at the top or bottom, its width at a side (in a window: its height); kept at the end of a drag."""
        return self._size

    @pyqtSlot(str)
    def setPlace(self, place: str) -> None:
        if place in PLACES and place != self._place:
            self._place = place
            QSettings().setValue(self._key("place"), place)
            self.changed.emit()

    @pyqtSlot(bool)
    def setShown(self, shown: bool) -> None:
        if shown != self._shown:
            self._shown = shown
            QSettings().setValue(self._key("shown"), shown)
            self.changed.emit()

    @pyqtSlot()
    def toggle(self) -> None:
        self.setShown(not self._shown)

    @pyqtSlot(int)
    def setSize(self, size: int) -> None:
        """Keeps the extent the user dragged it to (not while it is dragged: settings cost time)."""
        size = max(MINIMUM, size)
        if size != self._size:
            self._size = size
            QSettings().setValue(self._key("size"), size)
            self.changed.emit()


class Panels(QObject):
    """The panels the user can move: `device` and `log`."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.device_panel = Panel("device", "Device", "top", True, self)
        self.log_panel = Panel("log", "Log", "bottom", False, self)

    @pyqtProperty(QObject, constant=True)
    def device(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self.device_panel

    @pyqtProperty(QObject, constant=True)
    def log(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self.log_panel

    @pyqtProperty("QVariantList", constant=True)
    def places(self) -> list[dict[str, str]]:  # pyright: ignore[reportRedeclaration]
        return [{"id": place, "text": PLACE_TITLES[place]} for place in PLACES]
