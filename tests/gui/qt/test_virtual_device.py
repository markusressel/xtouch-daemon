"""
The virtual device the GUI hosts: the daemon on its socket, the mouse on the drawing as a hand, the bar, and the offer
in the pill while the daemon waits for it.
"""

import dataclasses
import socket
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtNetwork import QLocalSocket
from pytestqt.qtbot import QtBot

from tests.support.gui import Dialogs, FakeLiveDaemon, MakeWindow, pill, snapshot, strip_state
from xtouch_daemon.gui.qt.preview.geometry import ENCODER, SLOT, button_rect, fraction_at, part_at, travel_y
from xtouch_daemon.gui.qt.preview.panel import Preview
from xtouch_daemon.gui.qt.virtual_device import HostedDevice, VirtualDeviceBar
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.simulator.server import AlreadyServed


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


def test_unplugged_and_switched_off_the_daemon_loses_it(qtbot: QtBot, hosted: HostedDevice) -> None:
    bar = VirtualDeviceBar(hosted, close=None)  # type: ignore[arg-type]
    qtbot.addWidget(bar)
    assert bar.state.text() == "Virtual device: waiting for the daemon"
    daemon = connect(qtbot, hosted)
    assert bar.state.text().startswith("Virtual device: the mouse is a hand on it")

    bar.plug.click()
    assert bar.state.text() == "Virtual device: unplugged"
    assert bar.plug.text() == "Plug in"
    qtbot.waitUntil(lambda: daemon.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    bar.plug.click()
    hosted.plug()
    assert hosted.plugged

    daemon = connect(qtbot, hosted)
    hosted.power_cycle()
    qtbot.waitUntil(lambda: daemon.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    assert hosted.device.strips[0].reporting
    hosted.stop()


def test_touch_sensors_break_and_work_again(qtbot: QtBot, hosted: HostedDevice) -> None:
    bar = VirtualDeviceBar(hosted, close=None)  # type: ignore[arg-type]
    qtbot.addWidget(bar)
    menu = bar.broken.menu()
    assert menu is not None
    fader_2 = menu.actions()[1]

    fader_2.setChecked(True)
    assert hosted.device.broken_touch == {1}
    fader_2.setChecked(False)
    assert hosted.device.broken_touch == set()
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
    assert view.virtual_bar is not None
    assert view.live_pill.text().startswith("Live · virtual device opening")

    close = [button for button in view.virtual_bar.findChildren(type(window.save_button)) if button.text() == "Close"]
    close[0].click()
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
