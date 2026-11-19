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
from xtouch_daemon.gui.domain.slots import MODES
from xtouch_daemon.gui.domain.status import Reason, Status, Tone, play_unavailable
from xtouch_daemon.gui.qt.fields.basics import label, show_status
from xtouch_daemon.gui.qt.fields.popover import Entry, make_clickable, show_popover
from xtouch_daemon.gui.qt.pages.slots import SlotsPanel
from xtouch_daemon.gui.qt.preview.panel import Hand, Preview
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space
from xtouch_daemon.gui.qt.virtual_device import HostedDevice, VirtualDeviceBar
from xtouch_daemon.live.messages import SetMode, Snapshot
from xtouch_daemon.slots.model import DEFAULT

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
    use_virtual_device = pyqtSignal(arguments=[])
    """"Use the virtual device": the daemon finds no device, so it drives the virtual one, hosted here."""

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
        """What the file showed last, while it is valid: kept while it has problems."""
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
        """The mode the device shows; a click: the modes to pick and the states."""
        self.slots_pill.hide()
        make_clickable(self.slots_pill, self._show_modes)
        layout.addWidget(self.slots_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(Space.XS)
        self.live_pill = label("", "pill")
        """Live or the file; a click: what that means (and the virtual device to open, while the daemon waits)."""
        make_clickable(self.live_pill, self._show_live)
        self.live_status: Status | None = None
        self.offered = False
        self.slots_status: Status | None = None
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
        self.virtual_button = QPushButton("Use the virtual device")
        set_icon(self.virtual_button, "monitor-shimmer")
        self.virtual_button.setToolTip(
            "The daemon runs, but finds no device: it drives the virtual device instead, here in the window, without a "
            "restart. Saves the file with `[device] virtual = true` (Virtual, on the page Extender)."
        )
        self.virtual_button.clicked.connect(self.use_virtual_device.emit)
        self.virtual_button.hide()
        layout.addWidget(self.virtual_button)
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
        if playing and self._opens_virtual_device():
            # Play on a daemon that waits for the virtual device opens it: `host` turns Play on once it runs
            self.select_button.setChecked(True)
            self.live_clicked.emit()
            return
        self.preview.set_playing(playing)
        self._show_mode()

    def _opens_virtual_device(self) -> bool:
        """Whether Play opens the virtual device first: the daemon waits for it, and the GUI offers to open it."""
        return self.offered and self.hosted is None

    def show_status(self, live: Status, offered: bool, slots: Status | None) -> None:
        """
        What the drawing shows (live or the file; `offered`: a click opens the virtual device) and the mode of the
        slots, None without slots.
        """
        changed = offered != self.offered
        self.live_status, self.offered, self.slots_status = live, offered, slots
        show_status(self.live_pill, live, more=True)
        if changed:
            self._show_mode()
        self.slots_pill.setVisible(slots is not None)
        if slots is not None:
            show_status(self.slots_pill, slots, more=True)

    def _show_live(self) -> None:
        if self.live_status is None:
            return
        actions = (("Open the virtual device", self.live_clicked.emit),) if self.offered else ()
        status = self.live_status
        # the pill clicked says the status already: only what it means, in the color of its tone
        entry = Entry("", Status("", status.tone), status.tip, actions)
        show_popover(self.live_pill, "Drawing", [entry])

    def _show_modes(self) -> None:
        """The mode, the modes to pick (or back to the rules) and the states, with what turned them on."""
        slots = self.snapshot.slots if self.snapshot is not None else None
        if slots is None or self.slots_status is None:
            return
        request = self.slots.request
        modes = [DEFAULT, *(state.name for state in slots.states if state.mode)]
        picks = tuple(
            ("Pick no mode" if mode == DEFAULT else f"Pick {mode}", lambda mode=mode: request(SetMode(mode)))
            for mode in modes
            if mode != slots.mode
        )
        if slots.mode_pick is not None:
            picks += (("Back to the rules", lambda: request(SetMode("auto"))),)
        how = "It was picked by hand, until the rules want another one." if slots.mode_pick else "The rules pick it."
        entries = [Entry("Mode", self.slots_status, f"{MODES} {how}", picks, Entity.STATE)]
        for state in slots.states:
            if state.mode:
                continue
            value = Status("on", Tone.GOOD) if state.value else Status("off", Tone.NEUTRAL)
            why = state.source or "none of its sources is on"
            why = why[:1].upper() + why[1:]
            override = "" if state.override == "auto" else f" Overridden: {state.override}."
            entries.append(Entry(state.name, value, f"{why}.{override}", entity=Entity.STATE))
        show_popover(self.slots_pill, "Mode and states", entries)

    def show_daemon(self, runs: bool) -> None:
        """Whether a daemon runs: without one (and nothing hosted), "Try without a device"."""
        self.daemon_runs = runs
        self._show_mode()

    def show_live(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot
        simulation = self.slots.simulation
        config = self.slots.editor.validation.config
        if simulation is not None and config is not None and snapshot is not None and not self.slots.on_device:
            faces = simulated_faces(config.slots, simulation)
        else:
            # the device as the daemon mirrors it, also while it shows the situation of Simulate; dark without a daemon
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
        if self._opens_virtual_device():
            reason = Reason(
                "opens the virtual device",
                "The daemon drives the virtual device, which does not run: Play opens it here and plays on it.",
            )
            self.play_button.setEnabled(True)
        else:
            self.play_button.setEnabled(reason is None)
        self.play_button.setToolTip(PLAY_TIP if reason is None else f"{reason.why}\n\n{PLAY_TIP}")
        if self.play_button.isChecked():
            where = "the virtual device" if hosting else "the device, through the daemon"
            hint = f"Playing on {where}"
        else:
            hint = "Drag a strip to move its slot"
            if reason is not None:
                # why Play is off, next to it rather than in its tooltip only
                hint += f"  ·  Play: {reason.short}"
        self.mode_hint.setText(hint)
        self.mode_hint.setToolTip(reason.why if reason is not None and not self.play_button.isChecked() else "")
        self.try_button.setVisible(not self.daemon_runs and not hosting)
        snapshot = self.snapshot
        self.virtual_button.setVisible(
            self.daemon_runs
            and snapshot is not None
            and not snapshot.device
            and not snapshot.virtual
            and self.owned()
            and not hosting
        )

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
