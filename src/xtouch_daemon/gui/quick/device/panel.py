"""The drawing of the device: its backend for QML (a stub of the foundation)."""

from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.app import App


class DevicePanel(QObject):
    def __init__(self, app: App) -> None:
        super().__init__(app)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.app = app
