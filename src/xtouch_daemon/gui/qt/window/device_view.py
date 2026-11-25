"""
The device as it is right now (the live view of the daemon), or the preview of the window (the unsaved changes, and
Simulate while it is open) on its virtual twin in the daemon: the window Device, docked or on its own, on every page. A
bar above the drawing switches between Select (a click picks a slot, a drag moves it) and Play (the mouse is a hand on
the device), and offers to try it without a device while no daemon runs; on its right the mode the device shows,
whether the drawing is live, and the test of the device. While the GUI hosts the virtual device, a pill there opens
what the mouse can't do on it; while the test runs, a second bar says what each control does.
"""

from collections.abc import Callable

from PyQt6.QtCore import QEvent, QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QResizeEvent, QShortcut
from PyQt6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from xtouch_daemon.gui.domain.looks import device_faces, twin_faces
from xtouch_daemon.gui.domain.slots import MODES
from xtouch_daemon.gui.domain.status import (
    DeviceOffer,
    Reason,
    Status,
    Tone,
    play_unavailable,
    test_unavailable,
)
from xtouch_daemon.gui.qt.fields.basics import ElidedLabel, discard, label, show_status
from xtouch_daemon.gui.qt.fields.popover import Entry, make_clickable, show_popover
from xtouch_daemon.gui.qt.pages.slots import SlotsPanel
from xtouch_daemon.gui.qt.preview.panel import Hand, Preview
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space
from xtouch_daemon.gui.qt.virtual_device import HostedDevice, VirtualDevicePill
from xtouch_daemon.live.messages import SetMode, Snapshot, TwinView
from xtouch_daemon.slots.model import DEFAULT

SELECT_TIP = "Select: a click picks a strip and its slot, dragging a strip (or Ctrl+Left/Right) moves its slot."
TEST_TIP = (
    "Tests the device: every strip answers its own controls, on the device and here, so you can check each LED, the "
    "ring, the LCD colors, the motors and the touch of the faders. The slots go on, but show again only when the test "
    "ends."
)
TEST_HELP = (
    "Testing the device. Fader: the meter follows it. Rec, Solo, Mute, Select: the LED goes on, flashing, off. "
    "Encoder: turn it to change, push it for the next of ring, mode (+c: also the LEDs at its ends), LCD color, motor "
    "fader. The LCD shows the last input. Play works on the drawing too."
)
PLAY_TIP = (
    "Play: the mouse is a hand on the device. Drag a fader (Alt: without a touch), click a button, turn an encoder "
    "with the wheel and push it with a click."
)


class DeviceView(QWidget):
    close_virtual_device = pyqtSignal(arguments=[])
    """The popover of the hosted virtual device was told to close it."""
    restart_daemon = pyqtSignal(arguments=[])
    """The popover of the hosted virtual device was told to restart the daemon that drives it."""
    picked = pyqtSignal(int, arguments=["slot"])
    """A strip of the drawing was clicked: the slot (1 for the leftmost one) to show on the page Slots."""
    unpicked = pyqtSignal(arguments=[])
    """The drawing was clicked beside the strips: no strip, and no slot on the page Slots, is picked."""
    moved = pyqtSignal(int, int, arguments=["source", "target"])
    """A strip was dragged to another place: its slot moves there (slots from 1)."""
    live_clicked = pyqtSignal(arguments=[])
    """The pill of what the drawing shows was clicked (it opens the virtual device while the daemon waits for it)."""
    try_without_device = pyqtSignal(arguments=[])
    """"Try without a device": a daemon with the virtual device, hosted here."""
    use_virtual_device = pyqtSignal(arguments=[])
    """"Use the virtual device": the daemon finds no device, so it drives the virtual one, hosted here."""
    test_toggled = pyqtSignal(bool, arguments=["on"])
    """"Test the device" was clicked: start the test (True) or end it."""
    switch_to_device = pyqtSignal(arguments=[])
    """The button of the bar of a device that is plugged in while the daemon drives the virtual one."""

    def __init__(
        self,
        slots: SlotsPanel,
        remote: Hand,
        twin_hand: Hand,
        twin: Callable[[], TwinView | None],
        owned: Callable[[], bool],
        shows_twin: Callable[[], bool] = lambda: False,
        previewing: Callable[[], bool] = lambda: False,
        restart_reason: Callable[[], str | None] = lambda: None,
    ) -> None:
        """
        `remote`: the hand on the daemon's device; `twin_hand` and `twin`: the hand on the virtual twin of the window
        and its latest view; `owned`: whether the daemon runs as this user; `shows_twin`: whether the drawing shows the
        twin (the preview in the GUI); `previewing`: whether the drawing shows a preview of the window (on the twin or
        on the device); `restart_reason`: why the daemon that drives the hosted virtual device can't be restarted
        from here, None when it can.
        """
        super().__init__()
        self.view_layout = layout = QVBoxLayout(self)
        layout.setContentsMargins(Space.S, Space.S, Space.S, Space.S)
        self.hosted: HostedDevice | None = None
        self.remote = remote
        self.twin_hand = twin_hand
        self.twin = twin
        self.shows_twin = shows_twin
        self.previewing = previewing
        self.owned = owned
        self.restart_reason = restart_reason
        self.daemon_runs = True
        """Whether a daemon runs (see `show_daemon`): without one, it offers to try without a device."""
        self.snapshot: Snapshot | None = None
        """What the file showed last, while it is valid: kept while it has problems."""
        self.slots = slots
        """The slots: what Simulate shows instead of the device."""
        self.preview = Preview()
        self.testing = False
        """Whether the test of this window runs (see `show_test()`)."""
        layout.addWidget(self._mode_bar())
        self.test_bar = label(TEST_HELP, "hint", wrap=True)
        """What each control does while the test runs."""
        self.test_bar.hide()
        layout.addWidget(self.test_bar)
        layout.addWidget(self._device_bar())
        self.virtual_pill: VirtualDevicePill | None = None
        """While the GUI hosts the virtual device: how it is connected, and what can be done with it."""
        self.preview.clicked.connect(self.select)
        self.preview.cleared.connect(self.deselect)
        self.preview.moved.connect(lambda source, target: self.moved.emit(source + 1, target + 1))
        layout.addWidget(self.preview, 1)
        self.slots.simulated.connect(lambda: self.show_live(self.snapshot))
        end = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        end.activated.connect(lambda: self.slots.simulate(None))
        self.selected: int | None = None
        """The strip picked (0 for the leftmost one), None for none."""

    def _mode_bar(self) -> QWidget:
        left = QWidget()
        layout = QHBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.modes = QButtonGroup(self)
        self.select_button = self._segment("Select", "cursor-default-outline", SELECT_TIP)
        self.play_button = self._segment("Play", "hand-back-right-outline", PLAY_TIP)
        self.select_button.setChecked(True)
        self.play_button.toggled.connect(self._play_toggled)
        layout.addWidget(self.select_button)
        layout.addWidget(self.play_button)
        layout.addSpacing(Space.S)
        # cut where the bar is short: it never makes the window wider than the screen gives it
        self.mode_hint = ElidedLabel("", "hint")
        layout.addWidget(self.mode_hint)
        layout.addSpacing(Space.XS)
        self.hand_pill = label("", "pill")
        """In Play: what the mouse plays on, the device, the virtual device or the twin of the preview."""
        self.hand_pill.hide()
        layout.addWidget(self.hand_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        self.slots_pill = label("", "pill")
        """The mode the device shows, over the middle of the drawing; a click: the modes to pick and the states."""
        self.slots_pill.hide()
        make_clickable(self.slots_pill, self._show_modes)
        right = QWidget()
        layout = QHBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.live_pill = label("", "pill")
        """Live or the file; a click: what that means (and the virtual device to open, while the daemon waits)."""
        make_clickable(self.live_pill, self._show_live)
        self.live_status: Status | None = None
        self.offered = False
        self.slots_status: Status | None = None
        layout.addWidget(self.live_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.virtual_slot = QHBoxLayout()
        """Where the pill of the hosted virtual device goes, next to what the drawing shows."""
        self.virtual_slot.setContentsMargins(Space.XS, 0, 0, 0)
        layout.addLayout(self.virtual_slot)
        layout.addSpacing(Space.S)
        self.test_button = QPushButton("Test the device")
        set_icon(self.test_button, "test-tube")
        self.test_button.setCheckable(True)
        self.test_button.setToolTip(TEST_TIP)
        self.test_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.test_button.clicked.connect(lambda: self.test_toggled.emit(self.test_button.isChecked()))
        layout.addWidget(self.test_button)
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
        self.mode_row = CenteredRow(left, self.slots_pill, right)
        bar = QWidget()
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(0, 0, 0, Space.XS)
        outer.addWidget(self.mode_row)
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
        twin = self.twin()
        # the virtual twin once it shows something; the device as the daemon mirrors it until then, and also while it
        # shows the preview (dark without a daemon)
        faces = twin_faces(twin) if self.shows_twin() and twin is not None else device_faces(snapshot)
        self.preview.show_faces(faces, self.selected, simulating=self.previewing())
        self.slots.show_live(snapshot)
        self._show_mode()

    def _show_mode(self) -> None:
        """Which hand Play has (the hosted virtual device first), and why none while it has none."""
        hosting = self.hosted is not None
        drawn = self.shows_twin()
        reason = play_unavailable(self.snapshot, self.owned(), hosting, drawn)
        if reason is not None:
            self.preview.device_hand = None
        else:
            self.preview.device_hand = self.twin_hand if drawn else self.hosted or self.remote
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
        playing = self.play_button.isChecked()
        self.hand_pill.setVisible(playing)
        if playing:
            show_status(self.hand_pill, self._hand_status(hosting, drawn))
            hint = "Playing on"
        else:
            hint = "Drag a strip to move its slot"
            if reason is not None:
                # why Play is off, next to it rather than in its tooltip only
                hint += f"  ·  Play: {reason.short}"
        self.mode_hint.setText(hint)
        self.mode_hint.setToolTip(reason.why if reason is not None and not self.play_button.isChecked() else "")
        self.try_button.setVisible(not self.daemon_runs and not hosting)
        snapshot = self.snapshot
        test_reason = test_unavailable(snapshot, self.owned())
        self.test_button.setVisible(self.daemon_runs)
        self.test_button.setEnabled(self.testing or test_reason is None)
        self.test_button.setToolTip(TEST_TIP if test_reason is None else f"{test_reason.why}\n\n{TEST_TIP}")
        self.virtual_button.setVisible(
            self.daemon_runs
            and snapshot is not None
            and not snapshot.device
            and not snapshot.virtual
            and self.owned()
            and not hosting
        )

    def _hand_status(self, hosting: bool, drawn: bool) -> Status:
        """What the mouse plays on in Play, in the order the hand is picked (see `_show_mode`)."""
        if drawn:
            return Status(
                "the twin of the preview",
                Tone.NEUTRAL,
                "The drawing shows the preview in the GUI: the mouse plays on its virtual twin in the daemon, which "
                "runs the changes in the editor. The device is not touched.",
            )
        if hosting:
            return Status(
                "the virtual device",
                Tone.WARN,
                "The virtual device, here in the window: the daemon drives it like the real one, and what the mouse "
                "does acts on the sound server.",
            )
        if self.snapshot is not None and self.snapshot.virtual:
            return Status(
                "the virtual device",
                Tone.WARN,
                "The daemon drives the virtual device (`[device] virtual = true`): the mouse plays on it through the "
                "daemon, and what it does acts on the sound server.",
            )
        return Status(
            "the device",
            Tone.GOOD,
            "The X-Touch Extender, through the daemon: the mouse is a hand on it, and what it does acts on the sound "
            "server.",
        )

    def _device_bar(self) -> QFrame:
        """The bar while the device is plugged in and the daemon drives the virtual one (see `show_device_offer()`)."""
        self.device_bar = QFrame()
        set_role(self.device_bar, "banner")
        bar = QHBoxLayout(self.device_bar)
        bar.setContentsMargins(Space.M, Space.S, Space.M, Space.S)
        self.device_message = label("", wrap=True)
        bar.addWidget(self.device_message, 1)
        self.device_button = QPushButton()
        set_icon(self.device_button, "swap-horizontal")
        self.device_button.clicked.connect(self.switch_to_device.emit)
        bar.addWidget(self.device_button)
        self.device_bar.hide()
        return self.device_bar

    def show_device_offer(self, offer: DeviceOffer | None) -> None:
        """The device is plugged in while the daemon drives the virtual one: what to do (None: nothing to say)."""
        self.device_bar.setVisible(offer is not None)
        if offer is None:
            return
        self.device_message.setText(offer.text)
        self.device_button.setVisible(offer.action is not None)
        self.device_button.setText(offer.action or "")

    def show_test(self, running: bool) -> None:
        """Whether the test of this window runs: the button checked, and the bar of what each control does."""
        self.testing = running
        self.test_button.setChecked(running)
        self.test_bar.setVisible(running)
        self._show_mode()

    def host(self, hosted: HostedDevice | None) -> None:
        """The GUI hosts the virtual device (None: not any more): its pill, and Play on it."""
        if self.virtual_pill is not None:
            # off the screen at once, its popover with it (see `discard`)
            discard(self.virtual_slot, self.virtual_pill)
            self.virtual_pill = None
        self.hosted = hosted
        if hosted is not None:
            self.virtual_pill = VirtualDevicePill(
                hosted, self.close_virtual_device.emit, self.restart_daemon.emit, self.restart_reason
            )
            self.virtual_slot.addWidget(self.virtual_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self._show_mode()
        if hosted is not None:
            # opened to play with it
            self.play_button.setChecked(True)

    def select(self, index: int) -> None:
        """A strip of the drawing was picked: the card of its slot too."""
        self.selected = index
        self.show_live(self.snapshot)
        self.picked.emit(index + 1)

    def show_selected(self, index: int | None) -> None:
        """The strip of the slot picked on the page Slots (0 for the leftmost one), None for none: only drawn."""
        if index != self.selected:
            self.selected = index
            self.show_live(self.snapshot)

    def deselect(self) -> None:
        """Nothing picked: no strip of the drawing, and no slot on the page Slots."""
        self.selected = None
        self.show_live(self.snapshot)
        self.unpicked.emit()


class CenteredRow(QWidget):
    """
    A row of three: `left` and `right` at its ends, `middle` (while it shows) in the middle of the row, e.g. over the
    middle of the drawing under it. Where the ends need its place, it moves aside as little as it can; the room left
    for `left` cuts its texts (see `ElidedLabel`), rather than move it.
    """

    def __init__(self, left: QWidget, middle: QWidget, right: QWidget, gap: int = Space.S):
        super().__init__()
        self.left, self.middle, self.right, self.gap = left, middle, right, gap
        for part in (left, middle, right):
            part.setParent(self)  # pyright: ignore[reportArgumentType]: PyQt's stub types the parent as Self
        # shown or hidden, it takes its place or gives it back
        middle.installEventFilter(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _middle_width(self) -> int:
        return 0 if self.middle.isHidden() else self.middle.sizeHint().width() + 2 * self.gap

    def sizeHint(self) -> QSize:
        parts = (self.left, self.right) if self.middle.isHidden() else (self.left, self.middle, self.right)
        width = self.left.sizeHint().width() + self._middle_width() + self.right.sizeHint().width()
        return QSize(width, max(part.sizeHint().height() for part in parts))

    def minimumSizeHint(self) -> QSize:
        width = self.left.minimumSizeHint().width() + self._middle_width() + self.right.sizeHint().width()
        return QSize(width, self.sizeHint().height())

    def event(self, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.LayoutRequest:
            # a part changed its size (a longer text, a button shown)
            self.updateGeometry()
            self.place()
        return super().event(event)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if event is not None and event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self.updateGeometry()
            self.place()
        return False

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self.place()

    def place(self) -> None:
        width, height = self.width(), self.height()
        right_width = min(self.right.sizeHint().width(), width)
        right_x = width - right_width
        self.right.setGeometry(right_x, 0, right_width, height)
        left_end = right_x
        if not self.middle.isHidden():
            size = self.middle.sizeHint()
            centered = (width - size.width()) // 2
            # centered, also over a hint it cuts; moved right for the least the left end needs, never into the right end
            x = min(max(centered, self.left.minimumSizeHint().width() + self.gap), right_x - self.gap - size.width())
            self.middle.setGeometry(x, (height - size.height()) // 2, size.width(), size.height())
            left_end = x - self.gap
        self.left.setGeometry(0, 0, max(0, left_end), height)
