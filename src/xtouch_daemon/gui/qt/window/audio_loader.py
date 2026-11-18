"""
Reading the sound server in a thread, so a slow or missing one does not block the window.
"""

import contextlib
import threading
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.audio.pulse import SoundServerError


class AudioLoader(QObject):
    """Reads the sound server in a thread, so a slow or missing one does not block the window."""

    loaded = pyqtSignal(object, arguments=["state"])
    failed = pyqtSignal(str, arguments=["message"])

    def __init__(self, read: Callable[[], AudioState]):
        super().__init__()
        self._read = read

    def load(self) -> None:
        threading.Thread(target=self._run, name="sound server", daemon=True).start()

    def _run(self) -> None:
        try:
            state = self._read()
        except SoundServerError as e:
            self._emit(self.failed, str(e))
        else:
            self._emit(self.loaded, state)

    @staticmethod
    def _emit(signal: Any, value: object) -> None:
        # the window may be gone meanwhile, e.g. for a new zoom
        with contextlib.suppress(RuntimeError):
            signal.emit(value)
