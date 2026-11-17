"""
The live view of the running daemon in the window.
"""

from pathlib import Path

from pytestqt.qtbot import QtBot

from tests.support.gui import FakeLiveDaemon, MakeWindow, snapshot, strip_state
from tests.support.instance import RecordingInstance
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
    assert window.mode_pill.text() == "Live"
    assert window.sync_label.text() == "The device runs the saved file."
    # Select flashes
    assert window.device_view.preview.blinker.isActive()
    blink = window.device_view.preview.blink
    window.device_view.preview.blinker.timeout.emit()
    assert window.device_view.preview.blink != blink
    assert not window.device_view.preview.grab().isNull()

    # an edit: the device runs the file until it is saved
    window.document.set(("channel", "out", "label"), "Boxes")
    window.editor.edited()
    assert window.device_view.preview.strips[0].face.live
    assert window.sync_label.text() == "The device runs the saved file. There are unsaved changes."
    assert not window.device_view.preview.grab().isNull()

    # saved: the daemon takes a moment
    assert window.save()
    assert daemon.reloads == [1234]
    assert window.sync_label.text() == "Applying the saved file…"
    # it did not take it
    window.applying.stop()
    window.applying.timeout.emit()
    assert window.sync_label.text() == "The device does not run the saved file yet."
    assert "journalctl --user -u xtouch-daemon" in window.sync_label.toolTip()
    # it did
    live_daemon.send(snapshot(window, first, device=False))
    qtbot.waitUntil(lambda: window.sync_label.text() == "The device runs the saved file.")
    assert window.mode_pill.text() == "Live · X-Touch-Ext not connected"

    # the daemon ended: the file again
    live_daemon.close()
    qtbot.waitUntil(lambda: window.live.snapshot is None)
    assert window.mode_pill.text() == "File preview"
    assert not window.device_view.preview.strips[0].face.live


def test_the_live_view_ends_with_the_daemon(qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon):
    running: list[Instance | None] = [RecordingInstance(1234, Path("/elsewhere.toml"), systemd=True)]
    window = make_window(find_daemon=lambda: running[0], live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(snapshot(window, strip_state()))
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    assert window.sync_label.text() == "The daemon reads /elsewhere.toml, not this file."
    # a line of another version means nothing
    live_daemon.send_line(b'{"version": 99}\n')
    qtbot.wait(20)
    assert window.live.snapshot is not None

    running[0] = None
    window.refresh_service()

    assert window.live.snapshot is None
    assert window.mode_pill.text() == "File preview"
    assert window.sync_label.text() == "Nothing runs this file."
