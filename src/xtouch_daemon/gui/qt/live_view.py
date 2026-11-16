"""The live view of the running daemon (see `xtouch_daemon.live`), read with a QLocalSocket in the event loop."""

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalSocket

from xtouch_daemon import live
from xtouch_daemon.live import Snapshot


class LiveView(QObject):
    """
    The latest state of the daemon at `path`. `changed` tells every new one, and None when the connection ended (or
    could not be made). Without a thread: Qt reads the socket when there is something to read.
    """

    changed = pyqtSignal(object, arguments=["snapshot"])

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.snapshot: Snapshot | None = None
        self.socket = QLocalSocket(self)
        self.socket.readyRead.connect(self._read)
        self.socket.disconnected.connect(self._lost)
        self.socket.errorOccurred.connect(self._lost)

    def connect_to_daemon(self) -> None:
        """Connects, unless it is connected or connecting already; the daemon may have started meanwhile."""
        if self.socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            self.socket.connectToServer(str(self.path))

    def disconnect_from_daemon(self) -> None:
        self.socket.abort()
        self._lost()

    def send(self, line: bytes) -> bool:
        """Sends a command (`live.command`) to the daemon; False while it is not connected."""
        if self.socket.state() != QLocalSocket.LocalSocketState.ConnectedState:
            return False
        self.socket.write(line)
        self.socket.flush()
        return True

    def _read(self) -> None:
        # only the latest complete line counts: each is the whole state
        latest: Snapshot | None = None
        while self.socket.canReadLine():
            snapshot = live.decode(bytes(self.socket.readLine().data()))
            if snapshot is not None:
                latest = snapshot
        if latest is not None:
            self.snapshot = latest
            self.changed.emit(latest)

    def _lost(self) -> None:
        if self.snapshot is None:
            return
        self.snapshot = None
        self.changed.emit(None)
