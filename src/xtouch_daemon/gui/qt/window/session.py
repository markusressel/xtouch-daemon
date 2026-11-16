"""
What a window hands to the next one when the zoom changes.
"""

from dataclasses import dataclass

from PyQt6.QtCore import QRect

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.gui.domain.history import History


@dataclass(frozen=True)
class Session:
    """
    What a window hands to the next one when the zoom changes (see `run_gui`): Qt scales a whole application only when
    it starts, so a new zoom takes a new window, which goes on where the old one was.
    """

    history: History
    """The undo history, and through it the document with its unsaved changes."""
    selected: int
    page: str
    geometry: QRect
    """Where the window was, in pixels of the screen (the zoom changes the size of a window's own pixels)."""
    maximized: bool
    audio: AudioState
    preview_share: float | None
    """The share of the height the preview has, None while it has not been dragged."""
    live_preview: bool = False
    """Whether the live preview was on: it goes on in the next window (a new start has it off)."""
