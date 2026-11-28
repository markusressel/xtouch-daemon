"""
The application in Qt Quick: `App`, the root object QML gets (`app` in `Main.qml`), with the editor and a backend per
part of the window; `run_quick` shows the window until it closes.

Each part of the window has a backend here and its QML in a module of its own:

| Part | Python | QML |
|---|---|---|
| The window: menus, footer, dialogs, the service, the file | `window/` (`Shell`) | `XTouch.Window` |
| The drawing of the device | `device/` (`DevicePanel`) | `XTouch.Device` |
| The forms made from the models | `forms/` | `XTouch.Forms` |
| The pages | `pages/` (`SlotsPage`, ...) | `XTouch.Pages` |
"""

import gc
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickWindow

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.gui.domain import broker
from xtouch_daemon.gui.domain.entities import Fetch
from xtouch_daemon.gui.domain.slots_document import SlotsDocument
from xtouch_daemon.gui.quick.editor import Editor
from xtouch_daemon.gui.quick.engine import make_engine
from xtouch_daemon.gui.quick.icons import app_icon
from xtouch_daemon.gui.quick.window.audio_loader import Follow
from xtouch_daemon.gui.quick.window.dialogs import Asker
from xtouch_daemon.gui.quick.window.session import Session
from xtouch_daemon.homeassistant.client import fetch
from xtouch_daemon.system import instance
from xtouch_daemon.system.instance import Instance
from xtouch_daemon.system.systemd import Service

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.window.shell import Shell

log = logging.getLogger(__name__)

SYSTEMCTL_TIMEOUT = 2.0
"""
Seconds a command of `systemctl` may take in the window, which waits for it: a user's service manager that hangs would
freeze the window (the state of the service is read every 3 s). It answers in milliseconds otherwise; the jobs are
queued (`--no-block`).
"""
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


PAGES = (
    ("slots", "Slots", "tune-vertical", "What each slot shows when"),
    ("channels", "Channels", "format-list-bulleted", "What a strip can control"),
    ("states", "States", "toggle-switch-outline", "The states and modes that decide what slots show"),
    ("settings", "Settings", "cog-outline", "The device, behavior, aliases, Home Assistant, the voice chat"),
)
"""The pages of the rail: name, title, icon, tip. Ctrl+1 shows the first one."""


@dataclass
class Dependencies:
    """What the application reaches outside of itself; tests give fakes (see `MainWindow` of the widgets)."""

    document: SlotsDocument
    service: Service
    read_audio: Callable[[], AudioState]
    find_daemon: Callable[[], Instance | None] = instance.running
    live_socket: Path | None = None
    """Where the daemon serves its live view, by default `instance.socket_file()`."""
    try_broker: broker.BrokerTest = broker.try_broker
    session: Session | None = None
    plugin_installers: Sequence[object] | None = None
    """The installers of the plugins of the voice chat clients, by default those of Mumble and TeamSpeak."""
    virtual_socket: Path | None = None
    """Where the virtual device waits for the daemon when the GUI hosts it."""
    read_entities: Fetch = fetch
    follow_audio: Follow | None = None
    dialogs: Asker | None = None
    """What asks the questions of the window; by default its own dialog (`window/dialogs.py`), tests give a fake."""
    extra: dict[str, object] = field(default_factory=dict)


class App(QObject):
    """The root of what QML shows: the editor, the page shown, and the backend of each part (see the module)."""

    pageChanged = pyqtSignal(arguments=[])

    def __init__(self, deps: Dependencies) -> None:
        super().__init__()
        # the parts import the app: imported here, so each module can be imported alone
        from xtouch_daemon.gui.quick.device.panel import DevicePanel
        from xtouch_daemon.gui.quick.pages.channels import ChannelsPage
        from xtouch_daemon.gui.quick.pages.settings import SettingsPage
        from xtouch_daemon.gui.quick.pages.slots import SlotsPage
        from xtouch_daemon.gui.quick.pages.states import StatesPage
        from xtouch_daemon.gui.quick.window.shell import Shell

        self.deps = deps
        session = deps.session
        self.editor = Editor(deps.document, session.history if session is not None else None)
        self._page = session.page if session is not None and session.page in self.page_names() else "slots"
        self._shell = Shell(self)
        self._device = DevicePanel(self)
        self._slots = SlotsPage(self)
        self._channels = ChannelsPage(self)
        self._states = StatesPage(self)
        self._settings = SettingsPage(self)

    @property
    def rezoom(self) -> float | None:
        """The zoom the next window gets, None while the window ends for good (see `run_quick`)."""
        return self._shell.rezoom

    @property
    def last_session(self) -> Session | None:
        """What the window handed to the next one when it closed for a new zoom."""
        return self._shell.last_session

    def dialogs_open(self) -> bool:
        return self._shell.dialogs.property("isOpen") is True

    @staticmethod
    def page_names() -> list[str]:
        return [name for name, *_ in PAGES]

    @pyqtProperty("QVariantList", constant=True)
    def pages(self) -> list[dict[str, str]]:  # pyright: ignore[reportRedeclaration]
        """The pages of the rail: `name`, `title`, `icon`, `tip`."""
        return [{"name": name, "title": title, "icon": icon, "tip": tip} for name, title, icon, tip in PAGES]

    @pyqtProperty(str, notify=pageChanged)
    def page(self) -> str:  # pyright: ignore[reportRedeclaration]
        """The name of the page shown."""
        return self._page

    @pyqtSlot(str)
    def showPage(self, name: str) -> None:
        if name in self.page_names() and name != self._page:
            self._page = name
            self.pageChanged.emit()

    if TYPE_CHECKING:
        shell: Shell
        """The window around the pages (QML: `app.shell`); typed as what it is, for the code and the tests."""
    else:

        @pyqtProperty(QObject, constant=True)
        def shell(self) -> QObject:
            return self._shell

    @pyqtProperty(QObject, constant=True)
    def device(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._device

    @pyqtProperty(QObject, constant=True)
    def slots(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._slots

    @pyqtProperty(QObject, constant=True)
    def channels(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._channels

    @pyqtProperty(QObject, constant=True)
    def states(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._states

    @pyqtProperty(QObject, constant=True)
    def settings(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._settings


class QmlError(RuntimeError):
    """QML that doesn't load: a mistake of ours, raised at once (tests fail on it)."""


def load_window(app: App, engine: QQmlApplicationEngine) -> QQuickWindow:
    """Loads the window (`XTouch.Window/Main.qml`) for `app` into `engine`; raises `QmlError` for QML that fails."""
    problems: list[str] = []
    engine.warnings.connect(lambda warnings: problems.extend(warning.toString() for warning in warnings))
    engine.setInitialProperties({"app": app})
    engine.loadFromModule("XTouch.Window", "Main")
    roots = engine.rootObjects()
    if not roots or problems:
        raise QmlError("\n".join(problems) or "the window did not load")
    window = roots[0]
    assert isinstance(window, QQuickWindow)
    return window


def run_quick(path: Path) -> int:
    """
    Shows the window until it is closed; raises `ConfigError` for a file it can't edit. Qt scales a whole application
    only when it starts (`QT_SCALE_FACTOR`), so a new zoom closes the window and starts the next application, which
    goes on where this one was (`Session`: the document with its history, the page, where the window is, ...).
    """
    from xtouch_daemon.audio.pulse import follow_state, read_state
    from xtouch_daemon.gui.quick import errors
    from xtouch_daemon.gui.quick.settings import load_zoom
    from xtouch_daemon.gui.quick.window.quit import QuitWindows

    errors.install()
    # before anything of Qt: Python's handler would raise KeyboardInterrupt in whatever runs
    signals = QuitWindows()
    document = SlotsDocument.open(path)
    own = os.environ.get(SCALE_FACTOR)
    session: Session | None = None
    while True:
        name_application()
        os.environ[SCALE_FACTOR] = scale_for(load_zoom(), own)
        qapp = QGuiApplication(sys.argv[:1])
        qapp.setApplicationDisplayName("X-Touch Extender")
        qapp.setDesktopFileName("xtouch-daemon-gui")
        qapp.setWindowIcon(app_icon())
        deps = Dependencies(
            document,
            Service(wait=False, timeout=SYSTEMCTL_TIMEOUT),
            lambda: read_state("xtouch-daemon-gui"),
            session=session,
            follow_audio=lambda on_state: follow_state("xtouch-daemon-gui", on_state),
        )
        app = App(deps)
        signals.watch_windows(qapp, app.dialogs_open)
        engine = make_engine()
        engine.warnings.connect(lambda warnings: [log.warning("QML: %s", w.toString()) for w in warnings])
        load_window(app, engine)
        code = qapp.exec()
        rezoom = app.rezoom
        if rezoom is None:
            return code
        session = app.last_session
        # Qt allows one application at a time: this one goes before the next one starts
        sip.delete(engine)
        sip.delete(app)
        sip.delete(qapp)
        gc.collect()
