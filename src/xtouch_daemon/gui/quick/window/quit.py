"""Ctrl+C and SIGTERM close the window of the application, which asks about unsaved changes."""

import signal
from collections.abc import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication

SIGNAL_CHECK_MS = 200
"""How often the event loop looks for Ctrl+C or SIGTERM."""


class QuitWindows:
    """
    Ctrl+C and SIGTERM close the windows, which ask about unsaved changes. The handler only notes the signal: Python
    runs it between any two bytecodes, e.g. in a paint or in the middle of building the window, where closing would
    break what runs. A timer of the event loop closes the windows after it, unless a question of the window waits for
    its answer already; Python runs handlers only between bytecodes and the loop runs in C++, so the timer also lets
    the handler run at all.
    """

    def __init__(self) -> None:
        self.asked = False
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, self._note)

    def _note(self, signum: int, frame: object) -> None:
        self.asked = True

    def watch_windows(self, app: QGuiApplication, asking: Callable[[], bool]) -> QTimer:
        """
        Closes the windows of `app` after a signal; `asking` says whether a dialog of the window asks already. The
        timer that does it runs for as long as `app` does.
        """
        timer = QTimer(app)
        timer.timeout.connect(lambda: self._close(app, asking))
        timer.start(SIGNAL_CHECK_MS)
        return timer

    def _close(self, app: QGuiApplication, asking: Callable[[], bool]) -> None:
        if not self.asked:
            return
        self.asked = False
        if asking():
            # the dialog asks already, e.g. about unsaved changes while closing: it is the answer
            return
        windows = app.topLevelWindows()
        for window in windows:
            window.close()
        # a window that stays asks about its unsaved changes: the next check leaves it that question
        self.asked = any(window.isVisible() for window in windows)
