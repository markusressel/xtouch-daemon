"""
Zooming the window, which takes a new one.
"""

import dataclasses
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication, QMenu
from pytestqt.qtbot import QtBot

from tests.support.gui import Dialogs, MakeWindow
from xtouch_daemon.gui import qt
from xtouch_daemon.gui.qt.theme.settings import (
    ZOOM_LEVELS,
    load_zoom,
    save_zoom,
    zoom_step,
    zoom_text,
)
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.gui.qt.window.session import Session


def test_zoom_goes_through_the_levels(isolated: Dialogs):
    assert zoom_step(1.0, 1) == 1.1
    assert zoom_step(1.0, -1) == 0.9
    # at the ends it stays
    assert zoom_step(3.0, 1) == 3.0
    assert zoom_step(0.67, -1) == 0.67
    # from a level that is none, from 100 %
    assert zoom_step(1.03, 1) == 1.1
    assert zoom_text(0.67) == "67 %"

    assert load_zoom() == 1.0
    save_zoom(1.5)
    assert load_zoom() == 1.5
    for odd in ("huge", 1.3):
        QSettings().setValue("zoom", odd)
        assert load_zoom() == 1.0


def test_the_scale_of_a_zoom_is_on_top_of_the_users_own():
    assert qt.scale_for(1.25, None) == "1.25"
    assert qt.scale_for(1.5, "2") == "3"
    assert qt.scale_for(1.1, "big") == "1.1"


def test_a_new_zoom_takes_a_new_window_that_goes_on_where_this_one_was(
    qtbot: QtBot, make_window: MakeWindow, isolated: Dialogs
):
    window = make_window()
    assert window.zoom_actions[1.0].isChecked()
    window.document.set(("behavior", "encoder_step"), 3)
    window.editor.edited()
    window.show_page("behavior")

    # the same zoom: nothing to do
    window.zoom_to(1.0)
    assert window.rezoom is None
    # Ctrl++: closes without asking about the unsaved changes, they go to the next window
    qtbot.keyClick(window, Qt.Key.Key_Plus, Qt.KeyboardModifier.ControlModifier)
    assert window.rezoom == 1.1
    assert not window.isVisible()
    assert isolated.shown == []
    assert load_zoom() == 1.1

    session = window.session()
    assert (session.page, session.maximized) == ("behavior", False)
    assert session.history is window.history
    ratio = window.devicePixelRatioF()
    assert session.geometry.width() == round(window.geometry().width() * ratio)

    after = make_window(session=session)
    assert after.zoom == 1.1
    assert after.zoom_actions[1.1].isChecked()
    assert after.history is window.history
    assert after.document.modified
    assert after.history.can_undo
    assert after.current_page == "behavior"


def test_zoom_keys_and_menu(qtbot: QtBot, window: MainWindow, isolated: Dialogs):
    zooms: list[float] = []
    window.zoom_to = zooms.append  # type: ignore[method-assign]
    window.zoom_out()
    window.zoom_in()
    window.zoom_reset()
    actions = list(window.zoom_actions.values())
    assert [action.text() for action in actions][:3] == ["67 %", "75 %", "80 %"]
    assert [action.isChecked() for action in actions].index(True) == ZOOM_LEVELS.index(1.0)
    actions[-1].trigger()
    assert zooms == [0.9, 1.1, 1.0, 3.0]
    # the keys are on the entries of the menu View, Zoom
    menu = actions[0].parent()
    assert isinstance(menu, QMenu)
    keys = {action.text(): action.shortcuts() for action in menu.actions()}
    assert QKeySequence("Ctrl+=") in keys["Zoom &in"]
    assert keys["&Actual size"] == [QKeySequence("Ctrl+0")]


def test_a_maximized_window_stays_maximized(make_window: MakeWindow, isolated: Dialogs):
    window = make_window()
    window.showMaximized()
    session = window.session()
    assert session.maximized
    after = make_window(session=dataclasses.replace(session, maximized=True))
    assert after.windowState() & Qt.WindowState.WindowMaximized


def test_run_gui_starts_again_for_a_new_zoom(
    path: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication, isolated: Dialogs
):
    windows: list[MainWindow] = []
    sessions: list[Session | None] = []
    original = MainWindow.__init__

    def init(window: MainWindow, *args: object, session: Session | None = None, **kwargs: object) -> None:
        original(window, *args, session=session, **kwargs)  # type: ignore[arg-type]
        windows.append(window)
        sessions.append(session)

    monkeypatch.setattr(MainWindow, "__init__", init)
    monkeypatch.setattr(qt, "QApplication", lambda args: qapp)
    monkeypatch.setattr(MainWindow, "show", lambda window: None)
    monkeypatch.setattr(qt.signal, "signal", lambda signum, handler: None)
    deleted: list[object] = []
    # the test's application stays
    monkeypatch.setattr(qt.sip, "delete", deleted.append)
    monkeypatch.delenv(qt.SCALE_FACTOR, raising=False)
    scales: list[str] = []

    def exec_() -> int:
        scales.append(qt.os.environ[qt.SCALE_FACTOR])
        if len(windows) == 1:
            windows[0].zoom_in()
        return 0

    monkeypatch.setattr(qapp, "exec", exec_)

    assert qt.run_gui(path) == 0
    assert scales == ["1", "1.1"]
    assert sessions[0] is None
    assert sessions[1] is not None
    assert sessions[1].history is windows[0].history
    assert deleted == [windows[0], qapp]
    for window in windows:
        window.deleteLater()
