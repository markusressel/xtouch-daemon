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
from xtouch_daemon.gui.domain.document import ConfigDocument
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


def create_application() -> QApplication:
    name_application()
    app = QApplication(sys.argv[:1])
    app.setApplicationDisplayName("X-Touch Extender")
    # Wayland finds the icon of the window by it: packaging/xtouch-daemon-gui.desktop
    app.setDesktopFileName("xtouch-daemon-gui")
    apply_theme(load_theme_mode())
    return app


def run_gui(path: Path) -> int:
    """Shows the window until it is closed; raises `ConfigError` for a file it can't edit."""
    document = ConfigDocument.open(path)
    own = os.environ.get(SCALE_FACTOR)
    session: Session | None = None
    while True:
        name_application()
        os.environ[SCALE_FACTOR] = scale_for(load_zoom(), own)
        app = create_application()
        window = MainWindow(document, Service(), lambda: read_state("xtouch-daemon-gui"), session=session)
        window.show()
        _quit_on_signals(app)
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


def _quit_on_signals(app: QApplication) -> None:
    """Ctrl+C and SIGTERM close the window (asking about unsaved changes)."""
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: app.closeAllWindows())
    # Python runs signal handlers only between bytecodes, and Qt's event loop runs in C++: this wakes it regularly
    timer = QTimer(app)
    timer.timeout.connect(lambda: None)
    timer.start(200)
