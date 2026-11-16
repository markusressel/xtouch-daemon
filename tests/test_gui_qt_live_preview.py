"""
The live preview of the window, against a fake live view that takes requests (see `test_gui_qt.py` for the setup:
offscreen, a fake systemctl, a configuration in a temporary directory, the dialogs answered by the tests).
"""

import dataclasses
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests import test_gui_qt
from tests.test_gui_qt import Dialogs, FakeLiveDaemon, MakeWindow, click, row, strip_state, type_into
from tests.test_instance import RecordingInstance
from xtouch_daemon.gui.qt import live_preview as live_preview_module
from xtouch_daemon.gui.qt.window import MainWindow
from xtouch_daemon.live.codec import decode_request, encode_reply
from xtouch_daemon.live.messages import (
    FEATURES,
    EndPreview,
    KeepPreview,
    Reply,
    Request,
    Snapshot,
    StartPreview,
    fingerprint,
)

# the fixtures of the window
isolated = test_gui_qt.isolated
path = test_gui_qt.path
systemctl = test_gui_qt.systemctl
daemon = test_gui_qt.daemon
make_window = test_gui_qt.make_window


@pytest.fixture(autouse=True)
def quick_previews(monkeypatch: pytest.MonkeyPatch) -> None:
    """An edit is previewed a moment after it, not after DEBOUNCE_MS: waiting for that adds nothing to the tests."""
    monkeypatch.setattr(live_preview_module, "DEBOUNCE_MS", 1)


class PreviewingDaemon(FakeLiveDaemon):
    """A live view that takes requests: it records them and answers like the daemon (`answer`)."""

    def __init__(self, path: Path):
        super().__init__(path)
        self.requests: list[Request] = []
        self.answer: Callable[[Request], Reply | None] = lambda request: (
            Reply("preview", True) if isinstance(request, StartPreview) else None
        )

    def _connected(self) -> None:
        while self.server.hasPendingConnections():
            client = self.server.nextPendingConnection()
            assert client is not None
            self.clients.append(client)
            client.readyRead.connect(lambda client=client: self._read(client))

    def _read(self, client: QLocalSocket) -> None:
        while client.canReadLine():
            request = decode_request(bytes(client.readLine().data()))
            self.requests.append(request)
            reply = self.answer(request)
            if reply is not None:
                client.write(encode_reply(reply))
                client.flush()

    def reply(self, reply: Reply) -> None:
        self.send_line(encode_reply(reply))

    @property
    def previews(self) -> list[str]:
        """The configurations sent for a preview."""
        return [request.config for request in self.requests if isinstance(request, StartPreview)]

    def ends(self) -> int:
        return sum(isinstance(request, EndPreview) for request in self.requests)


@pytest.fixture
def previewing(qapp: QApplication) -> Iterator[PreviewingDaemon]:
    # a short path: the one of a Unix socket has at most 107 bytes, which tmp_path may exceed
    with tempfile.TemporaryDirectory(prefix="xtp-") as directory:
        fake = PreviewingDaemon(Path(directory) / "live.sock")
        yield fake
        fake.close()


def snapshot(window: MainWindow, preview: bool = False, features: tuple[str, ...] = FEATURES) -> Snapshot:
    """What the daemon tells: the saved file, or with `preview` the document as it is in the window."""
    config = window.validation.config if preview else window.document.saved_config
    assert config is not None
    strips = tuple(strip_state() for _ in range(8))
    return Snapshot(fingerprint(config), True, True, None, strips, preview=preview, features=features)


def live_window(qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon, **options: object) -> MainWindow:
    window = make_window(live_socket=previewing.path, **options)
    qtbot.waitUntil(lambda: bool(previewing.clients))
    previewing.send(snapshot(window))
    qtbot.waitUntil(lambda: window.preview_switch.isEnabled())
    return window


def switch_on(qtbot: QtBot, window: MainWindow) -> None:
    click(qtbot, window.preview_switch)
    assert window.live_preview.on


def test_the_switch_is_off_until_a_daemon_can_preview(
    qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon
):
    alone = make_window(find_daemon=lambda: None)
    assert not alone.preview_switch.isEnabled()
    assert not alone.preview_switch.isChecked()
    assert alone.preview_switch.toolTip().startswith("No daemon runs")
    assert not alone.preview_pill.isVisible()

    # a daemon from before the live preview
    window = make_window(live_socket=previewing.path)
    qtbot.waitUntil(lambda: bool(previewing.clients))
    previewing.send(snapshot(window, features=()))
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    assert not window.preview_switch.isEnabled()
    assert "too old" in window.preview_label.toolTip()

    previewing.send(snapshot(window))
    qtbot.waitUntil(lambda: window.preview_switch.isEnabled())
    assert window.preview_switch.toolTip().startswith("The device runs the changes in the editor")
    assert not window.live_preview.on


def test_the_device_follows_the_editor_while_the_live_preview_is_on(
    qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon
):
    window = live_window(qtbot, make_window, previewing)

    switch_on(qtbot, window)
    # nothing to preview yet: the device runs the file
    assert previewing.requests == []
    assert window.preview_pill.text() == "Live preview"

    type_into(qtbot, row(window, "label").line, "Boxes")
    qtbot.waitUntil(lambda: bool(previewing.previews))
    qtbot.waitUntil(lambda: window.live_preview.running)
    # typing sends once it rests, the whole file with its comments
    (text,) = previewing.previews
    assert 'label = "Boxes"' in text
    assert text.startswith("# my mixer")
    assert window.preview_pill.text() == "Previewing unsaved changes"
    # picking another strip changes nothing: the daemon has it already
    window.select(1)
    window.live_preview.send()
    window.select(0)
    assert len(previewing.previews) == 1

    # the daemon runs it: the edited strip is live, and still marked
    previewing.send(snapshot(window, preview=True))
    qtbot.waitUntil(lambda: window.preview.strips[0].face.live)
    assert window.preview.strips[0].face.edited
    assert "live preview" in window.preview.strips[0].toolTip()
    assert window.sync_label.text() == "The device runs the unsaved changes (live preview). Save to keep them."
    assert not window.grab().isNull()

    # undone: back to the file; redone: previewed again
    window.undo()
    qtbot.waitUntil(lambda: previewing.ends() == 1)
    assert not window.live_preview.running
    window.redo()
    qtbot.waitUntil(lambda: len(previewing.previews) == 2)

    # the heartbeat, while a preview runs
    window.live_preview.heartbeat.timeout.emit()
    qtbot.waitUntil(lambda: isinstance(previewing.requests[-1], KeepPreview))

    # off: back to the file
    click(qtbot, window.preview_switch)
    qtbot.waitUntil(lambda: previewing.ends() == 2)
    assert not window.preview_pill.isVisible()
    # no heartbeat without a preview
    count = len(previewing.requests)
    window.live_preview._beat()
    qtbot.wait(20)
    assert len(previewing.requests) == count


def test_the_daemon_says_why_it_did_not_take_a_change(
    qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon
):
    window = live_window(qtbot, make_window, previewing)
    switch_on(qtbot, window)
    previewing.answer = lambda request: Reply("preview", False, "A preview can't change the [mqtt] section.")

    type_into(qtbot, row(window, "label").line, "Boxes")
    qtbot.waitUntil(lambda: window.preview_message.isVisible())

    assert window.preview_message.text() == (
        "The device keeps the version before: A preview can't change the [mqtt] section."
    )
    assert not window.live_preview.running
    # taken, with something to know
    previewing.answer = lambda request: Reply("preview", True, "The device name changes only with a restart.")
    type_into(qtbot, row(window, "label").line, "Desk")
    qtbot.waitUntil(lambda: window.live_preview.running)
    assert window.preview_message.text() == "The device name changes only with a restart."
    # a request it did not understand
    previewing.reply(Reply("error", False, "Can't read the request"))
    qtbot.waitUntil(lambda: "Can't read the request" in window.preview_message.text())


def test_a_document_with_problems_is_not_previewed(qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon):
    window = live_window(qtbot, make_window, previewing)
    switch_on(qtbot, window)

    window.document.set(("strip", 0, "color"), "pink")
    window.editor.edited()
    # what the debounce does when its time is over
    window.live_preview.debounce.timeout.emit()

    assert previewing.previews == []
    assert window.preview_pill.text() == "Live preview paused"


def test_saving_makes_the_preview_the_file(
    qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon, daemon: RecordingInstance
):
    window = live_window(qtbot, make_window, previewing)
    switch_on(qtbot, window)
    type_into(qtbot, row(window, "label").line, "Boxes")
    qtbot.waitUntil(lambda: window.live_preview.running)

    assert window.save()
    assert daemon.reloads == [1234]
    # the reload ends the preview, as the window expects: it stays on for the next change
    previewing.reply(Reply("ended", True, "the configuration file was loaded"))
    # and an answer to a preview of before means nothing now
    previewing.reply(Reply("preview", True))
    qtbot.wait(50)
    assert window.live_preview.on
    assert not window.live_preview.running
    assert not window.preview_message.isVisible()
    assert window.preview_pill.text() == "Live preview"

    type_into(qtbot, row(window, "label").line, "Desk")
    qtbot.waitUntil(lambda: len(previewing.previews) == 2)


def test_the_daemon_ends_the_preview_for_another_window(
    qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon
):
    window = live_window(qtbot, make_window, previewing)
    switch_on(qtbot, window)
    type_into(qtbot, row(window, "label").line, "Boxes")
    qtbot.waitUntil(lambda: window.live_preview.running)

    previewing.reply(Reply("ended", True, "another window previews now"))
    qtbot.waitUntil(lambda: not window.live_preview.on)

    assert not window.preview_switch.isChecked()
    assert window.preview_message.text() == "The live preview ended: another window previews now."
    # it ended already: the window does not end it again
    assert previewing.ends() == 0


def test_the_preview_ends_with_the_daemon(qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon):
    window = live_window(qtbot, make_window, previewing)
    switch_on(qtbot, window)
    type_into(qtbot, row(window, "label").line, "Boxes")
    qtbot.waitUntil(lambda: window.live_preview.running)

    previewing.close()
    qtbot.waitUntil(lambda: window.live.snapshot is None)

    assert not window.live_preview.on
    assert not window.live_preview.running
    assert not window.preview_switch.isEnabled()
    # nothing to send to
    assert not window.live.send(KeepPreview())


def test_closing_goes_back_to_the_file(
    qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon, isolated: Dialogs
):
    window = live_window(qtbot, make_window, previewing)
    switch_on(qtbot, window)
    type_into(qtbot, row(window, "label").line, "Boxes")
    qtbot.waitUntil(lambda: window.live_preview.running)

    assert window.close()

    assert "The device runs them now (live preview): without saving, it goes back to the file." in isolated.shown[-1]
    qtbot.waitUntil(lambda: previewing.ends() == 1)


def test_a_new_zoom_goes_on_with_the_preview(qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon):
    window = live_window(qtbot, make_window, previewing)
    switch_on(qtbot, window)
    session = window.session()
    assert session.live_preview
    window.rezoom = 1.25
    window.close()
    assert not window.live_preview.on

    after = make_window(live_socket=previewing.path, session=session)
    qtbot.waitUntil(lambda: len(previewing.clients) == 2)
    previewing.send(snapshot(after))
    qtbot.waitUntil(lambda: after.live_preview.on)
    assert after.preview_switch.isChecked()
    # a new start has it off
    assert not dataclasses.replace(session, live_preview=False).live_preview
