"""
The live preview of the window, against a fake live view that takes requests (see `conftest.py` for the setup:
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

from tests.support.gui import (
    Dialogs,
    FakeLiveDaemon,
    MakeWindow,
    click,
    pill,
    row,
    show_channel,
    strip_state,
    type_into,
)
from tests.support.instance import RecordingInstance
from xtouch_daemon.gui.domain.live_preview import Place
from xtouch_daemon.gui.qt import live_preview as live_preview_module
from xtouch_daemon.gui.qt.window.main_window import MainWindow
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
        """The configurations sent for a preview on the device."""
        return [
            request.config
            for request in self.requests
            if isinstance(request, StartPreview) and request.config and request.on_device
        ]

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
    qtbot.waitUntil(lambda: window.place_buttons[Place.DEVICE].isEnabled())
    show_channel(window, "out")
    return window


def switch_on(qtbot: QtBot, window: MainWindow) -> None:
    click(qtbot, window.place_buttons[Place.DEVICE])
    assert window.live_preview.on


def test_the_device_is_no_place_until_a_daemon_can_preview(
    qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon
):
    alone = make_window(find_daemon=lambda: None)
    device = alone.place_buttons[Place.DEVICE]
    assert not device.isEnabled()
    assert not device.isChecked()
    assert device.toolTip().startswith("No daemon runs")
    # in the GUI by default
    assert alone.place_buttons[Place.GUI].isChecked()

    # a daemon from before the preview
    window = make_window(live_socket=previewing.path)
    qtbot.waitUntil(lambda: bool(previewing.clients))
    previewing.send(snapshot(window, features=()))
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    assert not window.place_buttons[Place.DEVICE].isEnabled()
    assert "too old" in window.place_buttons[Place.DEVICE].toolTip()
    assert "too old" in window.place_buttons[Place.GUI].toolTip()

    previewing.send(snapshot(window))
    qtbot.waitUntil(lambda: window.place_buttons[Place.DEVICE].isEnabled())
    assert window.place_buttons[Place.DEVICE].toolTip().startswith("Runs the changes, and Simulate while it is open")
    assert window.live_preview.place == Place.GUI


def test_the_device_follows_the_editor_while_the_live_preview_is_on(
    qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon
):
    window = live_window(qtbot, make_window, previewing)

    switch_on(qtbot, window)
    # nothing to preview yet: the device runs the file
    assert previewing.requests == []
    assert pill(window.changes_pill) == "Saved, on the device"

    type_into(qtbot, row(window, "label").line, "Boxes")
    qtbot.waitUntil(lambda: bool(previewing.previews))
    qtbot.waitUntil(lambda: window.live_preview.running)
    # typing sends once it rests, the whole file with its comments
    (text,) = previewing.previews
    assert 'label = "Boxes"' in text
    assert text.startswith("# my mixer")
    assert pill(window.changes_pill) == "Sending to the device…"
    # sending again changes nothing: the daemon has it already
    window.live_preview.send()
    assert len(previewing.previews) == 1

    # the daemon runs it
    previewing.send(snapshot(window, preview=True))
    qtbot.waitUntil(lambda: window.live.snapshot is not None and window.live.snapshot.preview)
    assert pill(window.changes_pill) == "On the device, not saved"
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
    click(qtbot, window.place_buttons[Place.OFF])
    qtbot.waitUntil(lambda: previewing.ends() == 2)
    assert pill(window.changes_pill) == "Off: the device runs the file"
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
        "The preview keeps the version before: A preview can't change the [mqtt] section."
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

    window.document.set(("channel", "out", "color"), "pink")
    window.editor.edited()
    # what the debounce does when its time is over
    window.live_preview.debounce.timeout.emit()

    assert previewing.previews == []
    assert pill(window.changes_pill) == "Paused: problems"


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
    # and an answer to a preview of before means nothing now, nor one about something else
    previewing.reply(Reply("preview", True))
    previewing.reply(Reply("mode", True, "gaming"))
    qtbot.wait(50)
    assert window.live_preview.on
    assert not window.live_preview.running
    assert not window.preview_message.isVisible()
    assert pill(window.changes_pill) == "Applying…"

    type_into(qtbot, row(window, "label").line, "Desk")
    qtbot.waitUntil(lambda: len(previewing.previews) == 2)


def test_the_daemon_ends_the_preview_for_another_window(
    qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon
):
    window = live_window(qtbot, make_window, previewing)
    switch_on(qtbot, window)
    type_into(qtbot, row(window, "label").line, "Boxes")
    qtbot.waitUntil(lambda: window.live_preview.running)

    previewing.reply(Reply("ended", True, "another window previews on the device now"))
    qtbot.waitUntil(lambda: not window.live_preview.on)

    # back in the GUI, on the twin
    assert window.place_buttons[Place.GUI].isChecked()
    assert window.preview_message.text() == (
        "The preview on the device ended: another window previews on the device now. It shows in the GUI now."
    )
    last = previewing.requests[-1]
    assert isinstance(last, StartPreview)
    assert not last.on_device
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
    assert not window.place_buttons[Place.DEVICE].isEnabled()
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

    assert (
        "The device runs them now (Preview: On the device): without saving, it goes back to the file."
        in isolated.shown[-1]
    )
    qtbot.waitUntil(lambda: previewing.ends() == 1)


def test_a_new_zoom_goes_on_with_the_preview(qtbot: QtBot, make_window: MakeWindow, previewing: PreviewingDaemon):
    window = live_window(qtbot, make_window, previewing)
    switch_on(qtbot, window)
    session = window.session()
    assert session.preview == "device"
    window.rezoom = 1.25
    window.close()

    after = make_window(live_socket=previewing.path, session=session)
    qtbot.waitUntil(lambda: len(previewing.clients) == 2)
    previewing.send(snapshot(after))
    qtbot.waitUntil(lambda: after.live_preview.on)
    assert after.place_buttons[Place.DEVICE].isChecked()
    # a new start shows it in the GUI
    assert dataclasses.replace(session, preview="gui").preview == "gui"
