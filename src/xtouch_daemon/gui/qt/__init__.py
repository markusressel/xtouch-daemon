"""The Qt widgets of the GUI, and starting it."""

import signal
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from xtouch_daemon.audio.pulse import read_state
from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.qt.theme import apply_theme, load_theme_mode
from xtouch_daemon.gui.qt.window import MainWindow
from xtouch_daemon.systemd import Service


def create_application() -> QApplication:
    app = QApplication(sys.argv[:1])
    # QSettings (the theme) go to ~/.config/xtouch-daemon/xtouch-daemon-gui.conf
    app.setOrganizationName("xtouch-daemon")
    app.setApplicationName("xtouch-daemon-gui")
    app.setApplicationDisplayName("X-Touch Extender")
    apply_theme(load_theme_mode())
    return app


def run_gui(path: Path) -> int:
    """Shows the window until it is closed; raises `ConfigError` for a file it can't edit."""
    document = ConfigDocument.open(path)
    app = create_application()
    window = MainWindow(document, Service(), lambda: read_state("xtouch-daemon-gui"))
    window.show()
    _quit_on_signals(app)
    return app.exec()


def _quit_on_signals(app: QApplication) -> None:
    """Ctrl+C and SIGTERM close the window (asking about unsaved changes)."""
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: app.closeAllWindows())
    # Python runs signal handlers only between bytecodes, and Qt's event loop runs in C++: this wakes it regularly
    timer = QTimer(app)
    timer.timeout.connect(lambda: None)
    timer.start(200)
