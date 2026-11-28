"""
The live view of the running daemon on the drawing of the device in Qt Quick.
"""

import tempfile
from pathlib import Path

from pytestqt.qtbot import QtBot

from tests.gui.quick.conftest import MakeUi
from tests.gui.quick.device_support import device_of, drawing_of, snapshot
from tests.support.gui import FakeLiveDaemon, strip_state
from tests.support.instance import RecordingInstance
from xtouch_daemon.system.instance import Instance


def test_the_drawing_shows_the_device_live(make_ui: MakeUi, live_daemon: FakeLiveDaemon) -> None:
    ui = make_ui(live_socket=live_daemon.path)
    device = device_of(ui)
    shell = ui.app.shell
    drawing = drawing_of(ui)
    ui.wait_until(lambda: bool(live_daemon.clients))
    first = strip_state(
        ("Speaker", "46%"),
        color="cyan",
        leds={"rec": "off", "solo": "on", "mute": "on", "select": "flash"},
        ring=5,
        fader=0.46,
        touched=True,
        meter=6,
    )
    live_daemon.send(snapshot(ui, strips=(first, *snapshot(ui).strips[1:])))
    ui.wait_until(lambda: drawing.strips[0].face.live)

    assert drawing.strips[0].face.state == first
    assert device.liveStatus["text"] == "Live"
    # Select flashes
    assert drawing.blinker.isActive()
    blink = drawing.blink
    drawing.blinker.timeout.emit()
    assert drawing.blink != blink
    assert not ui.grab().isNull()

    # an edit: the drawing shows it in the GUI, the device runs the file until it is saved
    device.document.set(("channel", "out", "label"), "Boxes")
    device.editor.edited()
    assert drawing.strips[0].face.live
    assert not ui.grab().isNull()

    # without the device there is nothing to show (the file, not the preview, as it does after a save)
    shell.setPlace("off")
    live_daemon.send(snapshot(ui, strips=(first, *snapshot(ui).strips[1:]), device=False))
    ui.wait_until(lambda: device.liveStatus["text"] == "Live · not connected")
    assert drawing.strips[0].face.look.detail == "The device is not connected."
    assert drawing.strips[0].face.state.text == ("", "")

    # the daemon ended: dark strips
    live_daemon.close()
    ui.wait_until(lambda: shell.live.snapshot is None)
    assert device.liveStatus["text"] == "No live view"
    assert not drawing.strips[0].face.live


def test_the_live_view_ends_with_the_daemon(make_ui: MakeUi, live_daemon: FakeLiveDaemon) -> None:
    running: list[Instance | None] = [RecordingInstance(1234, Path("/elsewhere.toml"), systemd=True)]
    ui = make_ui(find_daemon=lambda: running[0], live_socket=live_daemon.path)
    device = device_of(ui)
    shell = ui.app.shell
    ui.wait_until(lambda: bool(live_daemon.clients))
    live_daemon.send(snapshot(ui))
    ui.wait_until(lambda: shell.live.snapshot is not None)
    # a line of another version means nothing
    live_daemon.send_line(b'{"version": 99}\n')
    ui.qtbot.wait(20)
    assert shell.live.snapshot is not None

    running[0] = None
    shell.refresh_service()

    assert shell.live.snapshot is None
    assert device.liveStatus["text"] == "No daemon"
    assert not device.testVisible


def test_a_daemon_that_starts_is_watched_at_once_not_at_the_next_poll(make_ui: MakeUi, qtbot: QtBot) -> None:
    # so that the drawing shows the startup sequence from its start (it takes about a second)
    with tempfile.TemporaryDirectory(prefix="xtw-") as directory:
        socket = Path(directory) / "live.sock"
        ui = make_ui(live_socket=socket)
        device_of(ui)
        shell = ui.app.shell
        assert shell.live.snapshot is None
        # something else changes in the directory: nothing to do
        (Path(directory) / "other").write_text("")
        qtbot.wait(50)

        daemon = FakeLiveDaemon(socket)

        qtbot.waitUntil(lambda: bool(daemon.clients), timeout=1000)
        daemon.close()
