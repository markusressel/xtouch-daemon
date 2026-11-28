"""
The virtual device the GUI hosts: the daemon on its socket, the mouse on the drawing as a hand, its pill, the offer
in the pill while the daemon waits for it, and the way back to the device once it is plugged in.
"""

import dataclasses
import socket
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, QPointF, QProcess, Qt
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QMessageBox, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from tests.support.gui import Dialogs, FakeLiveDaemon, MakeWindow, led_point, pill, snapshot, strip_state
from tests.support.instance import RecordingInstance
from tests.support.systemd import FakeSystemctl
from xtouch_daemon.gui.qt.fields.popover import Entry
from xtouch_daemon.gui.qt.preview.geometry import ENCODER, SLOT, button_rect, fraction_at, part_at, travel_y
from xtouch_daemon.gui.qt.preview.panel import Preview
from xtouch_daemon.gui.qt.preview.strip_view import HOVER_TIPS
from xtouch_daemon.gui.qt.virtual_device import HostedDevice, VirtualDevicePill
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


def device_pill(hosted: HostedDevice, reason: str | None = None) -> tuple[VirtualDevicePill, list[str]]:
    """The pill of `hosted`, and what its buttons for the window were told: "close", "restart"."""
    told: list[str] = []
    shown = VirtualDevicePill(hosted, lambda: told.append("close"), lambda: told.append("restart"), lambda: reason)
    return shown, told


def entry(shown: VirtualDevicePill, title: str) -> Entry:
    return next(entry for entry in shown.details() if entry.title == title)


def do(shown: VirtualDevicePill, title: str, text: str) -> None:
    """Clicks the button `text` of the row `title` in the popover of the pill."""
    dict(entry(shown, title).actions)[text]()


def test_unplugged_and_switched_off_the_daemon_loses_it(qtbot: QtBot, hosted: HostedDevice) -> None:
    shown, told = device_pill(hosted)
    qtbot.addWidget(shown)
    assert pill(shown) == "Virtual device · waiting for the daemon"
    daemon = connect(qtbot, hosted)
    assert pill(shown) == "Virtual device · connected"
    assert shown.property("tone") == "good"
    assert [text for text, _ in entry(shown, "Connection").actions] == ["Unplug", "Switch off and on", "Close"]

    do(shown, "Connection", "Unplug")
    assert pill(shown) == "Virtual device · unplugged"
    assert shown.property("tone") == "warn"
    qtbot.waitUntil(lambda: daemon.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    do(shown, "Connection", "Plug in")
    assert hosted.plugged

    daemon = connect(qtbot, hosted)
    do(shown, "Connection", "Switch off and on")
    qtbot.waitUntil(lambda: daemon.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    assert hosted.device.strips[0].reporting
    do(shown, "Connection", "Close")
    do(shown, "Daemon", "Restart")
    assert told == ["close", "restart"]
    hosted.stop()


def test_a_daemon_that_can_not_be_restarted_here_says_why(qtbot: QtBot, hosted: HostedDevice) -> None:
    shown, _ = device_pill(hosted, "Restart it where it runs.")
    qtbot.addWidget(shown)
    daemon = entry(shown, "Daemon")
    assert daemon.actions == ()
    assert daemon.text.endswith("Restart it where it runs.")
    hosted.stop()


def test_touch_sensors_break_and_work_again(qtbot: QtBot, hosted: HostedDevice) -> None:
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(800, 600)
    shown, _ = device_pill(hosted)
    shown.setParent(window)  # pyright: ignore[reportArgumentType]: PyQt's stub types the parent as Self
    window.show()
    popover = shown.show_details()
    faders = [button for button in popover.findChildren(QPushButton) if button.isCheckable()]
    assert [button.text() for button in faders] == [str(strip) for strip in range(1, protocol.STRIPS + 1)]

    faders[1].click()
    assert hosted.device.broken_touch == {1}
    # it stays open: several can break at once
    assert popover.isVisible()
    faders[3].click()
    assert hosted.device.broken_touch == {1, 3}
    faders[1].click()
    assert hosted.device.broken_touch == {3}
    popover.close()
    # the next popover shows them as they are
    assert [on for _, on, _ in entry(shown, "Broken touch").toggles] == [strip == 3 for strip in range(protocol.STRIPS)]
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


class Hand:
    def __init__(self) -> None:
        self.done: list[tuple[object, ...]] = []

    def touch(self, strip: int, touched: bool) -> None:
        self.done.append(("touch", strip, touched))

    def move(self, strip: int, fraction: float, hand: bool = True) -> None:
        self.done.append(("move", strip, round(fraction, 2), hand))

    def press(self, strip: int, button: Button, pressed: bool) -> None:
        self.done.append(("press", strip, button, pressed))

    def turn(self, strip: int, steps: int) -> None:
        self.done.append(("turn", strip, steps))

    def push(self, strip: int, pressed: bool) -> None:
        self.done.append(("push", strip, pressed))


def test_the_parts_of_a_strip() -> None:
    assert part_at(ENCODER) == "encoder"
    assert part_at(button_rect(2).center()) == 2
    assert part_at(QPointF(SLOT.center().x(), travel_y(0.5))) == "fader"
    assert part_at(QPointF(0, 0)) is None
    assert fraction_at(travel_y(0.25)) == pytest.approx(0.25)
    assert fraction_at(0) == 1.0
    assert fraction_at(10_000) == 0.0


@pytest.fixture
def preview(qtbot: QtBot) -> Preview:
    preview = Preview()
    qtbot.addWidget(preview)
    preview.resize(preview.sizeHint())
    preview.show()
    return preview


def play(preview: Preview, hand: Hand) -> None:
    """Play, with the mouse a hand on `hand`."""
    preview.device_hand = hand
    preview.set_playing(True)


def at(preview: Preview, point: QPointF) -> QPoint:
    return (point * preview.scale).toPoint()


def test_the_mouse_is_a_hand_on_the_hosted_device(qtbot: QtBot, preview: Preview) -> None:
    hand = Hand()
    play(preview, hand)
    view = preview.strips[1]
    top = QPointF(SLOT.center().x(), travel_y(1.0))
    middle = QPointF(SLOT.center().x(), travel_y(0.5))

    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=at(preview, top))
    qtbot.mouseMove(view, at(preview, middle))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=at(preview, middle))
    assert hand.done[0] == ("touch", 1, True)
    assert hand.done[1][:2] == ("move", 1)
    assert hand.done[-2][:3] == ("move", 1, 0.5)
    assert hand.done[-1] == ("touch", 1, False)

    # with Alt, the fader moves without a touch, like the device moving it by itself
    hand.done.clear()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, at(preview, middle))
    assert hand.done == [("move", 1, 0.5, False)]
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, at(preview, middle))

    # a drag that starts on a button moves no fader
    hand.done.clear()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=at(preview, button_rect(2).center()))
    qtbot.mouseMove(view, at(preview, middle))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=at(preview, middle))
    assert [done[0] for done in hand.done] == ["press", "press"]

    hand.done.clear()
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=at(preview, button_rect(2).center()))
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=at(preview, ENCODER))
    assert hand.done == [
        ("press", 1, Button.MUTE, True),
        ("press", 1, Button.MUTE, False),
        ("push", 1, True),
        ("push", 1, False),
    ]


def test_in_play_what_the_mouse_can_take_glows(qtbot: QtBot, preview: Preview) -> None:
    view = preview.strips[2]
    plain = view.grab().toImage()
    # not in the editor: there the mouse picks and moves strips
    qtbot.mouseMove(view, at(preview, ENCODER))
    assert view.hovered is None
    play(preview, Hand())
    qtbot.mouseMove(view, QPoint(0, 0))
    looks = {}
    for name, point in (
        ("knob", ENCODER),
        ("led", ENCODER + QPointF(0, -23)),
        ("button", button_rect(1).center()),
        ("fader", QPointF(SLOT.center().x(), travel_y(0.5))),
    ):
        qtbot.mouseMove(view, at(preview, point))
        assert view.hovered is not None
        assert view.hovered.part == name
        looks[name] = view.grab().toImage()
        assert looks[name] != plain
        # and says what the mouse does with it
        assert view.toolTip() == HOVER_TIPS[name]
    # each glows where it is
    images = list(looks.values())
    assert all(a != b for index, a in enumerate(images) for b in images[index + 1 :])
    qtbot.mouseMove(view, QPoint(0, 0))
    assert view.hovered is None
    assert view.toolTip() == view.face_tip
    # the LEDs at the ends: all the way
    qtbot.mouseMove(view, at(preview, led_point(0)))
    assert view.toolTip() == HOVER_TIPS["ends"]


def test_a_drag_on_the_knob_shows_the_steps(qtbot: QtBot, preview: Preview) -> None:
    view = preview.strips[2]
    hand = Hand()
    play(preview, hand)
    qtbot.mouseMove(view, at(preview, ENCODER))
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=at(preview, ENCODER))
    hovered = view.grab().toImage()
    qtbot.mouseMove(view, at(preview, ENCODER + QPointF(20, 0)))
    assert view.encoder.dragging
    # the pointer and the ticks of the steps, instead of the glow
    assert view.grab().toImage() != hovered
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=at(preview, ENCODER + QPointF(20, 0)))
    assert not view.encoder.dragging
    assert sum(int(str(done[2])) for done in hand.done if done[0] == "turn") == 5


def test_without_a_hand_the_mouse_only_selects(qtbot: QtBot, preview: Preview) -> None:
    view = preview.strips[1]
    clicked: list[int] = []
    preview.clicked.connect(clicked.append)

    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=at(preview, ENCODER))
    qtbot.mouseClick(view, Qt.MouseButton.RightButton, pos=at(preview, ENCODER))
    qtbot.mouseMove(view, at(preview, ENCODER))
    assert clicked == [1]

    # nothing to take, also with a hand; in Play a click selects nothing, and the selection is hidden
    preview.show_faces(tuple(view.face for view in preview.strips), 1)
    hand = Hand()
    play(preview, hand)
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(0, 0))
    assert hand.done == []
    assert clicked == [1]
    assert not view.selected
    preview.set_playing(False)
    assert view.selected


def test_the_wheel_turns_the_encoder(qtbot: QtBot, preview: Preview) -> None:
    from PyQt6.QtGui import QWheelEvent

    view = preview.strips[3]

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
        view.wheelEvent(event)
        return event.isAccepted()

    assert not wheel(120)
    hand = Hand()
    play(preview, hand)
    assert wheel(240)
    assert hand.done == [("turn", 3, 2)]
    # a smooth wheel or a touchpad sends parts of a notch: they add up, the same both ways
    hand.done.clear()
    for delta in (30, 30, 30, 30, -30, -30, -30, -30, -30):
        wheel(delta)
    assert hand.done == [("turn", 3, 1), ("turn", 3, -1)]


def test_play_opens_the_virtual_device_the_daemon_waits_for(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon, socket_dir: Path, isolated: Dialogs
) -> None:
    path = socket_dir / "virtual-device.sock"
    window = make_window(live_socket=live_daemon.path, virtual_socket=path)
    view = window.device_view
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    waiting = dataclasses.replace(snapshot(window, strip_state(), device=False), virtual=True)
    live_daemon.send(waiting)
    qtbot.waitUntil(lambda: view.live_pill.text().startswith("Live · virtual device not running · Open it"))
    assert view.offered
    assert "Play: opens the virtual device" in view.mode_hint.text()

    window.device_dock.hide()
    view.play_button.click()
    assert window.hosted is not None
    assert path.exists()
    # the window Device shows it, also after it was closed, in Play
    assert window.device_dock.isVisible()
    assert view.play_button.isChecked()
    assert view.preview.hand is window.hosted
    # what the mouse plays on stands out
    assert (view.mode_hint.text(), pill(view.hand_pill)) == ("Playing on", "the virtual device")
    assert view.hand_pill.property("tone") == "warn"
    assert view.virtual_pill is not None
    assert view.live_pill.text().startswith("Live · virtual device opening")

    shown = view.virtual_pill
    assert pill(shown).startswith("Virtual device · ")
    do(shown, "Connection", "Close")
    # gone from the screen at once, not when the event loop deletes it
    assert shown.isHidden()
    assert view.virtual_pill is None
    assert window.hosted is None
    assert not path.exists()
    assert window.device_view.preview.hand is None
    window.close_virtual_device()

    # another one runs already
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as other:
        other.bind(str(path))
        other.listen()
        window.open_virtual_device()
    assert window.hosted is None
    assert "already runs" in isolated.shown[-1]


def test_closing_the_window_closes_the_virtual_device(qtbot: QtBot, make_window: MakeWindow, socket_dir: Path) -> None:
    path = socket_dir / "virtual-device.sock"
    window = make_window(virtual_socket=path)
    window.open_virtual_device()
    assert path.exists()

    window.close()
    assert not path.exists()


def test_a_daemon_without_a_device_switches_to_the_virtual_one(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon, socket_dir: Path, isolated: Dialogs
) -> None:
    window = make_window(live_socket=live_daemon.path, virtual_socket=socket_dir / "virtual-device.sock")
    view = window.device_view
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    assert view.virtual_button.isHidden()
    live_daemon.send(snapshot(window, strip_state(), device=False))
    qtbot.waitUntil(lambda: not view.virtual_button.isHidden())

    view.virtual_button.click()

    # saved and reloaded: the daemon switches to it, and the window hosts it
    assert window.document.get(("device", "virtual")) is True
    assert not window.document.modified
    assert window.daemon is not None
    assert window.daemon.reloads  # pyright: ignore[reportAttributeAccessIssue]
    assert window.hosted is not None


def test_the_device_plugged_in_again_is_offered_and_switched_to(
    qtbot: QtBot,
    make_window: MakeWindow,
    live_daemon: FakeLiveDaemon,
    socket_dir: Path,
    path: Path,
    isolated: Dialogs,
) -> None:
    path.write_text("[device]\nvirtual = true\n" + path.read_text())
    window = make_window(live_socket=live_daemon.path, virtual_socket=socket_dir / "virtual-device.sock")
    view = window.device_view
    window.open_virtual_device()
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    virtual = dataclasses.replace(snapshot(window, strip_state()), virtual=True)
    live_daemon.send(virtual)
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    assert view.device_bar.isHidden()

    live_daemon.send(dataclasses.replace(virtual, device_plugged=True))
    qtbot.waitUntil(lambda: not view.device_bar.isHidden())
    assert view.device_message.text().startswith("X-Touch-Ext is plugged in")
    assert view.device_button.text() == "Switch to it"
    # other changes are saved with it: only if the user says so
    window.document.set(("channel", "out", "label"), "Boxes")
    window.editor.edited()
    isolated.answer = QMessageBox.StandardButton.No
    view.device_button.click()
    assert window.document.get(("device", "virtual")) is True
    assert window.hosted is not None

    isolated.answer = QMessageBox.StandardButton.Yes
    view.device_button.click()

    # saved and reloaded: the daemon goes to the device, the window closes the virtual one
    assert window.document.get(("device", "virtual")) is None
    assert "virtual" not in path.read_text()
    assert not window.document.modified
    assert window.daemon is not None
    assert window.daemon.reloads  # pyright: ignore[reportAttributeAccessIssue]
    assert window.hosted is None


@pytest.mark.parametrize("trying", [True, False])
def test_a_daemon_that_does_not_read_the_switch_from_the_file_is_not_switched_by_it(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon, trying: bool
) -> None:
    window = make_window(live_socket=live_daemon.path)
    view = window.device_view
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    if trying:
        # the trial of the window: a daemon with --virtual-device
        window.trying = QProcess(window)
        window.trying.start("sleep", ["30"])
        assert window.trying.waitForStarted()
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), virtual=True, device_plugged=True))
    qtbot.waitUntil(lambda: not view.device_bar.isHidden())

    if trying:
        assert view.device_button.text() == "End the trial"
        process = window.trying
        assert process is not None
        view.device_button.click()
        assert process.waitForFinished(5000)
        qtbot.wait(10)
        assert window.trying is None
        assert window.status.text() == "Ending the trial: start the service to use the device."
    else:
        # started elsewhere with --virtual-device: the bar only says so
        assert view.device_button.isHidden()
        assert "--virtual-device" in view.device_message.text()
        window.switch_to_device()
        assert window.document.get(("device", "virtual")) is None


def test_restarting_the_service_shows_its_sequences_on_the_virtual_device(
    make_window: MakeWindow, systemctl: FakeSystemctl, socket_dir: Path
) -> None:
    window = make_window(virtual_socket=socket_dir / "virtual-device.sock")
    window.open_virtual_device()
    view = window.device_view
    assert view.virtual_pill is not None
    assert window._restart_reason() is None  # pyright: ignore[reportPrivateUsage]

    do(view.virtual_pill, "Daemon", "Restart")
    assert systemctl.commands[-2] == ["systemctl", "--user", "restart", "--no-block", UNIT_NAME]
    assert window.status.text() == "Restarting the service…"
    window.close_virtual_device()


def test_a_daemon_elsewhere_or_none_is_not_restarted_here(make_window: MakeWindow, path: Path) -> None:
    elsewhere = make_window(find_daemon=lambda: RecordingInstance(4242, path.resolve(), systemd=False))
    assert elsewhere._restart_reason() == (  # pyright: ignore[reportPrivateUsage]
        "This daemon runs outside the service (process 4242): restart it where it runs."
    )
    none = make_window(find_daemon=lambda: None)
    assert none._restart_reason() == "No daemon runs now."  # pyright: ignore[reportPrivateUsage]


def test_the_daemon_of_the_trial_starts_again(
    qtbot: QtBot, make_window: MakeWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = make_window(find_daemon=lambda: None)
    started: list[bool] = []
    monkeypatch.setattr(window, "_start_trial", lambda: started.append(True))
    process = QProcess()
    process.start("sleep", ["30"])
    assert process.waitForStarted()
    window._keep_trying(process)  # pyright: ignore[reportPrivateUsage]
    assert window._restart_reason() is None  # pyright: ignore[reportPrivateUsage]

    window.restart_daemon()
    assert window.status.text() == "Stopping the daemon for trying without a device, to start it again…"
    qtbot.waitUntil(lambda: started == [True])
    assert not window.restarting_trial
    assert window.status.text() == "Starting the daemon for trying without a device again…"
