"""
The live view of the running daemon in the window.
"""

import tempfile
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.support.gui import FakeLiveDaemon, MakeWindow, pill, snapshot, strip_state
from tests.support.instance import RecordingInstance
from xtouch_daemon.gui.qt.window import main_window as main_window_module
from xtouch_daemon.system.instance import Instance


def test_the_preview_shows_the_device_live(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon, daemon: RecordingInstance
):
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    first = strip_state(
        ("Speaker", "46%"),
        color="cyan",
        leds={"rec": "off", "solo": "on", "mute": "on", "select": "flash"},
        ring=5,
        fader=0.46,
        touched=True,
        meter=6,
    )
    live_daemon.send(snapshot(window, first))
    qtbot.waitUntil(lambda: window.device_view.preview.strips[0].face.live)

    assert window.device_view.preview.strips[0].face.state == first
    assert pill(window.device_view.live_pill) == "Live"
    assert pill(window.changes_pill) == "Saved, running"
    # Select flashes
    assert window.device_view.preview.blinker.isActive()
    blink = window.device_view.preview.blink
    window.device_view.preview.blinker.timeout.emit()
    assert window.device_view.preview.blink != blink
    assert not window.device_view.preview.grab().isNull()

    # an edit: the preview shows it in the GUI, the device runs the file until it is saved
    window.document.set(("channel", "out", "label"), "Boxes")
    window.editor.edited()
    assert window.device_view.preview.strips[0].face.live
    assert pill(window.changes_pill) == "In the GUI, not saved"
    assert not window.device_view.preview.grab().isNull()

    # saved: the daemon takes a moment
    assert window.save()
    assert daemon.reloads == [1234]
    assert pill(window.changes_pill) == "Applying…"
    # it did not take it
    window.applying.stop()
    window.applying.timeout.emit()
    assert pill(window.changes_pill) == "Not on the device yet"
    assert "journalctl --user -u xtouch-daemon" in window.changes_pill.toolTip()
    # it did
    live_daemon.send(snapshot(window, first, device=False))
    qtbot.waitUntil(lambda: pill(window.changes_pill) == "Saved, running")
    assert pill(window.device_view.live_pill) == "Live · not connected"
    # nothing to show without the device
    assert window.device_view.preview.strips[0].face.look.detail == "The device is not connected."
    assert window.device_view.preview.strips[0].face.state.text == ("", "")

    # the daemon ended: dark strips
    live_daemon.close()
    qtbot.waitUntil(lambda: window.live.snapshot is None)
    assert pill(window.device_view.live_pill) == "No live view"
    assert not window.device_view.preview.strips[0].face.live


def test_the_live_view_ends_with_the_daemon(qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon):
    running: list[Instance | None] = [RecordingInstance(1234, Path("/elsewhere.toml"), systemd=True)]
    window = make_window(find_daemon=lambda: running[0], live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(snapshot(window, strip_state()))
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    assert pill(window.changes_pill) == "Runs another file"
    # a line of another version means nothing
    live_daemon.send_line(b'{"version": 99}\n')
    qtbot.wait(20)
    assert window.live.snapshot is not None

    running[0] = None
    window.refresh_service()

    assert window.live.snapshot is None
    assert pill(window.device_view.live_pill) == "No daemon"
    assert pill(window.changes_pill) == "Not running"


def test_a_daemon_that_starts_is_watched_at_once_not_at_the_next_poll(
    qtbot: QtBot, make_window: MakeWindow, monkeypatch: pytest.MonkeyPatch
):
    # so that the drawing shows the startup sequence from its start (it takes about a second)
    monkeypatch.setattr(main_window_module, "SERVICE_POLL_MS", 3_600_000)
    with tempfile.TemporaryDirectory(prefix="xtw-") as directory:
        socket = Path(directory) / "live.sock"
        window = make_window(live_socket=socket)
        assert window.live.snapshot is None
        # something else changes in the directory: nothing to do
        (Path(directory) / "other").write_text("")
        qtbot.wait(50)

        daemon = FakeLiveDaemon(socket)

        qtbot.waitUntil(lambda: bool(daemon.clients), timeout=1000)
        daemon.close()
