"""
What a window hands to the next one when the zoom changes.
"""

import operator
from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import QProcess, QRect

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.gui.domain.history import History
from xtouch_daemon.gui.domain.slots_document import SlotsDocument


@dataclass(frozen=True)
class Session:
    """
    What a window hands to the next one when the zoom changes (see `run_gui`): Qt scales a whole application only when
    it starts, so a new zoom takes a new window, which goes on where the old one was.
    """

    history: History[SlotsDocument]
    """The undo history, and through it the document with its unsaved changes."""
    page: str
    geometry: QRect
    """Where the window was, in pixels of the screen (the zoom changes the size of a window's own pixels)."""
    maximized: bool
    audio: AudioState
    live_preview: bool = False
    """Whether the live preview was on: it goes on in the next window (a new start has it off)."""
    trying: QProcess | None = None
    """The daemon started by "Try without a device": the next window ends it when it closes."""


def _each(rect: QRect, ratio: float, op: Callable[[float, float], float]) -> QRect:
    return QRect(*(round(op(value, ratio)) for value in (rect.x(), rect.y(), rect.width(), rect.height())))


def to_screen(rect: QRect, ratio: float) -> QRect:
    """`rect` of a window with the device pixel ratio `ratio` in pixels of the screen (see `Session.geometry`)."""
    return _each(rect, ratio, operator.mul)


def from_screen(rect: QRect, ratio: float) -> QRect:
    """`rect` in pixels of the screen in those of a window with the device pixel ratio `ratio`."""
    return _each(rect, ratio, operator.truediv)
