"""
Reading the sound server in a thread, so a slow or missing one does not block the window: once, or following it.
"""

import contextlib
import logging
import threading
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.audio.pulse import SoundServerError

log = logging.getLogger(__name__)

Follow = Callable[[Callable[[AudioState], None]], None]
"""Calls its argument with the state of the sound server, then after each change of it (see `follow_state`)."""


class _Stopped(Exception):
    """Ends a `Follow`: the loader stopped."""


class AudioLoader(QObject):
    """Reads the sound server in a thread, so a slow or missing one does not block the window."""

    loaded = pyqtSignal(object, arguments=["state"])
    failed = pyqtSignal(str, arguments=["message"])

    def __init__(self, read: Callable[[], AudioState]):
        super().__init__()
        self._read = read
        self._stopped = False

    def load(self) -> None:
        threading.Thread(target=self._run, name="sound server", daemon=True).start()

    def follow(self, follow: Follow) -> None:
        """Reads the sound server again after each change of it, until `stop`."""
        threading.Thread(target=self._follow, args=(follow,), name="sound server events", daemon=True).start()

    def stop(self) -> None:
        """Ends `follow`, at the next change of the sound server."""
        self._stopped = True

    def _follow(self, follow: Follow) -> None:
        try:
            follow(self._followed)
        except _Stopped:
            pass
        except Exception:
            log.exception("Following the sound server failed")

    def _followed(self, state: AudioState) -> None:
        if self._stopped:
            raise _Stopped
        if state is DISCONNECTED:
            self._emit(self.failed, "lost the sound server (is pipewire-pulse running?), trying again")
        else:
            self._emit(self.loaded, state)

    def _run(self) -> None:
        try:
            state = self._read()
        except SoundServerError as e:
            self._emit(self.failed, str(e))
        except Exception as e:
            # the read ends with a result, whatever happens: the window would say it reads the sound server for good
            log.exception("Reading the sound server failed")
            self._emit(self.failed, f"{type(e).__name__}: {e}")
        else:
            self._emit(self.loaded, state)

    @staticmethod
    def _emit(signal: Any, value: object) -> None:
        # the window may be gone meanwhile, e.g. for a new zoom
        with contextlib.suppress(RuntimeError):
            signal.emit(value)
