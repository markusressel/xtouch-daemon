"""Zooming the window in Qt Quick, which takes a new application that goes on where the old one was."""

import dataclasses
from pathlib import Path

import pytest
from PyQt6.QtCore import QProcess, QRect, Qt
from PyQt6.QtQuick import QQuickWindow
from PyQt6.QtWidgets import QApplication

from tests.gui.quick import test_menu
from tests.gui.quick.conftest import MakeUi
from tests.support.dialogs import FakeDialogs
from tests.support.quick import Ui
from xtouch_daemon.audio.model import DISCONNECTED
from xtouch_daemon.gui.qt.theme.settings import ZOOM_LEVELS, load_zoom
from xtouch_daemon.gui.qt.window.session import Session
from xtouch_daemon.gui.quick import app as app_module
from xtouch_daemon.gui.quick.app import App

CTRL = Qt.KeyboardModifier.ControlModifier


def edit(ui: Ui) -> None:
    ui.app.editor.document.set(("behavior", "encoder_step"), 3)
    ui.app.editor.edited()
    ui.settle()


def test_a_new_zoom_takes_a_new_window_that_goes_on_where_this_one_was(make_ui: MakeUi, ui: Ui, dialogs: FakeDialogs):
    shell = ui.app.shell
    edit(ui)
    ui.app.showPage("states")
    assert shell.zoomLevel == 1.0

    # the same zoom: nothing to do
    shell.zoom_to(1.0)
    assert shell.rezoom is None
    # Ctrl++ closes without asking about the changes: they go to the next window
    test_menu.KEYS.keyClick(ui.window, Qt.Key.Key_Plus, CTRL)
    ui.settle()
    assert shell.rezoom == 1.1
    assert not ui.window.isVisible()
    assert dialogs.shown == []
    assert load_zoom() == 1.1

    session = shell.last_session
    assert session is not None
    assert (session.page, session.maximized) == ("states", False)
    assert session.history is ui.app.editor.history
    ratio = ui.window.devicePixelRatio()
    assert session.geometry.width() == round(1280 * ratio)

    after = make_ui(session=session, document=ui.app.editor.document)
    assert after.app.shell.zoomLevel == 1.1
    assert after.app.editor.history is session.history
    assert after.app.editor.document.modified
    assert after.app.editor.history.can_undo
    assert after.app.page == "states"
    assert after.app.shell.zoomLevels[ZOOM_LEVELS.index(1.1)]["value"] == 1.1


def test_the_zoom_menu_has_the_levels_and_keys(ui: Ui):
    zooms: list[float] = []
    ui.app.shell.zoom_to = zooms.append  # type: ignore[method-assign]
    test_menu.open_title(ui, "view")
    ui.click(test_menu.submenu_item(ui, "Zoom"))
    ui.grab()
    assert ui.item("menu_zoom.1").property("checked") is True
    ui.click("menu_zoom.3")

    test_menu.press(ui, Qt.Key.Key_Minus, CTRL)
    test_menu.press(ui, Qt.Key.Key_Equal, CTRL)
    test_menu.press(ui, Qt.Key.Key_0, CTRL)

    assert zooms == [3.0, 0.9, 1.1, 1.0]


def test_a_maximized_window_stays_maximized(make_ui: MakeUi, ui: Ui, monkeypatch: pytest.MonkeyPatch):
    session = ui.app.shell.session()
    assert not session.maximized
    maximized: list[bool] = []
    monkeypatch.setattr(QQuickWindow, "showMaximized", lambda window: maximized.append(True))

    make_ui(session=dataclasses.replace(session, maximized=True))

    assert maximized == [True]


def test_run_quick_starts_again_for_a_new_zoom(
    path: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication, dialogs: FakeDialogs
):
    from xtouch_daemon.gui import qt

    apps: list[App] = []
    sessions: list[Session | None] = []
    original = App.__init__

    def init(app: App, deps: app_module.Dependencies) -> None:
        original(app, deps)
        deps.dialogs = dialogs
        apps.append(app)
        sessions.append(deps.session)

    monkeypatch.setattr(App, "__init__", init)
    monkeypatch.setattr(app_module, "QApplication", lambda args: qapp)
    monkeypatch.setattr(qt.errors, "install", lambda: None)
    deleted: list[object] = []
    # the test's application stays
    monkeypatch.setattr(app_module.sip, "delete", deleted.append)
    monkeypatch.delenv(qt.SCALE_FACTOR, raising=False)
    scales: list[str] = []

    def exec_() -> int:
        scales.append(app_module.os.environ[qt.SCALE_FACTOR])
        if len(apps) == 1:
            shell = apps[0].shell
            shell.zoom_to(1.1)
            shell.last_session = Session(apps[0].editor.history, "slots", QRect(0, 0, 100, 100), False, DISCONNECTED)
        return 0

    monkeypatch.setattr(qapp, "exec", exec_)
    monkeypatch.setattr(app_module, "load_window", lambda app, engine: None)

    assert app_module.run_quick(path) == 0
    assert scales == ["1", "1.1"]
    assert sessions[0] is None
    assert sessions[1] is not None
    assert len(deleted) == 3


def test_the_trial_goes_to_the_window_of_the_new_zoom(make_ui: MakeUi, ui: Ui):
    shell = ui.app.shell
    process = QProcess()
    process.start("sleep", ["30"])
    assert process.waitForStarted()
    shell._keep_trying(process)  # pyright: ignore[reportPrivateUsage]
    shell.zoom_to(1.1)
    session = shell.last_session
    assert session is not None

    after = make_ui(session=session)
    assert after.app.shell.trying is process

    process.terminate()
    assert process.waitForFinished(5000)
    # only the new window takes the end: the one before would touch what run_quick deletes
    ui.wait_until(lambda: after.app.shell.trying is None)
    assert after.app.shell.statusText.startswith("The daemon for trying without a device ended (exit code ")
    assert shell.statusText == ""
