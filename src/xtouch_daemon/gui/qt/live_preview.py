"""
The live preview (see `gui.domain.live_preview`): sends the document to the daemon while it is on, a moment after
every edit, with the situation of Simulate while it is open (see `docs/development/design/try-and-simulate.md`), and
keeps the preview alive with a heartbeat.
"""

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from xtouch_daemon.gui.domain.slots_document import SlotsDocument
from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.live.messages import EndPreview, KeepPreview, Reply, StartPreview
from xtouch_daemon.slots.outcomes import Situation

SITUATION = "situation"
"""The feature of the daemon (`Snapshot.features`) that runs a situation of Simulate."""

DEBOUNCE_MS = 300
"""How long the editor rests before the document goes to the daemon: typing a name sends it once, not per letter."""
HEARTBEAT_MS = 3000
"""How often the window tells the daemon that it is still there (`daemon.PREVIEW_TIMEOUT` is 10 s)."""


class LivePreview(QObject):
    """
    Whether the live preview is on, and what the daemon said about it. `changed` tells that the window should show
    it again.
    """

    changed = pyqtSignal(arguments=[])

    def __init__(self, live: LiveView, document: SlotsDocument):
        super().__init__()
        self.live = live
        self.document = document
        self.on = False
        self.running = False
        """Whether the daemon runs a preview of this window (it took one and did not end it since)."""
        self.error: str | None = None
        """Why the daemon did not take the latest document (it runs the one before)."""
        self.notice: str | None = None
        """Something to know: e.g. why the preview ended, or what of it needs a restart."""
        self.situation: Situation | None = None
        """What Simulate shows, None while it is closed: the device shows it too while the preview is on."""
        self._sent: tuple[str | None, Situation | None] | None = None
        """
        The last preview sent: the text (None: the file's) and the situation; None when no preview of this window
        runs or is on its way.
        """
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(DEBOUNCE_MS)
        self.debounce.timeout.connect(self.send)
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(HEARTBEAT_MS)
        self.heartbeat.timeout.connect(self._beat)
        # the window turns it off when the daemon goes away (see `domain.live_preview.unavailable()`)
        live.replied.connect(self._replied)

    def set_on(self, on: bool) -> None:
        """Turns the preview on (the document goes to the daemon at once) or off (back to the file)."""
        if on == self.on:
            return
        self.on = on
        self.error = self.notice = None
        if on:
            self.heartbeat.start()
            self.send()
        else:
            self.debounce.stop()
            self.heartbeat.stop()
            self._end()
        self.changed.emit()

    def document_changed(self) -> None:
        """After an edit (or undo, revert...): the document goes to the daemon once the editor rests."""
        if self.on:
            self.debounce.start()

    @property
    def simulating(self) -> bool:
        """Whether the daemon took a situation of this window (the snapshot tells once the device shows it)."""
        return self.running and self._sent is not None and self._sent[1] is not None

    def set_situation(self, situation: Situation | None) -> None:
        """Simulate changed (None: it ended): the device shows it too, a moment later, while the preview is on."""
        if situation == self.situation:
            return
        self.situation = situation
        if self.on:
            self.debounce.start()

    def saved(self) -> None:
        """
        The document was saved and the daemon reloads it, which ends the preview: the device runs the file, which is
        the document now. The preview stays on for the next edit.
        """
        self._sent = None
        self.running = False
        self.error = None
        self.changed.emit()

    def send(self) -> None:
        """
        Sends the document and the situation, unless the daemon has them already; without changes and without a
        situation the device runs the file.
        """
        snapshot = self.live.snapshot
        situation = self.situation if snapshot is not None and SITUATION in snapshot.features else None
        if not self.document.modified and situation is None:
            self._end()
            self.error = None
            self.changed.emit()
            return
        if self.document.modified and self.document.validate().config is None:
            # the problems show in the window; the device keeps the last document without them
            return
        sent = (self.document.render() if self.document.modified else None, situation)
        if sent != self._sent and self.live.send(StartPreview(*sent)):
            self._sent = sent

    def _end(self) -> None:
        sent, self._sent = self._sent, None
        self.running = False
        if sent is not None:
            # its answer ("ended") is not news
            self.live.send(EndPreview())

    def _beat(self) -> None:
        if self._sent is not None:
            self.live.send(KeepPreview())

    def _replied(self, reply: Reply) -> None:
        if reply.kind == "preview":
            if self._sent is None:
                # the answer to a preview that ended meanwhile
                return
            if reply.ok:
                self.running = True
                self.error = None
                self.notice = reply.message or None
            else:
                self.error = reply.message
        elif reply.kind == "ended":
            if self._sent is None:
                # it ended as this window wanted, e.g. by saving: a situation goes on with the file
                if self.on and self.situation is not None:
                    self.send()
                return
            # by the daemon: another window took over, the file changed, the window did not answer in time
            self._sent = None
            self.running = False
            self.set_on(False)
            self.notice = f"Trying the changes on the device ended: {reply.message}."
        elif reply.kind == "error":
            self.error = reply.message
        else:
            # about something else, e.g. a mode picked
            return
        self.changed.emit()
