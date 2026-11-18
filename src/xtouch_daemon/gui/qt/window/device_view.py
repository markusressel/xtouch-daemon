"""
The device as it is right now (the live view of the daemon), or what Simulate on the page Slots shows (drawn by the
GUI, or on the device with Try on the device): the window
Device, docked or on its own, on every page. A bar above the drawing switches between Select (a click picks a slot,
a drag moves it) and Play (the mouse is a hand on the device), and offers to try it without a device while no daemon
runs; on its right the mode the device shows and whether the drawing is live. While the GUI hosts the virtual device,
a second bar has what the mouse can't do on it.
"""

from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from xtouch_daemon.gui.domain.looks import device_faces
from xtouch_daemon.gui.domain.simulate import simulated_faces
from xtouch_daemon.gui.domain.status import Status, play_unavailable
from xtouch_daemon.gui.qt.fields.basics import label, show_status
from xtouch_daemon.gui.qt.pages.slots import SlotsPanel
from xtouch_daemon.gui.qt.preview.panel import Hand, Preview
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.gui.qt.virtual_device import HostedDevice, VirtualDeviceBar
from xtouch_daemon.live.messages import Snapshot

SELECT_TIP = "Select: a click picks a strip and its slot, dragging a strip (or Ctrl+Left/Right) moves its slot."
PLAY_TIP = (
    "Play: the mouse is a hand on the device. Drag a fader (Alt: without a touch), click a button, turn an encoder "
    "with the wheel and push it with a click."
)


class DeviceView(QWidget):
    close_virtual_device = pyqtSignal(arguments=[])
    """The bar of the hosted virtual device was told to close it."""
    picked = pyqtSignal(int, arguments=["slot"])
    """A strip of the drawing was clicked: the slot (1 for the leftmost one) to show on the page Slots."""
    moved = pyqtSignal(int, int, arguments=["source", "target"])
    """A strip was dragged to another place: its slot moves there (slots from 1)."""
    live_clicked = pyqtSignal(arguments=[])
    """The pill of what the drawing shows was clicked (it opens the virtual device while the daemon waits for it)."""
    try_without_device = pyqtSignal(arguments=[])
    """"Try without a device": a daemon with the virtual device, hosted here."""

    def __init__(self, slots: SlotsPanel, remote: Hand, owned: Callable[[], bool]) -> None:
        """`remote`: the hand on the daemon's device; `owned`: whether the daemon runs as this user."""
        super().__init__()
        self.view_layout = layout = QVBoxLayout(self)
        layout.setContentsMargins(Space.S, Space.S, Space.S, Space.S)
        self.hosted: HostedDevice | None = None
        self.remote = remote
        self.owned = owned
        self.daemon_runs = True
        """Whether a daemon runs (see `show_daemon`): without one, it offers to try without a device."""
        self.snapshot: Snapshot | None = None
        self.slots = slots
        """The slots: what Simulate shows instead of the device."""
        self.preview = Preview()
        layout.addWidget(self._mode_bar())
        self.virtual_bar: VirtualDeviceBar | None = None
        self.preview.clicked.connect(self.select)
        self.preview.moved.connect(lambda source, target: self.moved.emit(source + 1, target + 1))
        layout.addWidget(self.preview, 1)
        self.slots.simulated.connect(lambda: self.show_live(self.snapshot))
        end = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        end.activated.connect(lambda: self.slots.simulate(None))
        self.selected: int | None = None
        """The strip picked (0 for the leftmost one), None for none."""

    def _mode_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, Space.XS)
        layout.setSpacing(0)
        self.modes = QButtonGroup(self)
        self.select_button = self._segment("Select", "cursor-default-outline", SELECT_TIP)
        self.play_button = self._segment("Play", "hand-back-right-outline", PLAY_TIP)
        self.select_button.setChecked(True)
        self.play_button.toggled.connect(self._play_toggled)
        layout.addWidget(self.select_button)
        layout.addWidget(self.play_button)
        layout.addSpacing(Space.S)
        self.mode_hint = label("", "hint")
        layout.addWidget(self.mode_hint, 1)
        self.slots_pill = label("", "pill")
        """The mode the device shows, with the states and slots in its tip."""
        self.slots_pill.hide()
        layout.addWidget(self.slots_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(Space.XS)
        self.live_pill = label("", "pill")
        """Live or the file; while the daemon waits for the virtual device, a click opens it."""
        self.live_pill.mousePressEvent = lambda event: self.live_clicked.emit()  # type: ignore[method-assign]
        layout.addWidget(self.live_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(Space.S)
        self.try_button = QPushButton("Try without a device")
        set_icon(self.try_button, "play-circle-outline")
        self.try_button.setToolTip(
            "Starts a daemon with the virtual device, here in the window, to set everything up and play with it "
            "before there is a device. It stops when the window closes."
        )
        self.try_button.clicked.connect(self.try_without_device.emit)
        self.try_button.hide()
        layout.addWidget(self.try_button)
        return bar

    def _segment(self, text: str, icon_name: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        set_icon(button, icon_name)
        set_role(button, "segment", "variant")
        button.setCheckable(True)
        button.setToolTip(tip)
        # keys typed into the window go to the strips, not here
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.modes.addButton(button)
        return button

    def _play_toggled(self, playing: bool) -> None:
        self.preview.set_playing(playing)
        self._show_mode()

    def show_status(self, live: Status, offered: bool, slots: Status | None) -> None:
        """
        What the drawing shows (live or the file; `offered`: a click opens the virtual device) and the mode of the
        slots, None without slots.
        """
        show_status(self.live_pill, live)
        self.live_pill.setCursor(Qt.CursorShape.PointingHandCursor if offered else Qt.CursorShape.ArrowCursor)
        self.slots_pill.setVisible(slots is not None)
        if slots is not None:
            show_status(self.slots_pill, slots)

    def show_daemon(self, runs: bool) -> None:
        """Whether a daemon runs: without one (and nothing hosted), "Try without a device"."""
        self.daemon_runs = runs
        self._show_mode()

    def show_live(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot
        simulation = self.slots.simulation
        config = self.slots.editor.validation.config
        if simulation is not None and config is not None and not self.slots.on_device:
            faces = simulated_faces(config.slots, simulation)
        else:
            # the device, also while it shows the situation of Simulate
            faces = device_faces(snapshot)
        self.preview.show_faces(faces, self.selected, simulating=simulation is not None)
        self.slots.show_live(snapshot)
        self._show_mode()

    def _show_mode(self) -> None:
        """Which hand Play has (the hosted virtual device first), and why none while it has none."""
        hosting = self.hosted is not None
        drawn = self.slots.simulation is not None and not self.slots.on_device
        reason = play_unavailable(self.snapshot, self.owned(), hosting, drawn)
        self.preview.device_hand = None if reason is not None else self.hosted or self.remote
        if reason is not None and self.play_button.isChecked():
            self.select_button.setChecked(True)
        self.play_button.setEnabled(reason is None)
        self.play_button.setToolTip(PLAY_TIP if reason is None else f"{PLAY_TIP}\n\n{reason}")
        if self.play_button.isChecked():
            where = "the virtual device" if hosting else "the device, through the daemon"
            hint = f"Playing on {where}"
        else:
            hint = "Drag a strip to move its slot"
        self.mode_hint.setText(hint)
        self.try_button.setVisible(not self.daemon_runs and not hosting)

    def host(self, hosted: HostedDevice | None) -> None:
        """The GUI hosts the virtual device (None: not any more): its bar, and Play on it."""
        if self.virtual_bar is not None:
            self.virtual_bar.deleteLater()
            self.virtual_bar = None
        self.hosted = hosted
        if hosted is not None:
            close = QPushButton("Close")
            close.setToolTip("Closes the virtual device: for the daemon, it is unplugged.")
            close.clicked.connect(self.close_virtual_device.emit)
            self.virtual_bar = VirtualDeviceBar(hosted, close)
            self.view_layout.insertWidget(1, self.virtual_bar)
        self._show_mode()
        if hosted is not None:
            # opened to play with it
            self.play_button.setChecked(True)

    def select(self, index: int) -> None:
        """A strip of the drawing was picked: the card of its slot too."""
        self.selected = index
        self.show_live(self.snapshot)
        self.picked.emit(index + 1)
