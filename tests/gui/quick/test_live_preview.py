"""
The live preview of the window in Qt Quick, against a fake live view that takes requests: where it shows (the control
"Preview" of the shell reads `places` and sets `place`), what the daemon says about it, and when it ends.
"""

import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.gui.quick.conftest import MakeUi
from tests.gui.quick.device_support import device_of
from tests.support.gui import FakeLiveDaemon, strip_state
from tests.support.instance import RecordingInstance
from tests.support.quick import Ui
from xtouch_daemon.gui.domain.live_preview import Place
from xtouch_daemon.gui.qt import live_preview as live_preview_module
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


def snapshot(ui: Ui, preview: bool = False, features: tuple[str, ...] = FEATURES) -> Snapshot:
    """What the daemon tells: the saved file, or with `preview` the document as it is in the window."""
    device = device_of(ui)
    config = device.editor.validation.config if preview else device.document.saved_config
    assert config is not None
    strips = tuple(strip_state() for _ in range(8))
    return Snapshot(fingerprint(config), True, True, None, strips, preview=preview, features=features)


def place_of(ui: Ui, place: Place) -> dict[str, Any]:
    """The position of the control "Preview" of the shell for `place`."""
    return next(entry for entry in device_of(ui).places if entry["place"] == place.value)


def live_ui(make_ui: MakeUi, previewing: PreviewingDaemon, **options: object) -> Ui:
    ui = make_ui(live_socket=previewing.path, **options)
    device = device_of(ui)
    ui.wait_until(lambda: bool(previewing.clients))
    previewing.send(snapshot(ui))
    ui.wait_until(lambda: place_of(ui, Place.DEVICE)["enabled"])
    # the shell saves, and tells the daemon to load the file
    daemon = device.find_daemon()

    def save() -> bool:
        device.document.save()
        device.live_preview.saved()
        assert daemon is not None
        daemon.reload()
        device.editor.saved()
        return True

    device.save = save
    return ui


def edit(ui: Ui, label: str) -> None:
    """What typing a label into the form of a channel does."""
    device = device_of(ui)
    device.document.set(("channel", "out", "label"), label)
    device.editor.edited()


def switch_on(ui: Ui) -> None:
    device_of(ui).setPlace("device")
    assert device_of(ui).live_preview.on


def test_the_device_is_no_place_until_a_daemon_can_preview(make_ui: MakeUi, previewing: PreviewingDaemon) -> None:
    alone = make_ui(find_daemon=lambda: None)
    assert not place_of(alone, Place.DEVICE)["enabled"]
    assert not place_of(alone, Place.DEVICE)["checked"]
    assert place_of(alone, Place.DEVICE)["tip"].startswith("No daemon runs")
    # in the GUI by default
    assert place_of(alone, Place.GUI)["checked"]
    assert device_of(alone).place == "gui"
    assert [entry["text"] for entry in device_of(alone).places] == ["In the GUI", "On the device", "Off"]

    # a daemon from before the preview
    ui = make_ui(live_socket=previewing.path)
    device = device_of(ui)
    ui.wait_until(lambda: bool(previewing.clients))
    previewing.send(snapshot(ui, features=()))
    ui.wait_until(lambda: device.live.snapshot is not None)
    assert not place_of(ui, Place.DEVICE)["enabled"]
    assert "too old" in place_of(ui, Place.DEVICE)["tip"]
    assert "too old" in place_of(ui, Place.GUI)["tip"]
    assert not place_of(ui, Place.GUI)["enabled"]

    previewing.send(snapshot(ui))
    ui.wait_until(lambda: place_of(ui, Place.DEVICE)["enabled"])
    assert place_of(ui, Place.DEVICE)["tip"].startswith("Runs the changes, and Simulate while it is open")
    assert device.live_preview.place == Place.GUI


def test_the_control_shows_while_there_is_something_to_preview(make_ui: MakeUi, previewing: PreviewingDaemon) -> None:
    ui = live_ui(make_ui, previewing)
    device = device_of(ui)
    assert not device.previewShown

    edit(ui, "Boxes")

    assert device.previewShown
    # where Simulate shows, for its bar
    assert device.placeNote == "In the GUI"
    switch_on(ui)
    assert device.placeNote == "On the device"
    device.setPlace("off")
    assert place_of(ui, Place.OFF)["checked"]


def test_the_device_follows_the_editor_while_the_live_preview_is_on(
    qtbot: QtBot, make_ui: MakeUi, previewing: PreviewingDaemon
) -> None:
    ui = live_ui(make_ui, previewing)
    device = device_of(ui)

    switch_on(ui)
    # nothing to preview yet: the device runs the file
    assert previewing.requests == []

    edit(ui, "Boxes")
    ui.wait_until(lambda: bool(previewing.previews))
    ui.wait_until(lambda: device.live_preview.running)
    # typing sends once it rests, the whole file with its comments
    (text,) = previewing.previews
    assert 'label = "Boxes"' in text
    assert text.startswith("# my mixer")
    # sending again changes nothing: the daemon has it already
    device.live_preview.send()
    assert len(previewing.previews) == 1

    # the daemon runs it, and the drawing says so
    previewing.send(snapshot(ui, preview=True))
    ui.wait_until(lambda: device.live.snapshot is not None and device.live.snapshot.preview)
    assert device.previewing()
    assert device.drawing.simulating
    assert not ui.grab().isNull()

    # undone: back to the file; redone: previewed again
    device.editor.undo()
    ui.wait_until(lambda: previewing.ends() == 1)
    assert not device.live_preview.running
    device.editor.redo()
    ui.wait_until(lambda: len(previewing.previews) == 2)

    # the heartbeat, while a preview runs
    device.live_preview.heartbeat.timeout.emit()
    ui.wait_until(lambda: isinstance(previewing.requests[-1], KeepPreview))

    # off: back to the file
    device.setPlace("off")
    ui.wait_until(lambda: previewing.ends() == 2)
    # no heartbeat without a preview
    count = len(previewing.requests)
    device.live_preview._beat()  # pyright: ignore[reportPrivateUsage]
    qtbot.wait(20)
    assert len(previewing.requests) == count


def test_the_daemon_says_why_it_did_not_take_a_change(make_ui: MakeUi, previewing: PreviewingDaemon) -> None:
    ui = live_ui(make_ui, previewing)
    device = device_of(ui)
    switch_on(ui)
    previewing.answer = lambda request: Reply("preview", False, "A preview can't change the [mqtt] section.")

    edit(ui, "Boxes")
    ui.wait_until(lambda: device.previewMessage != "")

    assert device.previewMessage == "The preview keeps the version before: A preview can't change the [mqtt] section."
    assert not device.live_preview.running
    # taken, with something to know
    previewing.answer = lambda request: Reply("preview", True, "The device name changes only with a restart.")
    edit(ui, "Desk")
    ui.wait_until(lambda: device.live_preview.running)
    assert device.previewMessage == "The device name changes only with a restart."
    # a request it did not understand
    previewing.reply(Reply("error", False, "Can't read the request"))
    ui.wait_until(lambda: "Can't read the request" in device.previewMessage)


def test_a_document_with_problems_is_not_previewed(make_ui: MakeUi, previewing: PreviewingDaemon) -> None:
    ui = live_ui(make_ui, previewing)
    device = device_of(ui)
    switch_on(ui)

    device.document.set(("channel", "out", "color"), "pink")
    device.editor.edited()
    # what the debounce does when its time is over
    device.live_preview.debounce.timeout.emit()

    assert previewing.previews == []


def test_saving_makes_the_preview_the_file(
    make_ui: MakeUi, previewing: PreviewingDaemon, daemon: RecordingInstance
) -> None:
    ui = live_ui(make_ui, previewing)
    device = device_of(ui)
    switch_on(ui)
    edit(ui, "Boxes")
    ui.wait_until(lambda: device.live_preview.running)

    assert device.save()
    assert daemon.reloads == [1234]
    # the reload ends the preview, as the window expects: it stays on for the next change
    previewing.reply(Reply("ended", True, "the configuration file was loaded"))
    # and an answer to a preview that ended meanwhile means nothing now, nor one about something else
    previewing.reply(Reply("preview", True))
    previewing.reply(Reply("mode", True, "gaming"))
    ui.qtbot.wait(50)
    assert device.live_preview.on
    assert not device.live_preview.running
    assert device.previewMessage == ""

    edit(ui, "Desk")
    ui.wait_until(lambda: len(previewing.previews) == 2)


def test_the_daemon_ends_the_preview_for_another_window(make_ui: MakeUi, previewing: PreviewingDaemon) -> None:
    ui = live_ui(make_ui, previewing)
    device = device_of(ui)
    switch_on(ui)
    edit(ui, "Boxes")
    ui.wait_until(lambda: device.live_preview.running)

    previewing.reply(Reply("ended", True, "another window previews on the device now"))
    ui.wait_until(lambda: not device.live_preview.on)
    # and the daemon took it there: its answer keeps why
    ui.wait_until(lambda: device.live_preview.running)

    # back in the GUI, on the twin
    assert place_of(ui, Place.GUI)["checked"]
    assert device.previewMessage == (
        "The preview on the device ended: another window previews on the device now. It shows in the GUI now."
    )
    last = previewing.requests[-1]
    assert isinstance(last, StartPreview)
    assert not last.on_device
    # it ended already: the window does not end it again
    assert previewing.ends() == 0


def test_the_preview_ends_with_the_daemon(make_ui: MakeUi, previewing: PreviewingDaemon) -> None:
    ui = live_ui(make_ui, previewing)
    device = device_of(ui)
    switch_on(ui)
    edit(ui, "Boxes")
    ui.wait_until(lambda: device.live_preview.running)

    previewing.close()
    ui.wait_until(lambda: device.live.snapshot is None)

    assert not device.live_preview.on
    assert not device.live_preview.running
    assert not place_of(ui, Place.DEVICE)["enabled"]
    # nothing to send to
    assert not device.live.send(KeepPreview())


def test_closing_goes_back_to_the_file(make_ui: MakeUi, previewing: PreviewingDaemon) -> None:
    ui = live_ui(make_ui, previewing)
    device = device_of(ui)
    switch_on(ui)
    edit(ui, "Boxes")
    ui.wait_until(lambda: device.live_preview.running)

    ui.window.close()

    ui.wait_until(lambda: previewing.ends() == 1)


def test_a_new_window_goes_on_with_the_preview_where_it_was(
    make_ui: MakeUi, previewing: PreviewingDaemon, path: Path
) -> None:
    from PyQt6.QtCore import QRect

    from xtouch_daemon.gui.domain.history import History
    from xtouch_daemon.gui.domain.slots_document import SlotsDocument
    from xtouch_daemon.gui.qt.window.session import Session

    document = SlotsDocument.open(path)
    session = Session(
        History(document),
        "slots",
        QRect(),
        False,
        device_of(live_ui(make_ui, previewing)).app.deps.read_audio(),
        preview="device",
    )

    ui = make_ui(live_socket=previewing.path, session=session, document=document)
    device = device_of(ui)
    ui.wait_until(lambda: len(previewing.clients) == 2)
    previewing.send(snapshot(ui))
    ui.wait_until(lambda: device.live_preview.on)

    assert place_of(ui, Place.DEVICE)["checked"]
    assert device.resume_place is None
    # a new start shows it in the GUI
    assert make_ui().app.device.place == "gui"  # pyright: ignore[reportAttributeAccessIssue]
