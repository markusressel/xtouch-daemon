"""
Errors that no code of the GUI caught: logged and told in the window, never the end of the program.

PyQt ends the program (`qFatal`, a core dump) on an exception in a slot or in a method Qt calls (a paint, a size
hint) while `sys.excepthook` is Python's own. With `install()` such an error is logged with its traceback, and the
windows that `listen()` say it in their status line; the window goes on.
"""

import logging
import sys
from collections.abc import Callable
from types import TracebackType

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


class _Errors(QObject):
    raised = pyqtSignal(str, arguments=["text"])
    """An error no code caught: its type and message."""


_errors = _Errors()
_reporting = False
"""Whether the windows are told about an error now."""


def install() -> None:
    """Errors that no code caught go to `report` from now on."""
    sys.excepthook = report


def report(kind: type[BaseException], error: BaseException, traceback: TracebackType | None) -> None:
    """Logs an error with its traceback and tells the windows (see `listen`)."""
    global _reporting
    log.error("An error in the GUI, it goes on", exc_info=(kind, error, traceback))
    if _reporting:
        # a window failed to say an error: PyQt hands that error here too, it is logged only
        return
    _reporting = True
    try:
        _errors.raised.emit(f"{kind.__name__}: {error}" if str(error) else kind.__name__)
    finally:
        _reporting = False


def listen(told: Callable[[str], None]) -> None:
    """`told` gets the text of each error `report` gets."""
    _errors.raised.connect(told)
