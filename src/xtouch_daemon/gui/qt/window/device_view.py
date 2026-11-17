"""
The device as it is right now (the live view of the daemon), or what Simulate on the page Slots shows: the window
Device, docked or on its own, on every page. While the GUI hosts the virtual device, a bar above the drawing has what
the mouse can't do on it.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from xtouch_daemon.gui.domain.looks import device_faces
from xtouch_daemon.gui.domain.simulate import simulated_faces
from xtouch_daemon.gui.qt.pages.slots import SlotsPanel
from xtouch_daemon.gui.qt.preview.panel import Preview
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.gui.qt.virtual_device import HostedDevice, VirtualDeviceBar
from xtouch_daemon.live.messages import Snapshot


class DeviceView(QWidget):
    close_virtual_device = pyqtSignal(arguments=[])
    """The bar of the hosted virtual device was told to close it."""
    picked = pyqtSignal(int, arguments=["slot"])
    """A strip of the drawing was clicked: the slot (1 for the leftmost one) to show on the page Slots."""

    def __init__(self, slots: SlotsPanel) -> None:
        super().__init__()
        self.view_layout = layout = QVBoxLayout(self)
        layout.setContentsMargins(Space.S, Space.S, Space.S, Space.S)
        self.virtual_bar: VirtualDeviceBar | None = None
        self.preview = Preview()
        self.preview.clicked.connect(self.select)
        layout.addWidget(self.preview, 1)
        self.slots = slots
        """The slots: what Simulate shows instead of the device."""
        self.slots.simulated.connect(lambda: self.show_live(self.snapshot))
        end = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        end.activated.connect(lambda: self.slots.simulate(None))
        self.selected: int | None = None
        """The strip picked (0 for the leftmost one), None for none."""
        self.snapshot: Snapshot | None = None

    def show_live(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot
        simulation = self.slots.simulation
        config = self.slots.editor.validation.config
        if simulation is not None and config is not None:
            faces = simulated_faces(config.slots, simulation)
        else:
            faces = device_faces(snapshot)
        self.preview.show_faces(faces, self.selected, simulating=simulation is not None)
        self.slots.show_live(snapshot)

    def host(self, hosted: HostedDevice | None) -> None:
        """The GUI hosts the virtual device (None: not any more): its bar, and the mouse as a hand on it."""
        if self.virtual_bar is not None:
            self.virtual_bar.deleteLater()
            self.virtual_bar = None
        self.preview.hand = hosted
        if hosted is not None:
            close = QPushButton("Close")
            close.setToolTip("Closes the virtual device: for the daemon, it is unplugged.")
            close.clicked.connect(self.close_virtual_device.emit)
            self.virtual_bar = VirtualDeviceBar(hosted, close)
            self.view_layout.insertWidget(0, self.virtual_bar)

    def select(self, index: int) -> None:
        """A strip of the drawing was picked: the card of its slot too."""
        self.selected = index
        self.show_live(self.snapshot)
        self.picked.emit(index + 1)
