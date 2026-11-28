"""
The drawing of the device, its backend for QML: the window Device. It is the `DeviceView` of the widgets
(`gui/qt/window/device_view.py`) with what the main window does around it for the device: the live view of the
daemon, the preview of the unsaved changes (where it shows: in the GUI, on the device or off), the test of the
device, the virtual device the GUI hosts, the daemon "Try without a device" starts, and the hand the mouse is on the
device in Play.

What the shell has to give it (all optional, see `DevicePanel`): the status line (`message`), the dialogs (`warning`,
`confirm`), saving the file (`save`) and restarting the service (`restart_service`).
"""

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import (  # pyright: ignore[reportUnknownVariableType]
    QFileSystemWatcher,
    QObject,
    QProcess,
    QTimer,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
)

from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.live_preview import Place, previewed, unavailable
from xtouch_daemon.gui.domain.looks import device_faces, twin_faces
from xtouch_daemon.gui.domain.slots import MODES, slots_status
from xtouch_daemon.gui.domain.status import (
    DeviceOffer,
    Reason,
    Status,
    Switch,
    Tone,
    device_offer,
    drawing_status,
    offers_virtual_device,
    play_unavailable,
    preview_status,
    test_unavailable,
)
from xtouch_daemon.gui.domain.twin import unavailable as twin_unavailable
from xtouch_daemon.gui.qt.device_test import DeviceTest
from xtouch_daemon.gui.qt.fields.popover import Entry, Group
from xtouch_daemon.gui.qt.live_preview import LivePreview
from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.gui.qt.preview.panel import Hand
from xtouch_daemon.gui.qt.remote_hand import RemoteHand
from xtouch_daemon.gui.qt.theme.tokens import Entity
from xtouch_daemon.gui.qt.virtual_device import HostedDevice
from xtouch_daemon.gui.quick.device.drawing import Drawing
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import SetMode, Snapshot
from xtouch_daemon.simulator.server import AlreadyServed
from xtouch_daemon.slots.model import DEFAULT
from xtouch_daemon.system import instance
from xtouch_daemon.system.instance import Instance
from xtouch_daemon.system.systemd import ServiceError

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.app import App

SERVICE_POLL_MS = 3000
"""How often the daemon is looked for (it is also looked for when its live view appears)."""
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
TRY_TIP = (
    "Starts a daemon with the virtual device, here in the window, to set everything up and play with it "
    "before there is a device. It stops when the window closes."
)
VIRTUAL_TIP = (
    "The daemon runs, but finds no device: it drives the virtual device instead, here in the window, without a "
    "restart. Saves the file with `[device] virtual = true` (Virtual, on the page Extender)."
)
PLACE_TEXTS = {Place.GUI: "In the GUI", Place.DEVICE: "On the device", Place.OFF: "Off"}
"""The positions of the control "Preview", from the left."""
PLACE_TIPS = {
    Place.GUI: (
        "Shows the changes, and Simulate while it is open, here in the window: on a twin of the device in the daemon. "
        "The device keeps running the saved file."
    ),
    Place.DEVICE: (
        "Runs the changes, and Simulate while it is open, on the device before they are saved: the device changes. "
        "It runs the saved file again once you pick another place or close the window."
    ),
    Place.OFF: (
        "Shows the device as it is: it runs the saved file. The changes show nowhere until you save them or pick "
        "another place."
    ),
}
"""What each position of the control "Preview" does."""


def status_map(status: Status | None) -> dict[str, str]:
    """A status for QML: `text`, `tone` and `tip`; empty for none."""
    if status is None:
        return {}
    return {"text": status.text, "tone": status.tone.value, "tip": status.tip}


class DevicePanel(QObject):
    """See the module. QML reads it as `app.device`."""

    barChanged = pyqtSignal(arguments=[])
    """What the bar over the drawing shows changed (the pills, the buttons, the hint)."""
    placeChanged = pyqtSignal(arguments=[])
    """Where the preview shows, or what it says, changed (see `places`)."""
    hostedChanged = pyqtSignal(arguments=[])
    testChanged = pyqtSignal(arguments=[])
    snapshotChanged = pyqtSignal(object, arguments=["snapshot"])
    """The live view of the daemon showed something new (None: the daemon went away)."""
    message = pyqtSignal(str, arguments=["text"])
    """Something for the status line of the window."""
    warning = pyqtSignal(str, str, arguments=["title", "text"])
    """Something that went wrong, for a dialog."""
    picked = pyqtSignal(int, arguments=["slot"])
    """A strip of the drawing was picked: its slot (from 1)."""
    unpicked = pyqtSignal(arguments=[])
    """The drawing was clicked beside the strips."""
    slotMoved = pyqtSignal(int, int, arguments=["source", "target"])
    """A strip was dragged to another place: its slot moved (slots from 1)."""

    def __init__(self, app: App) -> None:
        super().__init__(app)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.app = app
        deps = app.deps
        self.editor = app.editor
        self.document = app.editor.document
        self.find_daemon: Callable[[], Instance | None] = deps.find_daemon
        self.virtual_socket = deps.virtual_socket or instance.virtual_device_socket_file()
        # what the shell gives it (see the module); the defaults say it in the status line
        self.say: Callable[[str], None] = self.message.emit
        self.warn: Callable[[str, str], None] = self.warning.emit
        self.confirm: Callable[[str, str], bool] = lambda title, question: False
        """Asks a question with a Yes and a No; the shell shows the dialog."""
        self.save: Callable[[], bool] = lambda: False
        """Saves and applies the file, False when it could not be saved."""
        self.restart_service: Callable[[], None] = self._restart_service

        self.daemon: Instance | None = None
        self.live = LiveView(deps.live_socket or instance.socket_file(), self)
        self.live_preview = LivePreview(self.live, self.document)
        self.live_preview.setParent(self)  # pyright: ignore[reportArgumentType]
        self.device_test = DeviceTest(self.live)
        self.device_test.setParent(self)  # pyright: ignore[reportArgumentType]
        self.remote = RemoteHand(self.live)
        self.twin_hand = RemoteHand(self.live, preview=True)
        self.drawing = Drawing(self)
        self.hosted: HostedDevice | None = None
        """The virtual device while the GUI hosts it (see `open_virtual_device()`)."""
        self.trying: QProcess | None = None
        """The daemon started by "Try without a device", with the virtual device; it ends with the window."""
        self.restarting_trial = False
        """Whether the daemon of `trying` stops to start again (see `restart_daemon`)."""
        session = deps.session
        self.resume_place = Place(session.preview) if session is not None else None
        self.selected: int | None = None
        """The strip picked (0 for the leftmost one), None for none."""
        self.snapshot: Snapshot | None = None
        """What the live view showed last, while the drawing is shown."""
        self.testing = False
        self.daemon_runs = True
        self.offered = False
        self.live_status: Status | None = None
        self.slots_status: Status | None = None
        self.offer: DeviceOffer | None = None
        self._mode_text = ""
        self._hand_status: Status | None = None
        self._play_reason: Reason | None = None
        self._test_reason: Reason | None = None
        self._try = False
        self._use_virtual = False
        self._place_note = ""
        self._preview_message = ""
        self._preview_shown = False
        self._places: list[dict[str, Any]] = []
        self._entries: list[Entry | Group] = []
        """What the popover open now shows: its actions and toggles are called through `activate` and `toggle`."""

        self.drawing.clicked.connect(self.select)
        self.drawing.cleared.connect(self.deselect)
        self.drawing.moved.connect(self.move_slot)
        self.live.changed.connect(lambda _snapshot: self.refresh())
        self.live.twin_changed.connect(lambda _view: self.show_live(self.live.snapshot))
        self.live_preview.changed.connect(self.refresh)
        self.device_test.changed.connect(self._test_changed)
        self.editor.changed.connect(self._document_changed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_service)
        self.timer.start(SERVICE_POLL_MS)
        # a daemon that starts: its live view at once, not at the next poll, so the drawing shows its startup sequence
        self._live_socket_there = self.live.path.exists()
        self.runtime_watch: QFileSystemWatcher | None = None
        if self.live.path.parent.is_dir():
            self.runtime_watch = QFileSystemWatcher([str(self.live.path.parent)], self)
            self.runtime_watch.directoryChanged.connect(self._runtime_changed)
        if session is not None and session.trying is not None:
            self._keep_trying(session.trying)
        self.refresh_service()

    # -- the daemon ----------------------------------------------------------------------------------------------

    def _runtime_changed(self, _directory: str) -> None:
        """Something changed in the directory of the live view: the daemon may have started or stopped."""
        there = self.live.path.exists()
        if there != self._live_socket_there:
            self._live_socket_there = there
            self.refresh_service()

    @pyqtSlot()
    def refresh_service(self) -> None:
        """Finds the daemon (and its live view) again."""
        self.daemon = self.find_daemon()
        if self.daemon is None:
            self.live.disconnect_from_daemon()
        else:
            self.live.connect_to_daemon()
        self.refresh()

    def _restart_service(self) -> None:
        try:
            self.app.deps.service.restart()
        except ServiceError as e:
            self.warn("Service", str(e))
            return
        self.say("Restarting the service…")
        self.refresh_service()

    def restart_reason(self) -> str | None:
        """Why `restart_daemon` can't restart the daemon, None when it can."""
        if self.trying is not None:
            return None
        if self.daemon is None:
            return "No daemon runs now."
        if not self.daemon.systemd:
            return f"This daemon runs outside the service (process {self.daemon.pid}): restart it where it runs."
        return None

    def restart_daemon(self) -> None:
        """
        The daemon that drives the hosted virtual device stops and starts again, so its shutdown and startup sequences
        show on it: the daemon of "Try without a device", or the service.
        """
        if self.trying is not None:
            self.restarting_trial = True
            self.trying.terminate()
            self.say("Stopping the daemon for trying without a device, to start it again…")
            return
        self.restart_service()

    # -- what the drawing shows ------------------------------------------------------------------------------------

    def _document_changed(self, _change: object) -> None:
        self.live_preview.document_changed()
        self.refresh()

    def refresh(self) -> None:
        """Shows the device (live while the daemon tells what it shows) and whether it runs the file."""
        snapshot = self.live.snapshot
        if self.trying is not None and offers_virtual_device(snapshot, self.hosted is not None):
            # the daemon started to try without a device waits for its device: here it is
            self.open_virtual_device()
        self.daemon_runs = self.daemon is not None or self.trying is not None
        self._show_live_preview(snapshot)
        self.show_live(snapshot)
        shows_document = previewed(snapshot, self.editor.validation.config, self.live_preview.running)
        saved = self.document.saved_config
        device = saved.device.name if saved is not None else "the device"
        hosting = self.hosted is not None
        on_device = self.live_preview.on and (shows_document or self._device_simulates(snapshot))
        self.offered = offers_virtual_device(snapshot, hosting)
        self.live_status = drawing_status(
            preview_status(self.daemon, snapshot, device, hosting), self.live_preview.in_gui, on_device
        )
        self.slots_status = slots_status(snapshot)
        self.offer = self._device_offer()
        self._show_mode()
        self.snapshotChanged.emit(snapshot)

    def _device_simulates(self, snapshot: Snapshot | None) -> bool:
        """Whether the device shows the situation of Simulate of this window."""
        preview = self.live_preview
        return preview.on and preview.simulating and snapshot is not None and snapshot.simulated

    def previewing(self) -> bool:
        """Whether the drawing shows a preview of this window: on its twin, or on the device."""
        preview = self.live_preview
        snapshot = self.live.snapshot
        config = self.editor.validation.config
        on_device = previewed(snapshot, config, preview.running) or self._device_simulates(snapshot)
        return preview.in_gui or (preview.on and on_device)

    def shows_twin(self) -> bool:
        """Whether the drawing shows the twin (the preview in the GUI), but not while the device is tested."""
        return self.live_preview.in_gui and not self.device_test.running

    def show_live(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot
        twin = self.live.twin
        # the virtual twin once it shows something; the device as the daemon mirrors it until then, and also while it
        # shows the preview (dark without a daemon)
        faces = twin_faces(twin) if self.shows_twin() and twin is not None else device_faces(snapshot)
        self.drawing.show_faces(faces, self.selected, simulating=self.previewing())

    def _show_live_preview(self, snapshot: Snapshot | None) -> None:
        """Where the preview can show (a place it can't show in says why), and what the daemon said about it."""
        preview = self.live_preview
        device_reason = unavailable(self.daemon, snapshot, self.document.path, self.live.owned)
        gui_reason = twin_unavailable(snapshot, self.live.owned)
        if device_reason is not None and preview.place == Place.DEVICE:
            preview.set_place(Place.GUI)
        elif self.resume_place is not None and (device_reason is None or self.resume_place != Place.DEVICE):
            place, self.resume_place = self.resume_place, None
            preview.set_place(place)
        self._preview_shown = preview.wanted or preview.running
        self._place_note = (
            "On the device" if preview.on else "In the GUI" if gui_reason is None else f"Nowhere: {gui_reason.short}"
        )
        reasons = {Place.GUI: gui_reason, Place.DEVICE: device_reason, Place.OFF: None}
        self._places = [
            {
                "place": place.value,
                "text": PLACE_TEXTS[place],
                "checked": place == preview.place,
                "enabled": reasons[place] is None,
                "tip": PLACE_TIPS[place] if reasons[place] is None else f"{reasons[place].why}\n\n{PLACE_TIPS[place]}",  # type: ignore[union-attr]
            }
            for place in PLACE_TEXTS
        ]
        error = f"The preview keeps the version before: {preview.error}" if preview.error else preview.notice
        self._preview_message = error or ""
        self.placeChanged.emit()

    def _show_mode(self) -> None:
        """Which hand Play has (the hosted virtual device first), and why none while it has none."""
        hosting = self.hosted is not None
        drawn = self.shows_twin()
        reason = play_unavailable(self.snapshot, self.live.owned, hosting, drawn)
        if reason is not None:
            self.drawing.device_hand = None
        else:
            hand: Hand = self.twin_hand if drawn else self.hosted or self.remote
            self.drawing.device_hand = hand
        if reason is not None and self.drawing.playing:
            self.drawing.set_playing(False)
        if self._opens_virtual_device():
            reason = Reason(
                "opens the virtual device",
                "The daemon drives the virtual device, which does not run: Play opens it here and plays on it.",
            )
            self._play_enabled = True
        else:
            self._play_enabled = reason is None
        self._play_reason = reason
        playing = self.drawing.playing
        self._hand_status = self._hand(hosting, drawn) if playing else None
        if playing:
            hint = "Playing on"
        else:
            hint = "Drag a strip to move its slot"
            if reason is not None:
                # why Play is off, next to it rather than in its tooltip only
                hint += f"  ·  Play: {reason.short}"
        self._mode_text = hint
        self._try = not self.daemon_runs and not hosting
        snapshot = self.snapshot
        self._test_reason = test_unavailable(snapshot, self.live.owned)
        self._use_virtual = (
            self.daemon_runs
            and snapshot is not None
            and not snapshot.device
            and not snapshot.virtual
            and self.live.owned
            and not hosting
        )
        self.barChanged.emit()

    _play_enabled = True

    def _opens_virtual_device(self) -> bool:
        """Whether Play opens the virtual device first: the daemon waits for it, and the GUI offers to open it."""
        return self.offered and self.hosted is None

    def _hand(self, hosting: bool, drawn: bool) -> Status:
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

    # -- the bar over the drawing ----------------------------------------------------------------------------------

    @pyqtProperty(QObject, constant=True)
    def drawingModel(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """The strips (`Drawing`): the items of QML paint them."""
        return self.drawing

    @pyqtProperty(bool, notify=barChanged)
    def playing(self) -> bool:  # pyright: ignore[reportRedeclaration]
        """Play: the mouse is a hand on the device. Else Select: a click picks a strip, a drag moves its slot."""
        return self.drawing.playing

    @pyqtSlot(bool)
    def setPlaying(self, playing: bool) -> None:
        """Play (true) or Select. Play on a daemon that waits for the virtual device opens it, and plays on it then."""
        if playing and self._opens_virtual_device():
            # `host` turns Play on once it runs
            self._mode_clicked()
            return
        if playing != self.drawing.playing:
            self.drawing.set_playing(playing)
            self.show_live(self.snapshot)
        self._show_mode()

    @pyqtProperty(str, constant=True)
    def selectTip(self) -> str:  # pyright: ignore[reportRedeclaration]
        return SELECT_TIP

    @pyqtProperty(bool, notify=barChanged)
    def playEnabled(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._play_enabled

    @pyqtProperty(str, notify=barChanged)
    def playTip(self) -> str:  # pyright: ignore[reportRedeclaration]
        reason = self._play_reason
        return PLAY_TIP if reason is None else f"{reason.why}\n\n{PLAY_TIP}"

    @pyqtProperty(str, notify=barChanged)
    def modeHint(self) -> str:  # pyright: ignore[reportRedeclaration]
        """What Select or Play does now, and why Play is off while it is."""
        return self._mode_text

    @pyqtProperty(str, notify=barChanged)
    def modeHintTip(self) -> str:  # pyright: ignore[reportRedeclaration]
        reason = self._play_reason
        return reason.why if reason is not None and not self.drawing.playing else ""

    @pyqtProperty("QVariantMap", notify=barChanged)
    def handStatus(self) -> dict[str, str]:  # pyright: ignore[reportRedeclaration]
        """In Play: what the mouse plays on (empty in Select)."""
        return status_map(self._hand_status)

    @pyqtProperty("QVariantMap", notify=barChanged)
    def liveStatus(self) -> dict[str, str]:  # pyright: ignore[reportRedeclaration]
        """Whether the drawing is live or shows the file."""
        return status_map(self.live_status)

    @pyqtProperty("QVariantMap", notify=barChanged)
    def modeStatus(self) -> dict[str, str]:  # pyright: ignore[reportRedeclaration]
        """The mode the device shows; empty without slots."""
        return status_map(self.slots_status)

    @pyqtProperty("QVariantMap", notify=hostedChanged)
    def virtualStatus(self) -> dict[str, str]:  # pyright: ignore[reportRedeclaration]
        """How the hosted virtual device is connected; empty while the GUI hosts none."""
        hosted = self.hosted
        if hosted is None:
            return {}
        status = virtual_status(hosted)
        return status_map(Status(f"Virtual device · {status.text}", status.tone, status.tip))

    @pyqtProperty(bool, notify=barChanged)
    def testVisible(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self.daemon_runs

    @pyqtProperty(bool, notify=barChanged)
    def testEnabled(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self.testing or self._test_reason is None

    @pyqtProperty(str, notify=barChanged)
    def testTip(self) -> str:  # pyright: ignore[reportRedeclaration]
        reason = self._test_reason
        return TEST_TIP if reason is None else f"{reason.why}\n\n{TEST_TIP}"

    @pyqtProperty(bool, notify=testChanged)
    def testRunning(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self.testing

    @pyqtProperty(str, constant=True)
    def testHelp(self) -> str:  # pyright: ignore[reportRedeclaration]
        return TEST_HELP

    @pyqtProperty(bool, notify=barChanged)
    def tryVisible(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._try

    @pyqtProperty(str, constant=True)
    def tryTip(self) -> str:  # pyright: ignore[reportRedeclaration]
        return TRY_TIP

    @pyqtProperty(bool, notify=barChanged)
    def useVirtualVisible(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._use_virtual

    @pyqtProperty(str, constant=True)
    def useVirtualTip(self) -> str:  # pyright: ignore[reportRedeclaration]
        return VIRTUAL_TIP

    @pyqtProperty("QVariantMap", notify=barChanged)
    def deviceOffer(self) -> dict[str, str]:  # pyright: ignore[reportRedeclaration]
        """The device is plugged in while the daemon drives the virtual one: `text` and `action` (empty for none)."""
        offer = self.offer
        return {} if offer is None else {"text": offer.text, "action": offer.action or ""}

    # -- where the preview shows (the control "Preview" of the shell) ------------------------------------------------

    @pyqtProperty(str, notify=placeChanged)
    def place(self) -> str:  # pyright: ignore[reportRedeclaration]
        """Where the preview shows: `gui` (on a twin in the daemon), `device` or `off`."""
        return self.live_preview.place.value

    @pyqtSlot(str)
    def setPlace(self, place: str) -> None:
        self.live_preview.set_place(Place(place))

    @pyqtProperty("QVariantList", notify=placeChanged)
    def places(self) -> list[dict[str, Any]]:  # pyright: ignore[reportRedeclaration]
        """The positions of the control "Preview": `place`, `text`, `checked`, `enabled`, `tip`."""
        return self._places

    @pyqtProperty(bool, notify=placeChanged)
    def previewShown(self) -> bool:  # pyright: ignore[reportRedeclaration]
        """Whether there is something to preview (or it runs): the control shows."""
        return self._preview_shown

    @pyqtProperty(str, notify=placeChanged)
    def previewMessage(self) -> str:  # pyright: ignore[reportRedeclaration]
        """What the daemon said about the preview (it keeps the version before, or why it ended); empty for nothing."""
        return self._preview_message

    @pyqtProperty(str, notify=placeChanged)
    def placeNote(self) -> str:  # pyright: ignore[reportRedeclaration]
        """Where Simulate shows, for its bar: "In the GUI", "On the device" or "Nowhere: ..."."""
        return self._place_note

    # -- picking and moving strips ---------------------------------------------------------------------------------

    @pyqtSlot(int)
    def select(self, index: int) -> None:
        """A strip of the drawing was picked: the card of its slot too."""
        self.selected = index
        self.show_live(self.snapshot)
        self.picked.emit(index + 1)
        self.app.showPage("slots")
        self.app.slots.selectSlot(index + 1)  # pyright: ignore[reportAttributeAccessIssue]

    @pyqtSlot(int)
    def showSelected(self, index: int) -> None:
        """The strip of the slot picked on the page Slots (0 for the leftmost one), -1 for none: only drawn."""
        shown = index if index >= 0 else None
        if shown != self.selected:
            self.selected = shown
            self.show_live(self.snapshot)

    @pyqtSlot()
    def deselect(self) -> None:
        """Nothing picked: no strip of the drawing, and no slot on the page Slots."""
        self.selected = None
        self.show_live(self.snapshot)
        self.unpicked.emit()
        self.app.slots.selectSlot(0)  # pyright: ignore[reportAttributeAccessIssue]

    def move_slot(self, source: int, target: int) -> None:
        """A strip was dragged to another place: its slot moves there, and stays picked (source, target from 0)."""
        self.slotMoved.emit(source + 1, target + 1)
        self.editor.move_slot(source + 1, target + 1)
        self.say(f"Moved slot {source + 1} to {target + 1}. Ctrl+Z moves it back.")
        self.select(target)

    # -- the test of the device ------------------------------------------------------------------------------------

    @pyqtSlot(bool)
    def toggleTest(self, on: bool) -> None:
        """ "Test the device": the daemon tests it for this window (on), or the device shows the slots again."""
        if on:
            self.device_test.start()
        else:
            self.device_test.stop()

    def _test_changed(self) -> None:
        self.testing = self.device_test.running
        self.testChanged.emit()
        if self.device_test.message is not None:
            self.say(self.device_test.message)
        elif self.device_test.running:
            self.say("Testing the device: every strip answers its own controls.")
        else:
            self.say("The test ended: the device shows the slots again.")
        self.refresh()

    # -- the virtual device ----------------------------------------------------------------------------------------

    def _mode_clicked(self) -> None:
        if offers_virtual_device(self.live.snapshot, self.hosted is not None):
            self.open_virtual_device()

    @pyqtSlot()
    def openVirtualDevice(self) -> None:
        """The pill of what the drawing shows was clicked: opens the virtual device while the daemon waits for it."""
        self._mode_clicked()

    @pyqtSlot()
    def open_virtual_device(self) -> None:
        """Hosts the virtual device, for a daemon that waits for it: the mouse on the drawing is a hand on it."""
        hosted = HostedDevice(self.virtual_socket, self)
        try:
            hosted.start()
        except (AlreadyServed, OSError) as e:
            hosted.deleteLater()
            self.warn("Virtual device", str(e))
            return
        self.hosted = hosted
        hosted.changed.connect(self.hostedChanged)
        self.hostedChanged.emit()
        self.refresh()
        # opened to play with it
        self.setPlaying(True)

    @pyqtSlot()
    def close_virtual_device(self) -> None:
        """Unplugs the hosted virtual device and closes it."""
        if self.hosted is None:
            return
        self.hosted.stop()
        self.hosted.deleteLater()
        self.hosted = None
        self.hostedChanged.emit()
        self.refresh()

    @pyqtSlot(str, result="QVariantMap")
    def popover(self, kind: str) -> dict[str, Any]:
        """
        What a popover of the bar shows (`kind`: `live`, `modes` or `virtual`): its `heading`, `intro` and `entries`,
        each with `title`, `tone`, `statusText`, `text`, `actions`, `toggles` and `entity`. Empty for none.
        """
        entries: list[Entry | Group]
        intro = ""
        match kind:
            case "live":
                if self.live_status is None:
                    return {}
                status = self.live_status
                actions = (("Open the virtual device", self.open_virtual_device),) if self.offered else ()
                # the pill clicked says the status already: only what it means, in the color of its tone
                entries = [Entry("", Status("", status.tone), status.tip, actions)]
                heading = "Drawing"
            case "modes":
                shown = self._mode_entries()
                if shown is None:
                    return {}
                entries, heading, intro = shown, "Mode and states", MODES
            case "virtual":
                if self.hosted is None:
                    return {}
                entries, heading = self.virtual_entries(), "Virtual device"
            case _:
                return {}
        self._entries = entries
        return {"heading": heading, "intro": intro, "entries": [entry_map(entry) for entry in entries]}

    @pyqtSlot(int, int)
    def activate(self, entry: int, action: int) -> None:
        """A button of the popover open now was pressed (the popover closed first)."""
        shown = self._entries[entry]
        assert isinstance(shown, Entry)
        shown.actions[action][1]()

    @pyqtSlot(int, int, bool)
    def toggle(self, entry: int, toggle: int, on: bool) -> None:
        """A switch of the popover open now was flipped: it stays open."""
        shown = self._entries[entry]
        assert isinstance(shown, Entry)
        shown.toggles[toggle][2](on)

    def _mode_entries(self) -> list[Entry | Group] | None:
        """The mode, the modes to pick (or back to the rules) and the states, with what turned them on."""
        slots = self.snapshot.slots if self.snapshot is not None else None
        if slots is None or self.slots_status is None:
            return None
        request = self.live.send
        modes = [DEFAULT, *(state.name for state in slots.states if state.mode)]
        picks = tuple(
            ("Pick no mode" if mode == DEFAULT else f"Pick {mode}", lambda mode=mode: request(SetMode(mode)))
            for mode in modes
            if mode != slots.mode
        )
        if slots.mode_pick is not None:
            picks += (("Back to the rules", lambda: request(SetMode("auto"))),)
        how = "Picked by hand, until the rules want another one." if slots.mode_pick else "The rules pick it."
        # what a mode is goes above, as the intro: the row says only what holds now
        entries: list[Entry | Group] = [Entry("Mode", self.slots_status, how, picks, Entity.STATE)]
        states = [state for state in slots.states if not state.mode]
        if states:
            entries.append(Group("States", "Not modes: each is on or off by itself, also several at once."))
        for state in states:
            value = Status("on", Tone.GOOD) if state.value else Status("off", Tone.NEUTRAL)
            why = state.source or "none of its sources is on"
            why = why[:1].upper() + why[1:]
            override = "" if state.override == "auto" else f" Overridden: {state.override}."
            entries.append(Entry(state.name, value, f"{why}.{override}", entity=Entity.STATE))
        return entries

    def virtual_entries(self) -> list[Entry | Group]:
        """What the popover of the hosted virtual device opens: the connection, the daemon and the touch sensors."""
        hosted = self.hosted
        assert hosted is not None
        plug = ("Unplug", hosted.unplug) if hosted.plugged else ("Plug in", hosted.plug)
        status = virtual_status(hosted)
        connection = Entry(
            "Connection",
            # the pill says how it is: only its color
            Status("", status.tone),
            f"{status.tip} Switch off and on: it also forgets what it showed and starts again with its faders down. "
            "Close: unplugged, and gone from the window.",
            (plug, ("Switch off and on", hosted.power_cycle), ("Close", self.close_virtual_device)),
        )
        sequences = "The daemon stops and starts again: its shutdown and startup sequences show here."
        reason = self.restart_reason()
        daemon = Entry(
            "Daemon",
            text=sequences if reason is None else f"{sequences} {reason}",
            actions=(("Restart", self.restart_daemon),) if reason is None else (),
        )
        broken = Entry(
            "Broken touch",
            text="Faders whose touch sensor failed never report a touch, e.g. to try `touchless_faders`.",
            toggles=tuple(
                (
                    str(strip + 1),
                    strip in hosted.device.broken_touch,
                    lambda on, strip=strip, hosted=hosted: hosted.set_broken_touch(strip, on),
                )
                for strip in range(protocol.STRIPS)
            ),
        )
        return [connection, daemon, broken]

    # -- the daemon of "Try without a device" --------------------------------------------------------------------------

    @pyqtSlot()
    def tryWithoutDevice(self) -> None:
        """
        Starts a daemon with the virtual device on this file (saved first if it is new), and opens the device in the
        window once the daemon waits for it (see `refresh`).
        """
        if self.trying is not None:
            return
        if not self.document.exists and not self.save():
            return
        self._start_trial()
        self.say("Starting a daemon with the virtual device…")

    def _start_trial(self) -> None:
        process = QProcess()
        process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)
        process.start(
            sys.executable, ["-m", "xtouch_daemon", "run", "--virtual-device", "--config", str(self.document.path)]
        )
        self._keep_trying(process)

    def _keep_trying(self, process: QProcess) -> None:
        """The daemon to try without a device is this window's: it ends with it."""
        process.setParent(self)  # pyright: ignore[reportArgumentType]
        self.trying_ended = process.finished.connect(lambda code, _status: self._tried(process, code))
        self.trying = process

    def _tried(self, process: QProcess, code: int) -> None:
        if self.trying is not process:
            return
        self.trying = None
        process.deleteLater()
        if self.restarting_trial:
            self.restarting_trial = False
            self._start_trial()
            self.say("Starting the daemon for trying without a device again…")
            return
        self.say(f"The daemon for trying without a device ended (exit code {code}).")
        self.refresh_service()

    @pyqtSlot()
    def useVirtualDevice(self) -> None:
        """
        For a daemon that finds no device: `[device] virtual = true`, saved (the daemon takes it when it reloads,
        without a restart), and the virtual device opened here.
        """
        if self.daemon is None or self.document.path.resolve() != self.daemon.config:
            self.say("The daemon reads another file: set Virtual on the page Extender of that one.")
            return
        self.document.set(("device", "virtual"), True)
        self.editor.edited(Change(Scope.VALUE, ("device", "virtual")))
        if self.save():
            self.open_virtual_device()

    def _device_offer(self) -> DeviceOffer | None:
        """What the window offers while the device is plugged in and the daemon drives the virtual one."""
        saved = self.document.saved_config
        device = saved.device.name if saved is not None else "the device"
        file_virtual = saved is not None and saved.device.virtual
        return device_offer(self.live.snapshot, device, file_virtual, self.trying is not None)

    @pyqtSlot()
    def switchToDevice(self) -> None:
        """
        The device is plugged in while the daemon drives the virtual one: the daemon goes to the device. With
        `[device] virtual` in the file, it is turned off and the file applied (no restart); the daemon of the window,
        to try without a device, ends instead (the service, started then, takes the device).
        """
        offer = self._device_offer()
        if offer is None:
            return
        match offer.switch:
            case Switch.TRIAL:
                # ended on purpose: not the message of a daemon that ended (`_tried`)
                trying, self.trying = self.trying, None
                assert trying is not None
                trying.finished.connect(trying.deleteLater)
                trying.terminate()
                self.say("Ending the trial: start the service to use the device.")
                self.refresh_service()
            case Switch.FILE:
                if self.daemon is None or self.document.path.resolve() != self.daemon.config:
                    self.say("The daemon reads another file: turn Virtual off on its page Extender.")
                    return
                if self.document.modified:
                    question = "Switching saves the file: your other changes too. Save them and switch to the device?"
                    if not self.confirm("Switch to the device", question):
                        return
                self.document.unset(("device", "virtual"))
                self.editor.edited(Change(Scope.VALUE, ("device", "virtual")))
                if self.save():
                    self.close_virtual_device()
            case Switch.RESTART:
                # nothing the window can do: the bar says so
                return

    # -- the end -------------------------------------------------------------------------------------------------

    def keep_trying_for_next_window(self) -> QProcess | None:
        """The daemon of the trial, let go of this window for the next one (a new zoom) to take over."""
        trying = self.trying
        if trying is not None:
            trying.finished.disconnect(self.trying_ended)
            trying.setParent(None)  # pyright: ignore[reportArgumentType]
        return trying

    @pyqtSlot()
    def shutdown(self) -> None:
        """The window closes: the preview ends (the device runs the file again), the test, the virtual device."""
        self.live_preview.stop()
        self.device_test.stop()
        self.close_virtual_device()
        self.timer.stop()
        trying = self.trying
        if trying is not None:
            self.trying = None
            trying.terminate()
            trying.waitForFinished(3000)


def virtual_status(hosted: HostedDevice) -> Status:
    """How the hosted virtual device is connected (the pill of its popover)."""
    if not hosted.plugged:
        return Status("unplugged", Tone.WARN, "The daemon can't find it until it is plugged in again.")
    if hosted.host is None:
        return Status("waiting for the daemon", Tone.NEUTRAL, "Plugged in: the daemon finds it within seconds.")
    return Status(
        "connected",
        Tone.GOOD,
        "The daemon drives it, and the mouse is a hand on it in Play (Alt-drag moves a fader without a touch).",
    )


def entry_map(entry: Entry | Group) -> dict[str, Any]:
    """A row of a popover for QML."""
    if isinstance(entry, Group):
        return {"group": True, "title": entry.title, "text": entry.text}
    status = entry.status
    return {
        "group": False,
        "title": entry.title,
        "tone": status.tone.value if status is not None else "",
        "statusText": status.text if status is not None else "",
        "text": entry.text or (status.tip if status is not None else ""),
        "actions": [text for text, _ in entry.actions],
        "toggles": [{"text": text, "on": on} for text, on, _ in entry.toggles],
        "entity": entry.entity.value if entry.entity is not None else "",
        "path": entry.path or "",
        "items": [{"item": item, "note": note} for item, note in entry.items],
    }
