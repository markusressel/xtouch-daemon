"""
The drawing of the device, its backend for QML: the panel Device. It has the bar over the strips (Select and Play,
the pills of the live view, the mode, the virtual device, the test), the strips themselves (`Drawing`), the hands of
the mouse on the device in Play, the test of the device and the popovers of the pills.

It owns nothing of the window around it: the live view, the daemon, the preview, the virtual device the window hosts
and the daemon "Try without a device" starts are the shell's (`app.shell`, see `window/shell.py`), the status line and
the dialogs too. The panel reads them, draws them and calls the shell for what its buttons do.
"""

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon.gui.domain.looks import device_faces, twin_faces
from xtouch_daemon.gui.domain.slots import MODES
from xtouch_daemon.gui.domain.status import (
    DeviceOffer,
    Reason,
    Status,
    Tone,
    offers_virtual_device,
    play_unavailable,
    test_unavailable,
)
from xtouch_daemon.gui.domain.tokens import Entity
from xtouch_daemon.gui.quick.details import Entry, Group
from xtouch_daemon.gui.quick.device.device_test import DeviceTest
from xtouch_daemon.gui.quick.device.drawing import Drawing
from xtouch_daemon.gui.quick.device.remote_hand import RemoteHand
from xtouch_daemon.gui.quick.device.strip import Hand
from xtouch_daemon.gui.quick.device.virtual_device import HostedDevice
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import SetMode, Snapshot
from xtouch_daemon.slots.model import DEFAULT

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.app import App

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


def status_map(status: Status | None) -> dict[str, str]:
    """A status for QML: `text`, `tone` and `tip`; empty for none."""
    if status is None:
        return {}
    return {"text": status.text, "tone": status.tone.value, "tip": status.tip}


class DevicePanel(QObject):
    """See the module. QML reads it as `app.device`."""

    barChanged = pyqtSignal(arguments=[])
    """What the bar over the drawing shows changed (the pills, the buttons, the hint)."""
    hostedChanged = pyqtSignal(arguments=[])
    testChanged = pyqtSignal(arguments=[])
    snapshotChanged = pyqtSignal(object, arguments=["snapshot"])
    """The live view of the daemon showed something new (None: the daemon went away)."""

    def __init__(self, app: App) -> None:
        super().__init__(app)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.app = app
        self.shell = app.shell
        self.editor = app.editor
        self.document = app.editor.document
        live = self.shell.live
        self.device_test = DeviceTest(live)
        self.device_test.setParent(self)  # pyright: ignore[reportArgumentType]
        self.remote = RemoteHand(live)
        self.twin_hand = RemoteHand(live, preview=True)
        self.drawing = Drawing(self)
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
        self._entries: list[Entry | Group] = []
        """What the popover open now shows: its actions and toggles are called through `activate` and `toggle`."""

        self.drawing.clicked.connect(self.select)
        self.drawing.cleared.connect(self.deselect)
        self.drawing.moved.connect(self.move_slot)
        # the shell shows the state of the daemon, the preview and the file anew with every snapshot and edit
        self.shell.previewChanged.connect(self.refresh)
        self.shell.hostedChanged.connect(self.hostedChanged)
        self.shell.virtualDeviceOpened.connect(self._virtual_device_opened)
        live.twin_changed.connect(lambda _view: self.show_live(live.snapshot))
        self.device_test.changed.connect(self._test_changed)
        self.refresh()

    # -- what the drawing shows ------------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Shows the device (live while the daemon tells what it shows) and whether it runs the file."""
        shell = self.shell
        snapshot = shell.live.snapshot
        self.daemon_runs = shell.daemon is not None or shell.trying is not None
        self.show_live(snapshot)
        self.offered = offers_virtual_device(snapshot, shell.hosted is not None)
        self.live_status = shell.drawing_status()
        self.slots_status = shell.slots_status_text()
        self.offer = shell.device_offer()
        self._show_mode()
        self.snapshotChanged.emit(snapshot)

    def shows_twin(self) -> bool:
        """Whether the drawing shows the twin (the preview in the GUI), but not while the device is tested."""
        return self.shell.live_preview.in_gui and not self.device_test.running

    def show_live(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot
        twin = self.shell.live.twin
        # the virtual twin once it shows something; the device as the daemon mirrors it until then, and also while it
        # shows the preview (dark without a daemon)
        faces = twin_faces(twin) if self.shows_twin() and twin is not None else device_faces(snapshot)
        self.drawing.show_faces(faces, self.selected, simulating=self.shell.previewing())

    def _show_mode(self) -> None:
        """Which hand Play has (the hosted virtual device first), and why none while it has none."""
        shell = self.shell
        hosted = shell.hosted
        hosting = hosted is not None
        drawn = self.shows_twin()
        owned = shell.live.owned
        reason = play_unavailable(self.snapshot, owned, hosting, drawn)
        if reason is not None:
            self.drawing.device_hand = None
        else:
            hand: Hand = self.twin_hand if drawn else hosted or self.remote
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
        self._test_reason = test_unavailable(snapshot, owned)
        self._use_virtual = (
            self.daemon_runs
            and snapshot is not None
            and not snapshot.device
            and not snapshot.virtual
            and owned
            and not hosting
        )
        self.barChanged.emit()

    _play_enabled = True

    def _opens_virtual_device(self) -> bool:
        """Whether Play opens the virtual device first: the daemon waits for it, and the GUI offers to open it."""
        return self.offered and self.shell.hosted is None

    def _virtual_device_opened(self) -> None:
        """The window began to host the virtual device: it was opened to play with it."""
        self.refresh()
        self.setPlaying(True)

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
            # `_virtual_device_opened` turns Play on once it runs
            self.shell.open_virtual_device()
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
        hosted = self.shell.hosted
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

    # -- picking and moving strips ---------------------------------------------------------------------------------

    @pyqtSlot(int)
    def select(self, index: int) -> None:
        """A strip of the drawing was picked: the card of its slot too, on the page Slots."""
        self.selected = index
        self.show_live(self.snapshot)
        self.shell.show_slot(index + 1)

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
        self.app.slots.selectSlot(0)  # pyright: ignore[reportAttributeAccessIssue]

    def move_slot(self, source: int, target: int) -> None:
        """A strip was dragged to another place: its slot moves there, and stays picked (source, target from 0)."""
        self.selected = target
        self.shell.move_slot(source + 1, target + 1)
        self.show_live(self.snapshot)

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
            self.shell.tell(self.device_test.message)
        elif self.device_test.running:
            self.shell.tell("Testing the device: every strip answers its own controls.")
        else:
            self.shell.tell("The test ended: the device shows the slots again.")
        self.refresh()

    # -- the virtual device ----------------------------------------------------------------------------------------

    @pyqtSlot()
    def openVirtualDevice(self) -> None:
        """The pill of what the drawing shows was clicked: opens the virtual device while the daemon waits for it."""
        if self.offered:
            self.shell.open_virtual_device()

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
                actions = (("Open the virtual device", self.shell.open_virtual_device),) if self.offered else ()
                # the pill clicked says the status already: only what it means, in the color of its tone
                entries = [Entry("", Status("", status.tone), status.tip, actions)]
                heading = "Drawing"
            case "modes":
                shown = self._mode_entries()
                if shown is None:
                    return {}
                entries, heading, intro = shown, "Mode and states", MODES
            case "virtual":
                if self.shell.hosted is None:
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
        request = self.shell.live.send
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
        hosted = self.shell.hosted
        assert hosted is not None
        plug = ("Unplug", hosted.unplug) if hosted.plugged else ("Plug in", hosted.plug)
        status = virtual_status(hosted)
        connection = Entry(
            "Connection",
            # the pill says how it is: only its color
            Status("", status.tone),
            f"{status.tip} Switch off and on: it also forgets what it showed and starts again with its faders down. "
            "Close: unplugged, and gone from the window.",
            (plug, ("Switch off and on", hosted.power_cycle), ("Close", self.shell.close_virtual_device)),
        )
        sequences = "The daemon stops and starts again: its shutdown and startup sequences show here."
        reason = self.shell.restart_reason()
        daemon = Entry(
            "Daemon",
            text=sequences if reason is None else f"{sequences} {reason}",
            actions=(("Restart", self.shell.restart_daemon),) if reason is None else (),
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

    # -- what the buttons of the bar ask the shell for ---------------------------------------------------------------

    @pyqtSlot()
    def tryWithoutDevice(self) -> None:
        """ "Try without a device": the shell starts a daemon with the virtual device on this file."""
        self.shell.try_without_device()

    @pyqtSlot()
    def useVirtualDevice(self) -> None:
        """ "Use the virtual device" for a daemon that finds no device."""
        self.shell.use_virtual_device()

    @pyqtSlot()
    def switchToDevice(self) -> None:
        """The device is plugged in while the daemon drives the virtual one: the daemon goes to the device."""
        self.shell.switch_to_device()

    # -- the end -------------------------------------------------------------------------------------------------

    @pyqtSlot()
    def shutdown(self) -> None:
        """The window closes: the test ends (the shell ends the preview, the virtual device and the trial)."""
        self.device_test.stop()


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
