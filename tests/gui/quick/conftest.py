"""
The window in Qt Quick, offscreen with Qt's software renderer, with a fake systemctl, a fake sound server and a
configuration in a temporary directory. `ui` is the window of a test.
"""

import os
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQuick import QQuickWindow, QSGRendererInterface
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.support.dialogs import FakeDialogs
from tests.support.gui import (
    CONFIG,
    RUNNING,
    STATE,
    FakeLiveDaemon,
    no_plugins,
    unreachable_broker,
    unreachable_home_assistant,
)
from tests.support.instance import RecordingInstance
from tests.support.quick import Ui
from tests.support.systemd import FakeSystemctl
from xtouch_daemon.gui.domain.slots_document import SlotsDocument
from xtouch_daemon.gui.domain.tokens import Motion, ThemeMode
from xtouch_daemon.gui.quick.app import App, Dependencies, load_window
from xtouch_daemon.gui.quick.engine import QML, STYLE, make_engine
from xtouch_daemon.gui.quick.theme import Theme
from xtouch_daemon.system.systemd import Service

MakeUi = Callable[..., Ui]

# The style of the controls is chosen once per process, by the first QML that imports them. A worker that ran the
# widgets first would have Qt's own style: set ours for the whole process.
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", STYLE)
os.environ.setdefault("QML_IMPORT_PATH", str(QML))


@pytest.fixture(autouse=True)
def software(qapp: QApplication) -> None:
    """Qt's software renderer: no GPU in the tests, and the same pixels everywhere."""
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)


@pytest.fixture(autouse=True)
def isolated(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """QSettings, the configuration and the runtime directory in the temporary directory."""
    QCoreApplication.setOrganizationName("xtouch-daemon-test")
    QCoreApplication.setApplicationName("xtouch-daemon-test")
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))


@pytest.fixture(autouse=True)
def no_motion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every change happens at once: the durations of `Theme` are 0. The tests of motion turn it on."""
    monkeypatch.setattr(Motion, "enabled", False)


@pytest.fixture(autouse=True)
def no_popups(qapp: QApplication) -> Iterator[None]:
    """
    Fails a test in which a popup window shows: it grabs the keyboard and the mouse (on X11 the whole display).
    Popups of QML stay items of the window (`popupType: Popup.Item`).
    """
    yield
    popups = [
        window.objectName() or type(window).__name__
        for window in QGuiApplication.topLevelWindows()
        if window.isVisible() and window.type() == Qt.WindowType.Popup
    ]
    assert popups == [], f"popup windows showed: {popups}"


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """The configuration file the service reads."""
    result = tmp_path / "xtouch-daemon" / "config.toml"
    result.parent.mkdir()
    result.write_text(CONFIG)
    return result


@pytest.fixture
def systemctl() -> FakeSystemctl:
    return FakeSystemctl(RUNNING)


@pytest.fixture
def daemon(path: Path) -> RecordingInstance:
    return RecordingInstance(1234, path.resolve(), systemd=True)


@pytest.fixture
def dialogs() -> FakeDialogs:
    """The questions of the window, answered at once (Discard); a test sets `answer` or `pick`."""
    return FakeDialogs()


@pytest.fixture
def make_ui(
    qtbot: QtBot, path: Path, systemctl: FakeSystemctl, daemon: RecordingInstance, dialogs: FakeDialogs
) -> Iterator[MakeUi]:
    made: list[Ui] = []

    def make(file: Path = path, mode: ThemeMode = ThemeMode.DARK, **deps: Any) -> Ui:
        options: dict[str, Any] = {
            "read_audio": lambda: STATE,
            "find_daemon": lambda: daemon,
            "try_broker": unreachable_broker,
            "plugin_installers": no_plugins(),
            "read_entities": unreachable_home_assistant,
            "dialogs": dialogs,
            **deps,
        }
        document = options.pop("document", None) or SlotsDocument.open(file)
        app = App(Dependencies(document, Service(systemctl, wait=False), **options))
        engine = make_engine(Theme(mode))
        window = load_window(app, engine)
        window.resize(1280, 900)
        window.show()
        qtbot.waitExposed(window)
        ui = Ui(qtbot, app, engine, window)
        made.append(ui)
        ui.settle()
        return ui

    yield make
    for ui in made:
        ui.window.close()
        ui.window.deleteLater()
        ui.engine.deleteLater()
    QGuiApplication.processEvents()
    # the window and the engine go before the backends they show do (QML would read what is gone)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def ui(make_ui: MakeUi) -> Ui:
    return make_ui()


@pytest.fixture
def live_daemon(qapp: QApplication) -> Iterator[FakeLiveDaemon]:
    """A fake daemon with a live view (see `FakeLiveDaemon`), in a temporary directory."""
    # a short path: the one of a Unix socket has at most 107 bytes, which tmp_path may exceed
    with tempfile.TemporaryDirectory(prefix="xtq-") as directory:
        fake = FakeLiveDaemon(Path(directory) / "live.sock")
        yield fake
        fake.close()
