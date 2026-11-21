"""
Errors that no code of the GUI caught (`gui/qt/errors.py`).
"""

import logging
import sys

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from xtouch_daemon.gui.qt import errors
from xtouch_daemon.gui.qt.window.main_window import MainWindow


def test_an_error_no_code_caught_is_logged_and_said_in_the_window(window: MainWindow, caplog: pytest.LogCaptureFixture):
    try:
        raise ValueError("boom")
    except ValueError as error:
        errors.report(ValueError, error, error.__traceback__)

    assert window.status.text().startswith("Something went wrong: ValueError: boom. The window goes on")
    (record,) = [record for record in caplog.records if record.name == errors.__name__]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    # without a message: its type
    errors.report(KeyError, KeyError(), None)
    assert window.status.text().startswith("Something went wrong: KeyError. ")


@pytest.mark.qt_no_exception_capture
def test_an_error_in_a_slot_goes_to_the_hook_and_the_program_goes_on(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    errors.install()
    assert sys.excepthook is errors.report
    told = QLabel()
    qtbot.addWidget(told)
    errors.listen(told.setText)

    def fail() -> None:
        raise RuntimeError("in a slot")

    # without the hook PyQt would end the program here
    QTimer.singleShot(0, fail)
    qtbot.waitUntil(lambda: told.text() == "RuntimeError: in a slot")

    # a window that fails to say it: logged, not told again (which would fail again)
    def broken(text: str) -> None:
        raise RuntimeError("told")

    errors.listen(broken)
    caplog.clear()
    errors.report(ValueError, ValueError("first"), None)
    assert [str(record.exc_info[1]) for record in caplog.records if record.exc_info] == ["first", "told"]
    errors._errors.raised.disconnect(broken)  # pyright: ignore[reportPrivateUsage]
