"""Ctrl+C and SIGTERM close the window of the application in Qt Quick, which asks about unsaved changes."""

from collections.abc import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication

from xtouch_daemon.gui.qt import SIGNAL_CHECK_MS, QuitSignals


class QuitWindows(QuitSignals):
    """
    The signals of `QuitSignals` (they only note that one came), and a timer of the event loop that closes the
    windows of a `QGuiApplication` after it, unless a question of the window waits for its answer already.
    """

    def watch_windows(self, app: QGuiApplication, asking: Callable[[], bool]) -> None:
        """Closes the windows of `app` after a signal; `asking` says whether a dialog of the window asks already."""
        timer = QTimer(app)
        timer.timeout.connect(lambda: self._close(app, asking))
        timer.start(SIGNAL_CHECK_MS)

    def _close(self, app: QGuiApplication, asking: Callable[[], bool]) -> None:
        if not self.asked:
            return
        self.asked = False
        if asking():
            # the dialog asks already, e.g. about unsaved changes while closing: it is the answer
            return
        for window in app.topLevelWindows():
            window.close()
