"""
The button "Test the device" of the window Device: the daemon tests the device for the window, the drawing shows the
device meanwhile, and the window learns when the daemon ends the test.
"""

import dataclasses
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.support.gui import FakeLiveDaemon, MakeWindow, click, strip_state
from xtouch_daemon.gui.qt import device_test as device_test_module
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.codec import encode_reply
from xtouch_daemon.live.messages import FEATURES, EndTest, KeepTest, Reply, Snapshot, StartTest, fingerprint


@pytest.fixture
def live_daemon(qapp: QApplication) -> Iterator[FakeLiveDaemon]:
    # a short path: the one of a Unix socket has at most 107 bytes, which tmp_path may exceed
    with tempfile.TemporaryDirectory(prefix="xtt-") as directory:
        fake = FakeLiveDaemon(Path(directory) / "live.sock")
        yield fake
        fake.close()


def snapshot(window: MainWindow, **changes: object) -> Snapshot:
    config = window.document.saved_config
    assert config is not None
    strips = tuple(strip_state() for _ in range(8))
    state = Snapshot(fingerprint(config), True, True, None, strips, features=FEATURES)
    return dataclasses.replace(state, **changes)  # pyright: ignore[reportArgumentType]


def live_window(qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon, **changes: object) -> MainWindow:
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(snapshot(window, **changes))
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    return window


def test_the_button_starts_and_ends_the_test(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(device_test_module, "HEARTBEAT_MS", 10)
    window = live_window(qtbot, make_window, live_daemon)
    button = window.device_view.test_button
    assert button.isEnabled()

    click(qtbot, button)

    qtbot.waitUntil(lambda: StartTest() in live_daemon.requests)
    assert button.isChecked()
    assert not window.device_view.test_bar.isHidden()
    assert "Testing the device" in window.status.text()
    # a heartbeat keeps it going
    qtbot.waitUntil(lambda: KeepTest() in live_daemon.requests)

    click(qtbot, button)

    qtbot.waitUntil(lambda: EndTest() in live_daemon.requests)
    assert not button.isChecked()
    assert window.device_view.test_bar.isHidden()


def test_the_window_learns_why_the_daemon_ended_the_test_or_did_not_start_it(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = live_window(qtbot, make_window, live_daemon)
    button = window.device_view.test_button

    click(qtbot, button)
    live_daemon.send_line(encode_reply(Reply("test_ended", True, "the device went away")))
    qtbot.waitUntil(lambda: not button.isChecked())
    assert window.status.text() == "The test of the device ended: the device went away."

    click(qtbot, button)
    live_daemon.send_line(encode_reply(Reply("test", False, "The device is not connected.")))
    qtbot.waitUntil(lambda: not button.isChecked())
    assert window.status.text() == "The test did not start: The device is not connected."

    # the daemon goes away
    click(qtbot, button)
    live_daemon.close()
    qtbot.waitUntil(lambda: not button.isChecked())
    assert "the daemon went away" in window.status.text()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [({"features": ()}, "too old"), ({"device": False}, "The device is not connected.")],
)
def test_the_button_says_why_the_device_can_not_be_tested(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon, changes: dict[str, object], reason: str
):
    window = live_window(qtbot, make_window, live_daemon, **changes)
    button = window.device_view.test_button
    assert not button.isEnabled()
    assert reason in button.toolTip()


def test_while_testing_the_drawing_shows_the_device_and_not_the_twin(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = live_window(qtbot, make_window, live_daemon)
    window.document.set(("channel", "out", "label"), "Boxes")
    window.editor.edited()
    # the preview in the GUI draws the twin
    qtbot.waitUntil(lambda: window.device_view.shows_twin())

    click(qtbot, window.device_view.test_button)

    assert not window.device_view.shows_twin()
    # the window closes: the test ends
    window.close()
    qtbot.waitUntil(lambda: EndTest() in live_daemon.requests)
