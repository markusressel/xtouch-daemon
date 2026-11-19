"""The live view of the running daemon (see `xtouch_daemon.live`), read with a QLocalSocket in the event loop."""

import os
import socket
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalSocket

from xtouch_daemon.live.codec import decode_message, encode_request
from xtouch_daemon.live.messages import KnownDevice, KnownDevices, LogLines, Reply, Request, Snapshot, TwinView
from xtouch_daemon.live.server import peer_uid


class LiveView(QObject):
    """
    The latest state of the daemon at `path`. `changed` tells every new one, and None when the connection ended (or
    could not be made); `replied` every `Reply` of the daemon. Without a thread: Qt reads the socket when there is
    something to read.
    """

    changed = pyqtSignal(object, arguments=["snapshot"])
    replied = pyqtSignal(object, arguments=["reply"])
    twin_changed = pyqtSignal(object, arguments=["view"])
    """Every new view of the virtual twin of this window (a `StartPreview` not `on_device`), None when it is gone."""
    logged = pyqtSignal(object, arguments=["lines"])
    """Records of the log of the daemon (`LogLines`), after a `WatchLog`."""

    def __init__(self, path: Path, parent: QObject | None = None):
        """`parent` is the window it belongs to: it ends with it, so the socket tells nothing to a closed window."""
        # PyQt6's stub types the parent of a QObject as `Self`, the class itself
        super().__init__(parent)  # pyright: ignore[reportArgumentType]
        self.path = path
        self.snapshot: Snapshot | None = None
        self.twin: TwinView | None = None
        """The latest view of the virtual twin of this window, None without one."""
        self.known: tuple[KnownDevice, ...] = ()
        """The devices the daemon remembers (also those that are not there now), for suggestions."""
        self.owned = False
        """
        Whether the daemon at the other end runs as this user, so requests (which carry the configuration with its
        secrets) may go to it.
        """
        self.socket = QLocalSocket(self)
        self.socket.connected.connect(self._connected)
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

    def send(self, request: Request) -> bool:
        """Sends a request to the daemon; False while not connected to a daemon of this user."""
        if not self.owned or self.socket.state() != QLocalSocket.LocalSocketState.ConnectedState:
            return False
        self.socket.write(encode_request(request))
        self.socket.flush()
        return True

    def _connected(self) -> None:
        # a copy of the descriptor: closing it leaves the one of Qt open
        with socket.socket(fileno=os.dup(int(self.socket.socketDescriptor()))) as sock:
            self.owned = peer_uid(sock) == os.getuid()

    def _read(self) -> None:
        # only the latest complete snapshot counts, each is the whole state; every reply counts
        latest: Snapshot | None = None
        view: TwinView | None = None
        while self.socket.canReadLine():
            message = decode_message(bytes(self.socket.readLine().data()))
            if isinstance(message, Reply):
                self.replied.emit(message)
            elif isinstance(message, TwinView):
                view = message
            elif isinstance(message, KnownDevices):
                self.known = message.devices
            elif isinstance(message, LogLines):
                self.logged.emit(message)
            elif message is not None:
                latest = message
        if view is not None:
            self.twin = view
            self.twin_changed.emit(view)
        if latest is not None:
            self.snapshot = latest
            self.changed.emit(latest)

    def forget_twin(self) -> None:
        """The twin is gone (ended, or its window closed): its last view is not shown any more."""
        if self.twin is not None:
            self.twin = None
            self.twin_changed.emit(None)

    def _lost(self) -> None:
        self.owned = False
        self.forget_twin()
        if self.snapshot is None:
            return
        self.snapshot = None
        self.changed.emit(None)
