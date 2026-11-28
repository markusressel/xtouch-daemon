"""
The test of the device, run by the daemon for this window (see `hardware.selftest` and
docs/development/design/interactive-test.md): started and ended with the button of the window Device, kept alive by a
heartbeat. The daemon ends it too: when the device goes away, a preview takes the device, or another window tests it.
"""

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from xtouch_daemon.gui.quick.live_view import LiveView
from xtouch_daemon.live.messages import EndTest, KeepTest, Reply, Snapshot, StartTest

HEARTBEAT_MS = 3000
"""How often the window tells the daemon that it is still there (`daemon.TEST_TIMEOUT` is 10 s)."""


class DeviceTest(QObject):
    """Whether the test of this window runs (`running`), and what the daemon said about it (`message`)."""

    changed = pyqtSignal(arguments=[])

    def __init__(self, live: LiveView):
        super().__init__()
        self.live = live
        self.running = False
        """Whether the daemon runs the test of this window (asked for, and not ended since)."""
        self.message: str | None = None
        """Why the test did not start, or why the daemon ended it; None after a start or an end by the window."""
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(HEARTBEAT_MS)
        self.heartbeat.timeout.connect(lambda: self.live.send(KeepTest()))
        live.replied.connect(self._replied)
        live.changed.connect(self._live_changed)

    def start(self) -> None:
        if self.running:
            return
        self.message = None
        if not self.live.send(StartTest()):
            self.message = "The daemon is not reachable."
            self.changed.emit()
            return
        # running until the daemon says otherwise: the button shows it at once
        self.running = True
        self.heartbeat.start()
        self.changed.emit()

    def stop(self) -> None:
        """Ends the test (the window closes, or the button): the device shows the slots again."""
        if not self.running:
            return
        self.live.send(EndTest())
        self._ended(None)

    def _ended(self, message: str | None) -> None:
        self.running = False
        self.heartbeat.stop()
        self.message = message
        self.changed.emit()

    def _replied(self, reply: Reply) -> None:
        if reply.kind == "test" and not reply.ok and self.running:
            self._ended(f"The test did not start: {reply.message}")
        elif reply.kind == "test_ended" and self.running:
            self._ended(f"The test of the device ended: {reply.message}.")

    def _live_changed(self, snapshot: Snapshot | None) -> None:
        if snapshot is None and self.running:
            self._ended("The test of the device ended: the daemon went away.")
