"""
The preview of the window (see `gui.domain.live_preview` and `docs/development/design/previews.md`): the unsaved edits,
with the situation of Simulate while it is open, shown where the control "Preview" says: in the GUI (on a virtual twin
in the daemon, the default), on the device, or nowhere ("Off": the drawing shows the device as it is). The document
goes to the daemon a moment after every edit, and a heartbeat keeps the preview alive.
"""

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from xtouch_daemon.gui.domain.live_preview import Place
from xtouch_daemon.gui.domain.slots_document import SlotsDocument
from xtouch_daemon.gui.quick.live_view import LiveView
from xtouch_daemon.live.messages import EndPreview, KeepPreview, Reply, Snapshot, StartPreview
from xtouch_daemon.slots.outcomes import Situation

SITUATION = "situation"
"""The feature of the daemon (`Snapshot.features`) that runs a situation of Simulate on the device."""

DEBOUNCE_MS = 300
"""How long the editor rests before the document goes to the daemon: typing a name sends it once, not per letter."""
HEARTBEAT_MS = 3000
"""How often the window tells the daemon that it is still there (`daemon.PREVIEW_TIMEOUT` is 10 s)."""


class LivePreview(QObject):
    """
    Where the preview shows (`place`), and what the daemon said about it. `changed` tells that the window should
    show it again.
    """

    changed = pyqtSignal(arguments=[])

    def __init__(self, live: LiveView, document: SlotsDocument):
        super().__init__()
        self.live = live
        self.document = document
        self.place = Place.GUI
        """Where the preview shows, while there is one (see `wanted`)."""
        self.running = False
        """Whether the daemon runs the preview of this window (it took it and did not end it since)."""
        self.error: str | None = None
        """Why the daemon did not take the latest document (it runs the one before)."""
        self.notice: str | None = None
        """Something to know: e.g. why the preview on the device ended, or what of it needs a restart."""
        self._ended_notice: str | None = None
        """Why the daemon ended the preview on the device, until the GUI shows it: the answer to that keeps it."""
        self.failed = False
        """The twin of this window failed: it is asked for again after the next change only."""
        self.situation: Situation | None = None
        """What Simulate shows, None while it is closed."""
        self._off_before_simulate = False
        """Simulate moved the place from Off to In the GUI: it goes back once Simulate closes."""
        self._sent: tuple[str | None, Situation | None, bool] | None = None
        """
        The last preview sent: the text (None: the file's), the situation and whether on the device; None when no
        preview of this window runs or is on its way.
        """
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(DEBOUNCE_MS)
        self.debounce.timeout.connect(self.send)
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(HEARTBEAT_MS)
        self.heartbeat.timeout.connect(self._beat)
        self.heartbeat.start()
        live.replied.connect(self._replied)
        live.changed.connect(self._live_changed)

    @property
    def wanted(self) -> bool:
        """Whether there is something to preview: unsaved edits, or Simulate open."""
        return self.document.modified or self.situation is not None

    @property
    def on(self) -> bool:
        """Whether the preview goes to the device ("On the device")."""
        return self.place == Place.DEVICE

    @property
    def in_gui(self) -> bool:
        """Whether the drawing shows the preview on the twin of this window."""
        return self.place == Place.GUI and self.wanted

    @property
    def simulating(self) -> bool:
        """Whether the device runs a situation of this window (the snapshot tells once it shows it)."""
        return self.running and self._sent is not None and self._sent[1] is not None and self._sent[2]

    def set_place(self, place: Place) -> None:
        """Where the preview shows from now on: it goes there at once (the device runs the file again otherwise)."""
        if place == self.place:
            return
        self.place = place
        self._off_before_simulate = False
        self.error = self.notice = self._ended_notice = None
        self.failed = False
        self.debounce.stop()
        self.send()
        self.changed.emit()

    def stop(self) -> None:
        """The window closes: the preview ends (the device runs the file again), wherever it showed."""
        self.debounce.stop()
        self.heartbeat.stop()
        self._end()

    def document_changed(self) -> None:
        """After an edit (or undo, revert...): the document goes to the daemon once the editor rests."""
        self.failed = False
        self.debounce.start()

    def set_situation(self, situation: Situation | None) -> None:
        """
        Simulate changed (None: it ended): the preview follows a moment later. Opened while Off, it moves the
        preview to the GUI, and back once it ends.
        """
        if situation == self.situation:
            return
        if self.situation is None and situation is not None and self.place == Place.OFF:
            self.place = Place.GUI
            self._off_before_simulate = True
        elif situation is None and self._off_before_simulate:
            self.place = Place.OFF
            self._off_before_simulate = False
        self.situation = situation
        self.failed = False
        self.debounce.start()
        self.changed.emit()

    def saved(self) -> None:
        """
        The document was saved and the daemon reloads it, which ends a preview on the device: the device runs the
        file, which is the document now. A twin follows the next `send()`.
        """
        if self._sent is not None and self._sent[2]:
            self._sent = None
            self.running = False
        self.error = None
        self.changed.emit()

    def send(self) -> None:
        """
        Sends the document and the situation where the preview shows, unless the daemon has them already; with
        nothing to preview, or Off, the preview ends.
        """
        if not self.wanted or self.place == Place.OFF:
            self._end()
            return
        on_device = self.place == Place.DEVICE
        snapshot = self.live.snapshot
        situation = self.situation
        if on_device and (snapshot is None or SITUATION not in snapshot.features):
            situation = None
        if on_device and not self.document.modified and situation is None:
            # the device runs the file anyway
            self._end()
            return
        if (self.document.modified or not on_device) and self.document.validate().config is None:
            # the problems show in the window; the preview keeps the last document without them
            return
        # the twin runs this document, also for a daemon that reads another file
        text = self.document.render() if self.document.modified or not on_device else None
        sent = (text, situation, on_device)
        if sent != self._sent and self.live.send(StartPreview(*sent)):
            if on_device:
                self.live.forget_twin()
            self._sent = sent

    def _end(self) -> None:
        sent, self._sent = self._sent, None
        self.running = False
        self.live.forget_twin()
        if sent is not None:
            # its answer ("ended") is not news
            self.live.send(EndPreview())
            self.changed.emit()

    def _beat(self) -> None:
        if self._sent is not None:
            self.live.send(KeepPreview())
        elif self.wanted and self.place != Place.OFF and not self.failed:
            # the daemon was gone: asked for again, as soon as there is one
            self.send()

    def _live_changed(self, snapshot: Snapshot | None) -> None:
        if snapshot is None and self._sent is not None:
            # the daemon went away, and the preview with it
            self._sent = None
            self.running = False

    def _replied(self, reply: Reply) -> None:
        if reply.kind == "preview":
            if self._sent is None:
                # the answer to a preview that ended meanwhile
                return
            if reply.ok:
                self.running = True
                self.error = None
                # the answer to the start in the GUI after the daemon ended the preview on the device: why it moved
                # stays, with what the daemon says now
                ended, self._ended_notice = self._ended_notice, None
                self.notice = " ".join(text for text in (ended, reply.message) if text) or None
            else:
                self.error = reply.message
        elif reply.kind == "ended":
            if self._sent is None:
                # it ended as this window wanted, e.g. by saving: a situation goes on with the file
                if self.wanted and self.place != Place.OFF:
                    self.send()
                return
            # by the daemon
            on_device = self._sent[2]
            self._sent = None
            self.running = False
            self.live.forget_twin()
            if on_device:
                # another window took the device, the file changed, the window did not answer in time
                self.place = Place.GUI
                self.notice = self._ended_notice = (
                    f"The preview on the device ended: {reply.message}. It shows in the GUI now."
                )
                self.send()
            else:
                self.failed = True
                self.notice = f"The preview in the GUI ended: {reply.message}."
        elif reply.kind == "error":
            self.error = reply.message
        else:
            # about something else, e.g. a mode picked
            return
        self.changed.emit()
