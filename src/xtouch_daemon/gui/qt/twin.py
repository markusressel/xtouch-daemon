"""
The virtual twin of this window (see `gui.domain.twin`): while Simulate is open, the document and its situation go to
the daemon (`live.StartTwin`) a moment after every change, a heartbeat keeps the twin alive, and its views come back
through the live view. The drawing shows them, and the mouse is a hand on it (`RemoteHand(live, twin=True)`).
"""

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from xtouch_daemon.gui.domain.slots_document import SlotsDocument
from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.live.messages import EndTwin, KeepTwin, Reply, StartTwin
from xtouch_daemon.slots.outcomes import Situation

DEBOUNCE_MS = 150
"""How long the editor rests before the document goes to the twin."""
HEARTBEAT_MS = 3000
"""How often the window tells the daemon that the twin is still needed (`daemon.TWIN_TIMEOUT` is 10 s)."""


class TwinSession(QObject):
    """Whether this window has a twin (it asked for one and it was not ended), and what the daemon said about it."""

    changed = pyqtSignal(arguments=[])

    def __init__(self, live: LiveView, document: SlotsDocument):
        super().__init__()
        self.live = live
        self.document = document
        self.situation: Situation | None = None
        """What Simulate shows, None while it is closed: the twin runs it."""
        self.error: str | None = None
        """Why the daemon did not take the latest document (the twin runs the one before)."""
        self._sent: tuple[str, Situation] | None = None
        """The last request sent: the document's text and the situation; None while no twin is wanted."""
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(DEBOUNCE_MS)
        self.debounce.timeout.connect(self.send)
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(HEARTBEAT_MS)
        self.heartbeat.timeout.connect(self._beat)
        live.replied.connect(self._replied)

    def set_situation(self, situation: Situation | None) -> None:
        """Simulate changed (None: it ended): the twin follows a moment later, or is ended."""
        if situation == self.situation:
            return
        self.situation = situation
        if situation is None:
            self.end()
        else:
            self.heartbeat.start()
            self.debounce.start()

    def document_changed(self) -> None:
        """After an edit (or undo, revert...): the document goes to the twin once the editor rests."""
        if self.situation is not None:
            self.debounce.start()

    def send(self) -> None:
        """Sends the document and the situation, unless the twin has them already; a document with problems is kept."""
        if self.situation is None or self.document.validate().config is None:
            return
        sent = (self.document.render(), self.situation)
        if sent != self._sent and self.live.send(StartTwin(*sent)):
            self._sent = sent

    def end(self) -> None:
        """Ends the twin (the daemon is told, and the last view is forgotten)."""
        self.debounce.stop()
        self.heartbeat.stop()
        if self._sent is not None:
            self._sent = None
            self.live.send(EndTwin())
        self.error = None
        self.live.forget_twin()
        self.changed.emit()

    def _beat(self) -> None:
        if self._sent is None:
            # the daemon was gone or ended the twin: asked for again, as soon as there is a daemon
            self.send()
        else:
            self.live.send(KeepTwin())

    def _replied(self, reply: Reply) -> None:
        if reply.kind == "twin":
            self.error = None if reply.ok else reply.message
        elif reply.kind == "twin_ended":
            # by the daemon (it stops, or the window did not answer in time): asked for again at the next change
            self._sent = None
            self.live.forget_twin()
        else:
            return
        self.changed.emit()
