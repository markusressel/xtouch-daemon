"""
Qt's own messages in the log of Python: the warnings of QML (a binding that fails, a type that does not fit) and
whatever else Qt says go to the logger `xtouch_daemon.qt`, with the category of Qt (`qml`, `qt.qpa`, ...), instead of
straight to stderr. A window that runs clean says nothing, so any line there is a mistake to fix.
"""

import logging
from collections.abc import Callable

from PyQt6.QtCore import QMessageLogContext, QtMsgType, qInstallMessageHandler

log = logging.getLogger("xtouch_daemon.qt")

LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}
"""The level of the log for each kind of message of Qt."""

type Handler = Callable[[QtMsgType, QMessageLogContext, str | None], None]


def handle(kind: QtMsgType, context: QMessageLogContext, message: str | None) -> None:
    """Logs a message of Qt: `qml: file:///...Main.qml:12: TypeError: ...`."""
    log.log(LEVELS.get(kind, logging.WARNING), "%s: %s", context.category or "default", message or "")


def install() -> Handler | None:
    """Qt's messages go to the log from now on; returns the handler that was there before."""
    return qInstallMessageHandler(handle)  # pyright: ignore[reportReturnType]
