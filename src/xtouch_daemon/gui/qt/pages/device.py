"""
The page Device: the device as it is right now (the live view of the daemon), and below it what each slot shows when.
While the GUI hosts the virtual device, a bar above the drawing has what the mouse can't do on it.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut, QShowEvent
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from xtouch_daemon.gui.domain.looks import device_faces
from xtouch_daemon.gui.domain.simulate import simulated_faces
from xtouch_daemon.gui.qt.pages.slots import SlotsPanel
from xtouch_daemon.gui.qt.preview.panel import Preview
from xtouch_daemon.gui.qt.theme.settings import load_preview_share, save_preview_share
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.gui.qt.virtual_device import HostedDevice, VirtualDeviceBar
from xtouch_daemon.gui.qt.window.splitter import EDITOR_MIN_HEIGHT, PreviewSplitter
from xtouch_daemon.live.messages import Snapshot


class DevicePage(QWidget):
    close_virtual_device = pyqtSignal(arguments=[])
    """The bar of the hosted virtual device was told to close it."""

    def __init__(self, slots: SlotsPanel) -> None:
        super().__init__()
        self.page_layout = layout = QVBoxLayout(self)
        layout.setContentsMargins(0, Space.S, 0, 0)
        self.virtual_bar: VirtualDeviceBar | None = None
        self.preview = Preview()
        self.preview.clicked.connect(self.select)
        self.slots = slots
        """The slots, under the drawing of the device."""
        self.slots.setMinimumHeight(EDITOR_MIN_HEIGHT)
        self.slots.simulated.connect(lambda: self.show_live(self.snapshot))
        end = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        end.activated.connect(lambda: self.slots.simulate(None))
        self.splitter = PreviewSplitter()
        self.splitter.addWidget(self.preview)
        self.splitter.addWidget(self.slots)
        # a larger window gives the room to the slots, the drawing keeps its size until the handle is dragged
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(self._resized)
        self.splitter.held.connect(self._held)
        layout.addWidget(self.splitter, 1)
        self.share = load_preview_share()
        """The share of the height the drawing has, None while it has not been dragged: then it has its own size."""
        self.selected: int | None = None
        """The slot picked (0 for the leftmost one), None for none."""
        self.snapshot: Snapshot | None = None

    def showEvent(self, event: QShowEvent | None) -> None:
        """Gives the drawing its share of the height, now that the page has its size."""
        super().showEvent(event)
        if self.share is not None:
            self.splitter.share = self.share

    def _resized(self) -> None:
        """The handle was dragged: the share of the drawing is kept for the next start (once it is let go)."""
        self.share = self.splitter.share

    def _held(self, held: bool) -> None:
        """
        While the handle is held, the strips scale their pictures; once it is let go, they are drawn sharp, and the
        share is saved (not on every step of a drag, which would slow it down).
        """
        self.preview.hold(held)
        if not held and self.share is not None:
            save_preview_share(self.share)

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
            self.page_layout.insertWidget(0, self.virtual_bar)

    def select(self, index: int) -> None:
        """A strip of the drawing was picked: the card of its slot too."""
        self.selected = index
        self.show_live(self.snapshot)
        self.slots.select_slot(index + 1)
