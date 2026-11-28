"""
The window ends clean: the QML goes before the backends it binds to, and what Qt says at runtime (QML warnings, a
binding that fails) goes to the log, where a test sees it.
"""

import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QtMsgType, qInstallMessageHandler
from PyQt6.QtGui import QGuiApplication

from tests.gui.quick.conftest import MakeUi
from xtouch_daemon.gui.quick import qtlog
from xtouch_daemon.gui.quick.app import PAGES, close_window


@pytest.fixture
def qt_log(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Qt's messages go to the log (as in `run_quick`) for the test, and to the handler of before afterwards."""
    caplog.set_level(logging.DEBUG, logger=qtlog.log.name)
    previous = qtlog.install()
    yield caplog
    qInstallMessageHandler(previous)  # pyright: ignore[reportArgumentType]


def said(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == qtlog.log.name]


def test_a_window_that_shows_every_page_and_closes_logs_no_qml_warning(
    make_ui: MakeUi, qt_log: pytest.LogCaptureFixture
):
    ui = make_ui()
    for name, *_ in PAGES:
        ui.app.showPage(name)
        ui.settle()
    for panel in (
        "device.place.window",
        "device.place.top",
        "log",
        "log.place.window",
        "log.place.right",
        "theme.light",
        "labels",
    ):
        ui.app.shell.trigger(panel)
        ui.settle()

    close_window(ui.engine, ui.app)
    QGuiApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert said(qt_log) == []


def test_closing_twice_does_no_harm(make_ui: MakeUi):
    ui = make_ui()

    close_window(ui.engine, ui.app)
    close_window(ui.engine, ui.app)


def test_what_qt_says_goes_to_the_log(qt_log: pytest.LogCaptureFixture):
    context: Any = SimpleNamespace(category="qml")
    qtlog.handle(QtMsgType.QtWarningMsg, context, "Main.qml:3: TypeError: Cannot read property 'x' of null")
    qtlog.handle(QtMsgType.QtCriticalMsg, context, "broken")
    qtlog.handle(QtMsgType.QtInfoMsg, context, None)

    records = [record for record in qt_log.records if record.name == qtlog.log.name]
    assert [(record.levelno, record.getMessage()) for record in records] == [
        (logging.WARNING, "qml: Main.qml:3: TypeError: Cannot read property 'x' of null"),
        (logging.ERROR, "qml: broken"),
        (logging.INFO, "qml: "),
    ]
