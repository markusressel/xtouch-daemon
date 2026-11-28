"""
Errors that no code of the GUI caught (`gui/quick/errors.py`).
"""

import logging
import sys

import pytest
from PyQt6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from tests.support.quick import Ui
from xtouch_daemon.gui.quick import errors


def test_an_error_no_code_caught_is_logged_and_said_in_the_window(ui: Ui, caplog: pytest.LogCaptureFixture):
    try:
        raise ValueError("boom")
    except ValueError as error:
        errors.report(ValueError, error, error.__traceback__)

    assert ui.app.shell.statusText.startswith("Something went wrong: ValueError: boom. The window goes on")
    (record,) = [record for record in caplog.records if record.name == errors.__name__]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    # without a message: its type
    errors.report(KeyError, KeyError(), None)
    assert ui.app.shell.statusText.startswith("Something went wrong: KeyError. ")


@pytest.mark.qt_no_exception_capture
def test_an_error_in_a_slot_goes_to_the_hook_and_the_program_goes_on(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    errors.install()
    assert sys.excepthook is errors.report
    told: list[str] = []

    def note(text: str) -> None:
        told.append(text)

    errors.listen(note)

    def fail() -> None:
        raise RuntimeError("in a slot")

    # without the hook PyQt would end the program here
    QTimer.singleShot(0, fail)
    qtbot.waitUntil(lambda: told == ["RuntimeError: in a slot"])

    # a window that fails to say it: logged, not told again (which would fail again)
    def broken(text: str) -> None:
        raise RuntimeError("told")

    errors.listen(broken)
    caplog.clear()
    errors.report(ValueError, ValueError("first"), None)
    assert [str(record.exc_info[1]) for record in caplog.records if record.exc_info] == ["first", "told"]
    errors._errors.raised.disconnect(broken)  # pyright: ignore[reportPrivateUsage]
    errors._errors.raised.disconnect(note)  # pyright: ignore[reportPrivateUsage]
