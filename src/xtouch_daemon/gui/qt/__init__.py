"""The Qt widgets of the GUI, and starting it."""

import gc
import os
import signal
import sys
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QTimer
from PyQt6.QtWidgets import QApplication

from xtouch_daemon.audio.pulse import read_state
from xtouch_daemon.gui.domain.slots_document import SlotsDocument
from xtouch_daemon.gui.qt import errors
from xtouch_daemon.gui.qt.fields.rich_tips import RichTips
from xtouch_daemon.gui.qt.theme.icons import app_icon
from xtouch_daemon.gui.qt.theme.settings import load_zoom
from xtouch_daemon.gui.qt.theme.style import apply_theme, load_theme_mode
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.gui.qt.window.session import Session
from xtouch_daemon.system.systemd import Service

SCALE_FACTOR = "QT_SCALE_FACTOR"
"""Qt scales a whole application by it, when the application starts."""


def name_application() -> None:
    """QSettings (the theme, the zoom) go to ~/.config/xtouch-daemon/xtouch-daemon-gui.conf."""
    QCoreApplication.setOrganizationName("xtouch-daemon")
    QCoreApplication.setApplicationName("xtouch-daemon-gui")


def scale_for(zoom: float, own: str | None) -> str:
    """The QT_SCALE_FACTOR for a zoom, on top of the one the user set (`own`)."""
    try:
        base = float(own) if own else 1.0
    except ValueError:
        base = 1.0
    return f"{base * zoom:g}"


_rich_tips: RichTips | None = None
"""The tooltips in the colors of the help, for as long as the application runs."""


def create_application() -> QApplication:
    name_application()
    app = QApplication(sys.argv[:1])
    app.setApplicationDisplayName("X-Touch Extender")
    # Wayland finds the icon of the window by it: packaging/xtouch-daemon-gui.desktop
    app.setDesktopFileName("xtouch-daemon-gui")
    # X11 and the task bars that don't read the desktop file
    app.setWindowIcon(app_icon())
    apply_theme(load_theme_mode())
    global _rich_tips
    _rich_tips = RichTips()
    return app


def run_gui(path: Path) -> int:
    """Shows the window until it is closed; raises `ConfigError` for a file it can't edit."""
    errors.install()
    # before anything of Qt: Python's handler would raise KeyboardInterrupt in whatever runs, also in a method Qt calls
    signals = QuitSignals()
    document = SlotsDocument.open(path)
    own = os.environ.get(SCALE_FACTOR)
    session: Session | None = None
    while True:
        name_application()
        os.environ[SCALE_FACTOR] = scale_for(load_zoom(), own)
        app = create_application()
        signals.watch(app)
        window = MainWindow(document, Service(wait=False), lambda: read_state("xtouch-daemon-gui"), session=session)
        window.show()
        code = app.exec()
        if window.rezoom is None:
            return code
        # a new zoom: a new application at the new scale goes on where this one is
        session = window.session()
        # Qt allows one application at a time: this one goes before the next one starts (the handlers of the signals
        # and their timer still refer to it)
        sip.delete(window)
        sip.delete(app)
        gc.collect()


SIGNAL_CHECK_MS = 200
"""How often the event loop looks for Ctrl+C or SIGTERM (see `QuitSignals`)."""


class QuitSignals:
    """
    Ctrl+C and SIGTERM close the windows, which ask about unsaved changes. The handler only notes the signal: Python
    runs it between any two bytecodes, e.g. in a paint or in the middle of building the window, where closing would
    break what runs. A timer of the event loop closes the windows; Python runs handlers only between bytecodes and
    the loop runs in C++, so the timer also lets the handler run at all.
    """

    def __init__(self) -> None:
        self.asked = False
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, self._note)

    def _note(self, signum: int, frame: object) -> None:
        self.asked = True

    def watch(self, app: QApplication) -> None:
        """Closes the windows of `app` after a signal, from its event loop (each zoom has an application of its own)."""
        timer = QTimer(app)
        timer.timeout.connect(lambda: self._check(app))
        timer.start(SIGNAL_CHECK_MS)

    def _check(self, app: QApplication) -> None:
        if not self.asked:
            return
        self.asked = False
        if app.activeModalWidget() is not None:
            # a dialog asks already, e.g. about unsaved changes while closing: it is the answer
            return
        app.closeAllWindows()
