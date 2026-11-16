"""
The window of the GUI, offscreen (see tests/conftest.py), with a fake systemctl, a fake sound server, a
configuration in a temporary directory, and the dialogs answered by the tests.
"""

import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication, QSettings
from PyQt6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from tests.support.gui import (
    CONFIG,
    LAYOUT_CONFIG,
    NO_MUMBLE,
    RUNNING,
    STATE,
    Dialogs,
    FakeLiveDaemon,
    MakeWindow,
    no_install,
    unreachable_broker,
)
from tests.support.instance import RecordingInstance
from tests.support.systemd import FakeSystemctl
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.qt.pages.sections import BrokerTest, MumbleInstaller
from xtouch_daemon.gui.qt.theme.style import apply_theme
from xtouch_daemon.gui.qt.theme.tokens import ThemeMode
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.gui.qt.window.session import Session
from xtouch_daemon.system.instance import Instance
from xtouch_daemon.system.systemd import Service


@pytest.fixture(autouse=True)
def isolated(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dialogs:
    """
    QSettings, the configuration, the unit and the runtime directory in the temporary directory (a window never
    reaches the daemon of the machine, e.g. to preview a configuration on its device), and no dialog that waits for a
    user.
    """
    QCoreApplication.setOrganizationName("xtouch-daemon-test")
    QCoreApplication.setApplicationName("xtouch-daemon-test")
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    dialogs = Dialogs()
    monkeypatch.setattr(QMessageBox, "question", dialogs.question)
    monkeypatch.setattr(QMessageBox, "warning", dialogs.message)
    monkeypatch.setattr(QMessageBox, "critical", dialogs.message)
    apply_theme(ThemeMode.DARK)
    return dialogs


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
    """The service, which reads the file."""
    return RecordingInstance(1234, path.resolve(), systemd=True)


@pytest.fixture
def make_window(qtbot: QtBot, path: Path, systemctl: FakeSystemctl, daemon: RecordingInstance) -> MakeWindow:
    def make(
        read_audio: Callable[[], AudioState] = lambda: STATE,
        file: Path = path,
        find_daemon: Callable[[], Instance | None] = lambda: daemon,
        live_socket: Path | None = None,
        test_broker: BrokerTest = unreachable_broker,
        session: Session | None = None,
        mumble_installer: MumbleInstaller | None = None,
    ) -> MainWindow:
        # the window after a new zoom goes on with the document of the one before
        document = session.history.document if session is not None else ConfigDocument.open(file)
        window = MainWindow(
            document,
            Service(systemctl),
            read_audio,
            find_daemon,
            live_socket,
            test_broker,
            session,
            # nothing of this machine: no plugin, no Mumble
            mumble_installer or MumbleInstaller(no_install, lambda: NO_MUMBLE),
        )
        qtbot.addWidget(window)
        window.show()
        qtbot.waitUntil(lambda: window.audio_label.text() != "Reading the sound server…")
        return window

    return make


@pytest.fixture
def window(make_window: MakeWindow) -> MainWindow:
    return make_window()


@pytest.fixture
def live_daemon(qapp: QApplication) -> Iterator[FakeLiveDaemon]:
    # a short path: the one of a Unix socket has at most 107 bytes, which tmp_path may exceed
    with tempfile.TemporaryDirectory(prefix="xtg-") as directory:
        fake = FakeLiveDaemon(Path(directory) / "live.sock")
        yield fake
        fake.close()


@pytest.fixture
def layouts(make_window: MakeWindow, path: Path) -> MainWindow:
    path.write_text(LAYOUT_CONFIG)
    return make_window()
