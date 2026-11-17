"""
The virtual device hosted by the GUI: a `SimulatedDevice` on the socket where the daemon looks for it (like
`xtouch-daemon virtual-device`), with the mouse on the drawing as a hand on it (`Preview.hand`) and a bar to plug it
in and out, switch it off and on and break touch sensors. What the drawing shows still comes from the daemon's live
view, which is what reached the device.
"""

import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QToolButton, QWidget

from xtouch_daemon.gui.qt.fields.basics import label
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.simulator.device import SimulatedDevice
from xtouch_daemon.simulator.server import TICK, AlreadyServed, listening


class HostedDevice(QObject):
    """The virtual device at `path`, plugged in once started."""

    changed = pyqtSignal(arguments=[])
    """Plugged in or out, the daemon came or went, a touch sensor broke or works again."""

    def __init__(self, path: Path, parent: QObject | None = None):
        super().__init__(parent)  # pyright: ignore[reportArgumentType]
        self.path = path
        self.device = SimulatedDevice()
        self.server: QLocalServer | None = None
        self.host: QLocalSocket | None = None
        """The connection of the daemon, None while there is none."""
        self.ticker = QTimer(self)
        self.ticker.setInterval(round(TICK * 1000))
        self.ticker.timeout.connect(lambda: self.send(self.device.advance(time.monotonic())))

    def start(self) -> None:
        """Plugs it in and lets its time run. AlreadyServed if another virtual device runs."""
        self.plug()
        self.ticker.start()

    def stop(self) -> None:
        self.ticker.stop()
        self.unplug()

    @property
    def plugged(self) -> bool:
        return self.server is not None

    def plug(self) -> None:
        if self.server is not None:
            return
        if listening(self.path):
            raise AlreadyServed(f"a virtual device already runs at {self.path}")
        self.path.unlink(missing_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        server = QLocalServer(self)
        if not server.listen(str(self.path)):
            raise OSError(f"can't serve the virtual device at {self.path}: {server.errorString()}")
        server.newConnection.connect(self._connected)
        self.server = server
        self.changed.emit()

    def unplug(self) -> None:
        if self.server is None:
            return
        self.server.close()
        self.server.deleteLater()
        self.server = None
        self.path.unlink(missing_ok=True)
        if self.host is not None:
            host, self.host = self.host, None
            host.abort()
        self.changed.emit()

    def power_cycle(self) -> None:
        """Switched off and on: the daemon loses it, and it starts like the real device."""
        self.unplug()
        self.device.power_cycle()
        self.plug()

    def set_broken_touch(self, strip: int, broken: bool) -> None:
        if broken:
            self.device.broken_touch.add(strip)
        else:
            self.device.broken_touch.discard(strip)
        self.changed.emit()

    def _connected(self) -> None:
        assert self.server is not None
        while (sock := self.server.nextPendingConnection()) is not None:
            if self.host is not None:
                # the device is open already
                sock.abort()
                continue
            self.host = sock
            sock.readyRead.connect(lambda sock=sock: self._read(sock))
            sock.disconnected.connect(lambda sock=sock: self._gone(sock))
            self.changed.emit()

    def _read(self, sock: QLocalSocket) -> None:
        self.device.receive(bytes(sock.readAll().data()), time.monotonic())

    def _gone(self, sock: QLocalSocket) -> None:
        sock.deleteLater()
        if self.host is sock:
            self.host = None
            self.changed.emit()

    def send(self, data: bytes) -> None:
        """What the device sends to the daemon; lost while there is none."""
        if data and self.host is not None:
            self.host.write(data)

    # -- a hand on it (see `Preview.hand`) ------------------------------------------------------------------------

    def touch(self, strip: int, touched: bool) -> None:
        self.send(self.device.touch(strip, touched))

    def move(self, strip: int, fraction: float, hand: bool = True) -> None:
        self.send(self.device.move(strip, fraction, hand))

    def press(self, strip: int, button: Button, pressed: bool) -> None:
        self.send(self.device.press(strip, button, pressed))

    def turn(self, strip: int, steps: int) -> None:
        self.send(self.device.turn(strip, steps))

    def push(self, strip: int, pressed: bool) -> None:
        self.send(self.device.push(strip, pressed))


class VirtualDeviceBar(QWidget):
    """Above the drawing while the GUI hosts the virtual device: what the hand can't do with the mouse."""

    def __init__(self, hosted: HostedDevice, close: QPushButton):
        super().__init__()
        self.hosted = hosted
        layout = QHBoxLayout(self)
        layout.setContentsMargins(Space.S, 0, Space.S, 0)
        self.state = label("", "hint")
        layout.addWidget(self.state)
        layout.addStretch(1)
        self.plug = QPushButton()
        self.plug.clicked.connect(lambda: hosted.unplug() if hosted.plugged else hosted.plug())
        layout.addWidget(self.plug)
        power = QPushButton("Switch off and on")
        power.setToolTip("The daemon loses it; it starts again with its faders going down, like the real device.")
        power.clicked.connect(hosted.power_cycle)
        layout.addWidget(power)
        self.broken = QToolButton()
        self.broken.setText("Broken touch")
        self.broken.setToolTip("Faders whose touch sensor failed: they never report a touch.")
        self.broken.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.broken)
        for strip in range(protocol.STRIPS):
            action = menu.addAction(f"Fader {strip + 1}")
            assert action is not None
            action.setCheckable(True)
            action.toggled.connect(lambda broken, strip=strip: hosted.set_broken_touch(strip, broken))
        self.broken.setMenu(menu)
        layout.addWidget(self.broken)
        layout.addWidget(close)
        hosted.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        hosted = self.hosted
        if not hosted.plugged:
            state = "Virtual device: unplugged"
        elif hosted.host is None:
            state = "Virtual device: waiting for the daemon"
        else:
            state = "Virtual device: the mouse is a hand on it (Alt-drag moves a fader without a touch)"
        self.state.setText(state)
        self.plug.setText("Unplug" if hosted.plugged else "Plug in")
