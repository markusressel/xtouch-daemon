"""
The virtual device the GUI hosts: the daemon on its socket, the mouse on the drawing as a hand, its pill and popover,
the offer in the pill while the daemon waits for it, and the way back to the device once it is plugged in.
"""

import dataclasses
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QPoint, QPointF, QProcess, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtNetwork import QLocalSocket
from pytestqt.qtbot import QtBot

from tests.gui.quick.conftest import MakeUi
from tests.gui.quick.device_support import FakeHand, Stage, device_of, drawing_of, live_ui, snapshot  # noqa: F401
from tests.support.dialogs import FakeDialogs
from tests.support.gui import FakeLiveDaemon, led_point
from tests.support.instance import RecordingInstance
from tests.support.quick import Ui
from tests.support.systemd import FakeSystemctl
from xtouch_daemon.gui.domain.looks import UNKNOWN
from xtouch_daemon.gui.domain.slots_document import SlotsDocument
from xtouch_daemon.gui.qt.preview.geometry import ENCODER, SLOT, button_rect, fraction_at, part_at, travel_y
from xtouch_daemon.gui.qt.preview.strip_view import HOVER_TIPS
from xtouch_daemon.gui.qt.virtual_device import HostedDevice
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.simulator.server import AlreadyServed
from xtouch_daemon.system.systemd import UNIT_NAME


@pytest.fixture
def hosted(qtbot: QtBot, socket_dir: Path) -> HostedDevice:
    device = HostedDevice(socket_dir / "virtual-device.sock")
    device.start()
    return device


def connect(qtbot: QtBot, hosted: HostedDevice) -> QLocalSocket:
    """The daemon, connected to the hosted device."""
    daemon = QLocalSocket()
    daemon.connectToServer(str(hosted.path))
    qtbot.waitUntil(lambda: hosted.host is not None)
    return daemon


def test_the_daemon_drives_the_hosted_device(qtbot: QtBot, hosted: HostedDevice) -> None:
    daemon = connect(qtbot, hosted)
    daemon.write(protocol.lcd_text(0, 0, "Mic"))
    qtbot.waitUntil(lambda: hosted.device.text(0)[0] == "Mic    ")

    # a hand on it: the daemon hears of it
    hosted.touch(0, True)
    hosted.move(0, 0.5)
    hosted.press(0, Button.MUTE, True)
    hosted.turn(0, 1)
    hosted.push(0, True)
    expected = (
        protocol.fader_touched(0, True)
        + protocol.fader_moved(0, protocol.fader_value(0.5))
        + protocol.button(0, Button.MUTE, True)
        + protocol.encoder_turned(0, 1)
        + protocol.encoder_pressed(0, True)
    )
    received = bytearray()

    def arrived() -> bool:
        received.extend(daemon.readAll().data())
        return bytes(received) == expected

    qtbot.waitUntil(arrived)
    hosted.stop()
    hosted.stop()
    assert not hosted.path.exists()


def test_one_daemon_at_a_time(qtbot: QtBot, hosted: HostedDevice) -> None:
    first = connect(qtbot, hosted)
    second = QLocalSocket()
    second.connectToServer(str(hosted.path))
    qtbot.waitUntil(lambda: second.state() == QLocalSocket.LocalSocketState.UnconnectedState)

    assert hosted.host is not None
    first.disconnectFromServer()
    qtbot.waitUntil(lambda: hosted.host is None)
    hosted.stop()


def test_another_virtual_device_or_a_socket_left_behind(qtbot: QtBot, socket_dir: Path) -> None:
    path = socket_dir / "virtual-device.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as left:
        left.bind(str(path))
    first = HostedDevice(path)
    first.start()
    with pytest.raises(AlreadyServed):
        HostedDevice(path).start()
    first.stop()


def test_a_socket_that_can_not_be_served(qtbot: QtBot, tmp_path: Path) -> None:
    # longer than a Unix socket's path may be
    with pytest.raises(OSError, match="can't serve the virtual device"):
        HostedDevice(tmp_path / ("x" * 120) / "virtual-device.sock").start()


# -- its pill and popover -------------------------------------------------------------------------------------------


@pytest.fixture
def hosting(qtbot: QtBot, make_ui: MakeUi, socket_dir: Path) -> Iterator[Ui]:
    """A window that hosts the virtual device."""
    ui = make_ui(virtual_socket=socket_dir / "virtual-device.sock")
    ui.app.shell.open_virtual_device()
    ui.grab()
    yield ui
    ui.app.shell.close_virtual_device()


def said(ui: Ui) -> list[str]:
    """What the status line of the window says from now on, one text after the other."""
    texts: list[str] = []
    ui.app.shell.statusChanged.connect(lambda: texts.append(ui.app.shell.statusText))
    return texts


def entries(ui: Ui, kind: str = "virtual") -> list[dict[str, Any]]:
    """The rows of the popover of the hosted device (what the pill opens), as QML gets them."""
    return device_of(ui).popover(kind)["entries"]


def do(ui: Ui, title: str, text: str) -> None:
    """Presses the button `text` of the row `title` in the popover of the pill."""
    rows = entries(ui)
    index = next(index for index, row in enumerate(rows) if row["title"] == title)
    device_of(ui).activate(index, rows[index]["actions"].index(text))


def test_unplugged_and_switched_off_the_daemon_loses_it(qtbot: QtBot, hosting: Ui) -> None:
    device = device_of(hosting)
    shell = hosting.app.shell
    hosted = shell.hosted
    assert hosted is not None
    assert device.virtualStatus == {
        "text": "Virtual device · waiting for the daemon",
        "tone": "neutral",
        "tip": "Plugged in: the daemon finds it within seconds.",
    }
    daemon = connect(qtbot, hosted)
    assert device.virtualStatus["text"] == "Virtual device · connected"
    assert device.virtualStatus["tone"] == "good"
    assert [row["title"] for row in entries(hosting)] == ["Connection", "Daemon", "Broken touch"]
    assert entries(hosting)[0]["actions"] == ["Unplug", "Switch off and on", "Close"]

    do(hosting, "Connection", "Unplug")
    assert device.virtualStatus["text"] == "Virtual device · unplugged"
    assert device.virtualStatus["tone"] == "warn"
    qtbot.waitUntil(lambda: daemon.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    do(hosting, "Connection", "Plug in")
    assert hosted.plugged

    daemon = connect(qtbot, hosted)
    do(hosting, "Connection", "Switch off and on")
    qtbot.waitUntil(lambda: daemon.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    assert hosted.device.strips[0].reporting


def test_the_pill_of_the_hosted_device_opens_its_popover(hosting: Ui) -> None:
    assert hosting.shows("virtualPill")

    hosting.click("virtualPill")
    hosting.grab()

    assert hosting.shows("popoverEntry_Connection")
    assert hosting.shows("popoverAction_Close")
    assert hosting.shows("popoverEntry_Daemon")
    # a button closes the popover first: the device is gone from the window
    hosting.click("popoverAction_Close")
    assert hosting.app.shell.hosted is None
    assert not hosting.shows("virtualPill")
    assert not hosting.shows("popoverEntry_Connection")


def test_a_daemon_that_can_not_be_restarted_here_says_why(make_ui: MakeUi, socket_dir: Path, daemon: Any) -> None:
    elsewhere = RecordingInstance(4242, daemon.config, systemd=False)
    ui = make_ui(virtual_socket=socket_dir / "virtual-device.sock", find_daemon=lambda: elsewhere)
    device_of(ui)
    shell = ui.app.shell
    shell.open_virtual_device()

    row = next(row for row in entries(ui) if row["title"] == "Daemon")

    assert row["actions"] == []
    assert row["text"].endswith("restart it where it runs.")
    assert shell.restart_reason() == ("This daemon runs outside the service (process 4242): restart it where it runs.")
    shell.close_virtual_device()


def test_touch_sensors_break_and_work_again(qtbot: QtBot, hosting: Ui) -> None:
    device_of(hosting)
    shell = hosting.app.shell
    hosted = shell.hosted
    assert hosted is not None
    hosting.click("virtualPill")
    toggles = [f"popoverToggle_{strip}" for strip in range(1, protocol.STRIPS + 1)]
    assert all(hosting.shows(name) for name in toggles)

    hosting.click("popoverToggle_2")
    assert hosted.device.broken_touch == {1}
    # it stays open: several can break at once
    assert hosting.shows("popoverToggle_2")
    hosting.click("popoverToggle_4")
    assert hosted.device.broken_touch == {1, 3}
    hosting.click("popoverToggle_2")
    assert hosted.device.broken_touch == {3}
    # the next popover shows them as they are
    broken = next(row for row in entries(hosting) if row["title"] == "Broken touch")
    assert [toggle["on"] for toggle in broken["toggles"]] == [strip == 3 for strip in range(protocol.STRIPS)]


def test_restarting_the_service_shows_its_sequences_on_the_virtual_device(
    hosting: Ui, systemctl: FakeSystemctl
) -> None:
    device_of(hosting)
    shell = hosting.app.shell
    messages = said(hosting)
    assert shell.restart_reason() is None

    do(hosting, "Daemon", "Restart")

    assert ["systemctl", "--user", "restart", "--no-block", UNIT_NAME] in systemctl.commands
    assert messages[0] == "Restarting the service…"


# -- a hand on the device -------------------------------------------------------------------------------------------


def test_the_parts_of_a_strip() -> None:
    assert part_at(ENCODER) == "encoder"
    assert part_at(button_rect(2).center()) == 2
    assert part_at(QPointF(SLOT.center().x(), travel_y(0.5))) == "fader"
    assert part_at(QPointF(0, 0)) is None
    assert fraction_at(travel_y(0.25)) == pytest.approx(0.25)
    assert fraction_at(0) == 1.0
    assert fraction_at(10_000) == 0.0


@pytest.fixture
def stage(qtbot: QtBot) -> Iterator[Stage]:
    stage = Stage(qtbot)
    stage.drawing.show_faces((UNKNOWN,) * protocol.STRIPS, None)
    yield stage
    stage.close()


def play(stage: Stage, hand: FakeHand) -> None:
    """Play, with the mouse a hand on `hand`."""
    stage.drawing.device_hand = hand
    stage.drawing.set_playing(True)


def test_the_mouse_is_a_hand_on_the_hosted_device(stage: Stage) -> None:
    hand = FakeHand()
    play(stage, hand)
    top = QPointF(SLOT.center().x(), travel_y(1.0))
    middle = QPointF(SLOT.center().x(), travel_y(0.5))

    stage.press(1, top)
    stage.move(1, middle)
    stage.release(1, middle)
    assert hand.done[0] == ("touch", 1, True)
    assert hand.done[1][:2] == ("move", 1)
    assert hand.done[-2][:3] == ("move", 1, 0.5)
    assert hand.done[-1] == ("touch", 1, False)

    # with Alt, the fader moves without a touch, like the device moving it by itself
    hand.done.clear()
    stage.press(1, middle, Qt.KeyboardModifier.AltModifier)
    assert hand.done == [("move", 1, 0.5, False)]
    stage.release(1, middle, Qt.KeyboardModifier.AltModifier)

    # a drag that starts on a button moves no fader
    hand.done.clear()
    stage.press(1, button_rect(2).center())
    stage.move(1, middle)
    stage.release(1, middle)
    assert [done[0] for done in hand.done] == ["press", "press"]

    hand.done.clear()
    stage.click(1, button_rect(2).center())
    stage.click(1, ENCODER)
    assert hand.done == [
        ("press", 1, Button.MUTE, True),
        ("press", 1, Button.MUTE, False),
        ("push", 1, True),
        ("push", 1, False),
    ]


def test_in_play_what_the_mouse_can_take_glows(stage: Stage) -> None:
    view = stage.drawing.strips[2]
    item = stage.strips[2]
    plain = stage.image()
    # not in the editor: there the mouse picks and moves strips
    stage.move(2, ENCODER)
    assert view.hovered is None
    play(stage, FakeHand())
    stage.move(2, QPointF(0, 0))
    looks: dict[str, Any] = {}
    for name, point in (
        ("knob", ENCODER),
        ("led", ENCODER + QPointF(0, -23)),
        ("button", button_rect(1).center()),
        ("fader", QPointF(SLOT.center().x(), travel_y(0.5))),
    ):
        stage.move(2, point)
        assert view.hovered is not None
        assert view.hovered.part == name
        looks[name] = stage.image()
        assert looks[name] != plain
        # and says what the mouse does with it
        assert item.property("tip") == HOVER_TIPS[name]
    # each glows where it is
    images = list(looks.values())
    assert all(a != b for index, a in enumerate(images) for b in images[index + 1 :])
    stage.move(2, QPointF(0, 0))
    assert view.hovered is None
    assert item.property("tip") == view.face_tip
    # the LEDs at the ends: all the way
    stage.move(2, led_point(0))
    assert item.property("tip") == HOVER_TIPS["ends"]


def test_a_drag_on_the_knob_shows_the_steps(stage: Stage) -> None:
    view = stage.drawing.strips[2]
    hand = FakeHand()
    play(stage, hand)
    stage.move(2, ENCODER)
    stage.press(2, ENCODER)
    hovered = stage.image()
    stage.move(2, ENCODER + QPointF(20, 0))
    assert view.encoder.dragging
    # the pointer and the ticks of the steps, instead of the glow
    assert stage.image() != hovered
    stage.release(2, ENCODER + QPointF(20, 0))
    assert not view.encoder.dragging
    assert sum(int(str(done[2])) for done in hand.done if done[0] == "turn") == 5


def test_without_a_hand_the_mouse_only_selects(stage: Stage) -> None:
    drawing = stage.drawing
    clicked: list[int] = []
    drawing.clicked.connect(clicked.append)

    stage.click(1, ENCODER)
    stage.click(1, ENCODER, Qt.MouseButton.RightButton)
    stage.move(1, ENCODER)
    # the right button only opens the menu (and picks, as the widgets did)
    assert clicked == [1, 1]

    # nothing to take, also with a hand; in Play a click selects nothing, and the selection is hidden
    drawing.show_faces(tuple(view.face for view in drawing.strips), 1)
    hand = FakeHand()
    play(stage, hand)
    stage.click(1, QPointF(0, 0))
    assert hand.done == []
    assert clicked == [1, 1]
    assert not drawing.strips[1].selected
    drawing.set_playing(False)
    assert drawing.strips[1].selected


def test_the_wheel_turns_the_encoder(stage: Stage) -> None:
    item = stage.strips[3]

    def wheel(delta: int) -> bool:
        event = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        item.wheelEvent(event)
        return event.isAccepted()

    assert not wheel(120)
    hand = FakeHand()
    play(stage, hand)
    assert wheel(240)
    assert hand.done == [("turn", 3, 2)]
    # a smooth wheel or a touchpad sends parts of a notch: they add up, the same both ways
    hand.done.clear()
    for delta in (30, 30, 30, 30, -30, -30, -30, -30, -30):
        wheel(delta)
    assert hand.done == [("turn", 3, 1), ("turn", 3, -1)]


def test_a_hand_that_goes_while_a_strip_is_held_does_nothing_more(stage: Stage) -> None:
    hand = FakeHand()
    play(stage, hand)
    stage.press(0, button_rect(1).center())
    assert hand.done == [("press", 0, Button.SOLO, True)]

    stage.drawing.device_hand = None
    stage.release(0, button_rect(1).center())

    assert hand.done == [("press", 0, Button.SOLO, True)]


# -- Play in the window ---------------------------------------------------------------------------------------------


def test_play_opens_the_virtual_device_the_daemon_waits_for(
    make_ui: MakeUi, live_daemon: FakeLiveDaemon, socket_dir: Path, dialogs: FakeDialogs
) -> None:
    path = socket_dir / "virtual-device.sock"
    ui = make_ui(live_socket=live_daemon.path, virtual_socket=path)
    device = device_of(ui)
    shell = ui.app.shell
    ui.wait_until(lambda: bool(live_daemon.clients))
    waiting = dataclasses.replace(snapshot(ui, device=False), virtual=True)
    live_daemon.send(waiting)
    ui.wait_until(lambda: device.liveStatus.get("text", "").startswith("Live · virtual device not running · Open it"))
    assert device.offered
    assert "Play: opens the virtual device" in device.modeHint
    assert device.playEnabled

    ui.click("modePlay")

    assert shell.hosted is not None
    assert path.exists()
    assert device.playing
    assert drawing_of(ui).hand is shell.hosted
    # what the mouse plays on stands out
    assert (device.modeHint, device.handStatus["text"], device.handStatus["tone"]) == (
        "Playing on",
        "the virtual device",
        "warn",
    )
    assert ui.shows("handPill")
    assert ui.shows("virtualPill")
    assert device.liveStatus["text"].startswith("Live · virtual device opening")

    ui.grab()
    ui.click("virtualPill")
    ui.click("popoverAction_Close")
    # gone from the screen at once
    assert not ui.shows("virtualPill")
    assert shell.hosted is None
    assert not path.exists()
    assert drawing_of(ui).hand is None

    # another one runs already
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as other:
        other.bind(str(path))
        other.listen()
        shell.open_virtual_device()
    assert shell.hosted is None
    assert "already runs" in dialogs.shown[-1]
    assert dialogs.titles[-1] == "Virtual device"


def test_closing_the_window_closes_the_virtual_device(make_ui: MakeUi, socket_dir: Path) -> None:
    path = socket_dir / "virtual-device.sock"
    ui = make_ui(virtual_socket=path)
    ui.app.shell.open_virtual_device()
    assert path.exists()

    ui.window.close()
    ui.settle()

    assert not path.exists()


def test_a_daemon_without_a_device_switches_to_the_virtual_one(
    make_ui: MakeUi, live_daemon: FakeLiveDaemon, socket_dir: Path, daemon: RecordingInstance
) -> None:
    ui = make_ui(
        live_socket=live_daemon.path, virtual_socket=socket_dir / "virtual-device.sock", find_daemon=lambda: daemon
    )
    device = device_of(ui)
    shell = ui.app.shell
    ui.wait_until(lambda: bool(live_daemon.clients))
    assert not ui.shows("useVirtualButton")
    live_daemon.send(snapshot(ui, device=False))
    ui.wait_until(lambda: ui.shows("useVirtualButton"))
    # the shell saves and applies the file
    ui.click("useVirtualButton")

    # saved and reloaded: the daemon switches to it, and the window hosts it
    assert device.document.get(("device", "virtual")) is True
    assert not device.document.modified
    assert daemon.reloads
    assert shell.hosted is not None
    shell.close_virtual_device()


def test_the_device_plugged_in_again_is_offered_and_switched_to(
    make_ui: MakeUi,
    live_daemon: FakeLiveDaemon,
    socket_dir: Path,
    path: Path,
    daemon: RecordingInstance,
    dialogs: FakeDialogs,
) -> None:
    path.write_text("[device]\nvirtual = true\n" + path.read_text())
    ui = make_ui(
        live_socket=live_daemon.path, virtual_socket=socket_dir / "virtual-device.sock", find_daemon=lambda: daemon
    )
    device = device_of(ui)
    shell = ui.app.shell
    shell.open_virtual_device()
    ui.wait_until(lambda: bool(live_daemon.clients))
    virtual = dataclasses.replace(snapshot(ui), virtual=True)
    live_daemon.send(virtual)
    ui.wait_until(lambda: shell.live.snapshot is not None)
    assert not ui.shows("deviceBanner")

    live_daemon.send(dataclasses.replace(virtual, device_plugged=True))
    ui.wait_until(lambda: ui.shows("deviceBanner"))
    assert ui.text("deviceBanner").startswith("X-Touch-Ext is plugged in")
    assert ui.text("deviceOfferButton") == "Switch to it"
    # other changes are saved with it: only if the user says so
    device.document.set(("channel", "out", "label"), "Boxes")
    device.editor.edited()
    dialogs.answer = "no"
    ui.click("deviceOfferButton")
    assert dialogs.shown
    assert "Save them and switch" in dialogs.shown[0]
    assert device.document.get(("device", "virtual")) is True
    assert shell.hosted is not None

    dialogs.answer = "yes"
    ui.click("deviceOfferButton")

    # saved and reloaded: the daemon goes to the device, the window closes the virtual one
    assert device.document.get(("device", "virtual")) is None
    assert "virtual" not in path.read_text()
    assert not device.document.modified
    assert daemon.reloads
    assert shell.hosted is None


@pytest.mark.parametrize("trying", [True, False])
def test_a_daemon_that_does_not_read_the_switch_from_the_file_is_not_switched_by_it(
    qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon, trying: bool
) -> None:
    ui = make_ui(live_socket=live_daemon.path)
    device = device_of(ui)
    shell = ui.app.shell
    messages = said(ui)
    ui.wait_until(lambda: bool(live_daemon.clients))
    if trying:
        # the trial of the window: a daemon with --virtual-device
        shell.trying = QProcess(device)
        shell.trying.start("sleep", ["30"])
        assert shell.trying.waitForStarted()
    live_daemon.send(dataclasses.replace(snapshot(ui), virtual=True, device_plugged=True))
    ui.wait_until(lambda: ui.shows("deviceBanner"))

    if trying:
        assert ui.text("deviceOfferButton") == "End the trial"
        process = shell.trying
        assert process is not None
        ui.click("deviceOfferButton")
        # ended: terminated, and let go of
        qtbot.waitUntil(lambda: sip.isdeleted(process), timeout=5000)
        assert shell.trying is None
        assert messages[-1] == "Ending the trial: start the service to use the device."
    else:
        # started elsewhere with --virtual-device: the bar only says so
        assert not ui.shows("deviceOfferButton")
        assert "--virtual-device" in ui.text("deviceBanner")
        device.switchToDevice()
        assert device.document.get(("device", "virtual")) is None


def test_the_trial_starts_a_daemon_with_the_virtual_device(make_ui: MakeUi) -> None:
    started: list[Path] = []

    def launch(path: Path) -> QProcess:
        started.append(path)
        process = QProcess()
        process.start("sleep", ["30"])
        assert process.waitForStarted()
        return process

    ui = make_ui(find_daemon=lambda: None, extra={"launch_trial": launch})
    messages = said(ui)
    assert ui.shows("tryButton")

    ui.click("tryButton")

    assert started == [ui.app.editor.document.path]
    assert messages == ["Starting a daemon with the virtual device…"]
    # the window ends it with itself
    assert ui.app.shell.closeAllowed()


def test_a_trial_of_a_new_file_saves_it_first(make_ui: MakeUi, tmp_path: Path) -> None:
    started: list[Path] = []

    def launch(path: Path) -> QProcess:
        started.append(path)
        process = QProcess()
        process.start("sleep", ["30"])
        assert process.waitForStarted()
        return process

    new = tmp_path / "new" / "config.toml"
    ui = make_ui(find_daemon=lambda: None, document=SlotsDocument.open(new), extra={"launch_trial": launch})
    assert not new.exists()

    ui.app.device.tryWithoutDevice()  # pyright: ignore[reportAttributeAccessIssue]

    assert new.exists()
    assert started == [new]
    assert ui.app.shell.closeAllowed()
