"""
The test of the device in Qt Quick: the daemon tests the device for the window, the drawing shows the device
meanwhile, and the window learns when the daemon ends the test.
"""

import pytest
from PyQt6.QtCore import QPointF
from pytestqt.qtbot import QtBot

from tests.gui.quick.conftest import MakeUi
from tests.gui.quick.device_support import device_of, live_ui, snapshot  # noqa: F401
from tests.support.gui import FakeLiveDaemon
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.device import device_test as device_test_module
from xtouch_daemon.live.codec import encode_reply
from xtouch_daemon.live.messages import EndTest, KeepTest, Reply, StartTest


def messages_of(ui: Ui) -> list[str]:
    """What the panel says in the status line of the shell."""
    said: list[str] = []
    ui.app.shell.statusChanged.connect(lambda: said.append(ui.app.shell.statusText))
    return said


def test_the_button_starts_and_ends_the_test(
    qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(device_test_module, "HEARTBEAT_MS", 10)
    ui = live_ui(make_ui, live_daemon, qtbot)
    device = device_of(ui)
    said = messages_of(ui)
    assert device.testVisible
    assert device.testEnabled
    assert not device.testRunning

    device.toggleTest(True)

    ui.wait_until(lambda: StartTest() in live_daemon.requests)
    assert device.testRunning
    assert "Testing the device" in said[-1]
    # a heartbeat keeps it going
    ui.wait_until(lambda: KeepTest() in live_daemon.requests)

    device.toggleTest(False)

    ui.wait_until(lambda: EndTest() in live_daemon.requests)
    assert not device.testRunning
    assert said[-1] == "The test ended: the device shows the slots again."


def test_the_button_in_the_window(qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot)
    button = ui.item("testButton")
    ui.click(button)
    ui.wait_until(lambda: StartTest() in live_daemon.requests)
    assert device_of(ui).testRunning
    assert button.property("checked")
    ui.click(button)
    ui.wait_until(lambda: EndTest() in live_daemon.requests)
    assert not button.property("checked")


def test_the_window_learns_why_the_daemon_ended_the_test_or_did_not_start_it(
    qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon
) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot)
    device = device_of(ui)
    said = messages_of(ui)

    device.toggleTest(True)
    live_daemon.send_line(encode_reply(Reply("test_ended", True, "the device went away")))
    ui.wait_until(lambda: not device.testRunning, timeout=10_000)
    assert said[-1] == "The test of the device ended: the device went away."

    device.toggleTest(True)
    live_daemon.send_line(encode_reply(Reply("test", False, "The device is not connected.")))
    ui.wait_until(lambda: not device.testRunning, timeout=10_000)
    assert said[-1] == "The test did not start: The device is not connected."

    # the daemon goes away
    device.toggleTest(True)
    live_daemon.close()
    ui.wait_until(lambda: not device.testRunning, timeout=10_000)
    assert "the daemon went away" in said[-1]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [({"features": ()}, "too old"), ({"device": False}, "The device is not connected.")],
)
def test_the_button_says_why_the_device_can_not_be_tested(
    qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon, changes: dict[str, object], reason: str
) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot, **changes)
    device = device_of(ui)
    assert not device.testEnabled
    assert reason in device.testTip


def test_while_testing_the_drawing_shows_the_device_and_not_the_twin(
    qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon
) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot)
    device = device_of(ui)
    device.document.set(("channel", "out", "label"), "Boxes")
    device.editor.edited()
    # the preview in the GUI draws the twin
    ui.wait_until(device.shows_twin)

    device.toggleTest(True)

    assert not device.shows_twin()
    # the window closes: the test ends
    device.shutdown()
    ui.wait_until(lambda: EndTest() in live_daemon.requests)


@pytest.mark.parametrize(
    ("virtual", "text", "tone"), [(False, "the device", "good"), (True, "the virtual device", "warn")]
)
def test_play_says_in_a_pill_what_the_mouse_plays_on(
    qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon, virtual: bool, text: str, tone: str
) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot, virtual=virtual)
    device = device_of(ui)
    assert device.handStatus == {}

    device.setPlaying(True)

    assert device.modeHint == "Playing on"
    assert (device.handStatus["text"], device.handStatus["tone"]) == (text, tone)
    device.setPlaying(False)
    assert device.handStatus == {}


def test_the_thumb_of_select_and_play_sits_under_the_one_that_is_on(
    qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon
) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot)
    device = device_of(ui)
    hands = ui.item("hands")
    thumb = next(child for child in hands.childItems() if child.objectName() == "thumb")

    def under(name: str) -> bool:
        ui.settle()
        button = ui.item(name)
        return thumb.x() == button.mapToItem(hands, QPointF(0, 0)).x() and thumb.width() == button.width()

    assert under("modeSelect")
    device.setPlaying(True)
    assert under("modePlay")
    assert ui.item("modePlay").property("checked")
    assert not ui.item("modeSelect").property("checked")


def test_without_a_daemon_to_ask_the_test_does_not_start(make_ui: MakeUi) -> None:
    ui = make_ui()
    said = messages_of(ui)
    device_of(ui).device_test.start()
    assert not device_of(ui).device_test.running
    assert said[-1] == "The daemon is not reachable."


def test_a_second_start_changes_nothing(qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot)
    device = device_of(ui)
    device.device_test.start()
    device.device_test.start()
    ui.wait_until(lambda: StartTest() in live_daemon.requests)
    qtbot.wait(50)
    assert live_daemon.requests.count(StartTest()) == 1
