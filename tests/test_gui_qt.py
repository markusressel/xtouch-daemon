"""
The widgets of the GUI, offscreen (see conftest.py), with a fake systemctl, a fake sound server, a configuration in a
temporary directory, and the dialogs answered by the tests.
"""

import dataclasses
import signal
import tempfile
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QSettings, Qt
from PyQt6.QtGui import QColor, QContextMenuEvent, QTextDocument
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)
from pytestqt.qtbot import QtBot

from tests.conftest import output, source, stream
from tests.test_instance import RecordingInstance
from tests.test_systemd import FakeSystemctl
from xtouch_daemon import live
from xtouch_daemon.audio.model import AudioState, Card, Profile
from xtouch_daemon.audio.pulse import SoundServerError
from xtouch_daemon.config import MqttConfig
from xtouch_daemon.gui import qt
from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.domain.schema import Option, strip_options
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.qt import preview, theme
from xtouch_daemon.gui.qt import preview as preview_module
from xtouch_daemon.gui.qt import window as window_module
from xtouch_daemon.gui.qt.fields import Chips, OptionRow, Switch, Tables
from xtouch_daemon.gui.qt.pages import AliasesPage, BrokerTest, SectionPage
from xtouch_daemon.gui.qt.window import MainWindow
from xtouch_daemon.instance import Instance
from xtouch_daemon.live import MqttState, Snapshot, StripState
from xtouch_daemon.systemd import UNIT_NAME, Service, ServiceError

CONFIG = """\
# my mixer
[behavior]
max_volume = 120

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[[strip]]
type = "output"
device = "speaker"
label = "Speaker"
color = "cyan"

[[strip]]
type = "apps"
match = ["brave"]
label = "Browser"
"""

STATE = AudioState(
    outputs=(output("speaker", card="onboard"), output("buds")),
    inputs=(source("mic"),),
    streams=(stream(1, "Brave", "brave"), stream(2, "WEBRTC VoiceEngine", "Discord")),
    default_output="speaker",
    cards=(
        Card(
            "onboard",
            "output:analog-stereo",
            (
                Profile("output:analog-stereo", "Analog Stereo Output"),
                Profile("output:iec958-stereo", "Digital Output"),
            ),
        ),
    ),
)

RUNNING = "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
STOPPED = "LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled\n"
MISSING = "LoadState=not-found\nActiveState=inactive\nUnitFileState=\n"


class Dialogs:
    """Answers the message boxes, and records them."""

    def __init__(self) -> None:
        self.answer = QMessageBox.StandardButton.Discard
        self.shown: list[str] = []

    def question(self, parent: object, title: str, text: str, *args: object) -> QMessageBox.StandardButton:
        self.shown.append(text)
        return self.answer

    def message(self, parent: object, title: str, text: str) -> QMessageBox.StandardButton:
        self.shown.append(text)
        return QMessageBox.StandardButton.Ok


@pytest.fixture(autouse=True)
def isolated(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dialogs:
    """QSettings, the configuration and the unit in the temporary directory, and no dialog that waits for a user."""
    QCoreApplication.setOrganizationName("xtouch-daemon-test")
    QCoreApplication.setApplicationName("xtouch-daemon-test")
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    dialogs = Dialogs()
    monkeypatch.setattr(QMessageBox, "question", dialogs.question)
    monkeypatch.setattr(QMessageBox, "warning", dialogs.message)
    monkeypatch.setattr(QMessageBox, "critical", dialogs.message)
    theme.apply_theme(theme.ThemeMode.DARK)
    return dialogs


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """The configuration file the service reads."""
    result = tmp_path / "xtouch-daemon" / "config.toml"
    result.parent.mkdir()
    result.write_text(CONFIG)
    return result


@pytest.fixture
def systemctl() -> FakeSystemctl:
    return FakeSystemctl(RUNNING)


@pytest.fixture
def daemon(path: Path) -> RecordingInstance:
    """The service, which reads the file."""
    return RecordingInstance(1234, path.resolve(), systemd=True)


type MakeWindow = Callable[..., MainWindow]


async def unreachable_broker(config: MqttConfig) -> Status:
    """No test of the MQTT settings reaches out to a real broker."""
    return Status(f"Can't connect to {config.host}:{config.port}: Connection refused.", Tone.BAD, "Is it running?")


@pytest.fixture
def make_window(qtbot: QtBot, path: Path, systemctl: FakeSystemctl, daemon: RecordingInstance) -> MakeWindow:
    def make(
        read_audio: Callable[[], AudioState] = lambda: STATE,
        file: Path = path,
        find_daemon: Callable[[], Instance | None] = lambda: daemon,
        live_socket: Path | None = None,
        test_broker: BrokerTest = unreachable_broker,
    ) -> MainWindow:
        document = ConfigDocument.open(file)
        window = MainWindow(document, Service(systemctl), read_audio, find_daemon, live_socket, test_broker)
        qtbot.addWidget(window)
        window.show()
        qtbot.waitUntil(lambda: window.audio_label.text() != "Reading the sound server…")
        return window

    return make


@pytest.fixture
def window(make_window: MakeWindow) -> MainWindow:
    return make_window()


def row_options(strip_type: str, name: str) -> Option:
    return next(option for option in strip_options(strip_type) if option.name == name)


def row(window: MainWindow, name: str, page: str = "strip") -> OptionRow:
    return next(option_row for option_row in window.pages[page].rows if option_row.option.name == name)


def buttons[T: QAbstractButton](parent: QWidget, kind: type[T], match: Callable[[T], bool]) -> list[T]:
    """The buttons on `parent` that `match`, without the ones of replaced pages that wait for their deletion."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return [button for button in parent.findChildren(kind) if match(button)]


def type_into(qtbot: QtBot, edit: QLineEdit, text: str) -> None:
    edit.selectAll()
    qtbot.keyClick(edit, Qt.Key.Key_Backspace)
    qtbot.keyClicks(edit, text)


def click(qtbot: QtBot, button: object) -> None:
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # pyright: ignore[reportArgumentType]


# -- showing ------------------------------------------------------------------------------------------------------


def test_the_window_shows_the_configuration(window: MainWindow, path: Path):
    looks = [view.look for view in window.preview.strips]
    assert [(look.kind, look.label, look.color, look.configured) for look in looks[:3]] == [
        ("output", "Speaker", "cyan", True),
        ("apps", "Browser", "white", True),
        ("auto", "auto", "white", False),
    ]
    assert window.audio_label.text() == "Sound server: 2 outputs, 1 input, 2 applications"
    assert window.path_label.text() == f"{path}  ·  saved"
    assert not window.save_button.isEnabled()
    assert not window.problems_button.isVisible()
    assert window.pill.text() == "running"
    assert window.service_button.text() == "Restart"
    assert row(window, "label").line.text() == "Speaker"
    # the preview paints
    assert not window.grab().isNull()


def test_a_click_on_a_strip_edits_it(qtbot: QtBot, window: MainWindow):
    click(qtbot, window.preview.strips[1])

    assert window.selected == 1
    assert window.tabs.tabText(0) == "Strip 2 · Browser"
    assert row(window, "match").chips.values == ["brave"]


def test_without_the_sound_server_names_are_typed_by_hand(make_window: MakeWindow):
    def unreachable() -> AudioState:
        raise SoundServerError("can't reach the sound server: no socket")

    window = make_window(unreachable)

    assert window.audio_label.text() == "Sound server not reachable: type names by hand"
    assert window.audio_label.toolTip() == "can't reach the sound server: no socket"


# -- editing ------------------------------------------------------------------------------------------------------


def test_an_edit_shows_in_the_preview_and_is_saved(
    qtbot: QtBot, window: MainWindow, path: Path, daemon: RecordingInstance
):
    type_into(qtbot, row(window, "label").line, "Boxes")

    assert window.preview.strips[0].look.label == "Boxes"
    assert window.path_label.text().endswith("unsaved changes")
    assert window.save_button.isEnabled()

    click(qtbot, window.save_button)

    assert 'label = "Boxes"' in path.read_text()
    assert path.read_text().startswith("# my mixer\n")
    assert daemon.reloads == [1234]
    assert window.status.text() == "Saved and reloaded: the device shows the new configuration."
    assert not window.save_button.isEnabled()


def test_problems_are_shown_inline_and_block_saving(qtbot: QtBot, window: MainWindow, isolated: Dialogs):
    window.select(1)
    label = row(window, "label")
    type_into(qtbot, label.line, "")

    assert label.error.text() == "Field required"
    assert label.line.property("problem") is True
    assert window.problems_button.text() == "1 problem"
    assert window.preview.strips[1].look.problems == 1
    assert not window.save_button.isEnabled()

    assert not window.save()
    assert isolated.shown == ["Fix the problems first: the daemon would not take the file."]


def test_a_problem_leads_to_its_place(window: MainWindow):
    window.document.unset(("strip", 1, "label"))
    window.document.set(("behavior", "reset_volume"), 140)
    window.refresh()

    actions = window.problems_menu.actions()
    assert [action.text() for action in actions] == [
        "behavior: reset_volume (140) is above max_volume (120)",
        "strip[2].label: Field required",
    ]
    actions[1].trigger()
    assert window.selected == 1
    # selecting rebuilds the menu
    window.problems_menu.actions()[0].trigger()
    assert window.current_page == "behavior"
    assert window.pages["behavior"].problem.text() == "reset_volume (140) is above max_volume (120)"


def test_an_unknown_option_can_be_removed(make_window: MakeWindow, path: Path):
    path.write_text(CONFIG.replace("[aliases]", "typo = 1\n\n[aliases]"))
    window = make_window()

    (action,) = window.problems_menu.actions()
    assert action.text() == "behavior.typo: unknown option, click to remove it"
    assert window.pages["behavior"].problem.text() == "behavior.typo: Extra inputs are not permitted"

    action.trigger()

    assert window.validation.problems == []


def test_a_whole_configuration_problem_leads_to_the_section(window: MainWindow):
    window.document.set_strip_type(0, "homeassistant")
    window.refresh()

    (action,) = window.problems_menu.actions()
    assert action.text() == "strips in Home Assistant need an [mqtt] section"
    action.trigger()
    assert window.current_page == "mqtt"

    window.go_to(window.validation.problems[0].__class__((), "something else", "value_error"))
    assert window.current_page == "mqtt"


def test_the_type_of_a_strip_changes(qtbot: QtBot, window: MainWindow):
    (apps,) = [button for button in window.strip_page.types.buttons() if button.text() == "Apps"]

    click(qtbot, apps)

    assert window.document.strips[0].values == {"type": "apps", "label": "Speaker", "color": "cyan"}
    assert window.preview.strips[0].look.kind == "apps"
    assert row(window, "match").chips.values == []


def test_strips_move_and_go(qtbot: QtBot, window: MainWindow):
    def header(tip: str) -> QAbstractButton:
        (button,) = buttons(window.strip_page, QAbstractButton, lambda button: button.toolTip().startswith(tip))
        return button

    assert not header("Move it to the left").isEnabled()

    click(qtbot, header("Move it to the right"))
    assert [strip.type for strip in window.document.strips] == ["apps", "output"]
    assert window.selected == 1

    click(qtbot, header("Move it to the left"))
    assert [strip.type for strip in window.document.strips] == ["output", "apps"]
    assert window.selected == 0

    click(qtbot, header("Remove the strip"))
    assert [strip.type for strip in window.document.strips] == ["apps"]


def test_a_strip_that_is_not_configured_can_be_configured(qtbot: QtBot, window: MainWindow):
    window.select(4)
    (configure,) = [
        button for button in window.strip_page.findChildren(QPushButton) if button.text() == "Configure strip 5"
    ]

    click(qtbot, configure)

    assert [strip.type for strip in window.document.strips] == ["output", "apps", "auto", "auto", "auto"]
    assert window.preview.strips[4].look.configured
    assert [row.option.name for row in window.strip_page.rows] == [
        "color",
        "meter",
        "rec",
        "solo",
        "min_volume",
        "max_volume",
        "encoder",
        "fader",
        "id",
    ]


def test_an_empty_strip_has_no_options(window: MainWindow):
    window.document.set_strip_type(0, "empty")
    window.select(0)

    assert window.strip_page.rows == []


def test_a_strip_without_a_valid_type_shows_why(make_window: MakeWindow, path: Path):
    path.write_text('[[strip]]\ntype = "fader"\n')
    window = make_window()

    assert window.strip_page.rows == []
    assert window.strip_page.problem.text().startswith("Input tag 'fader' found using 'type'")


# -- the preview: moving strips ----------------------------------------------------------------------------------


def x_of(window: MainWindow, index: int) -> int:
    return window.preview.strips[index].x()


def test_a_dragged_strip_leaves_a_place_and_the_others_make_room(qtbot: QtBot, make_window: MakeWindow, path: Path):
    path.write_text(CONFIG + '\n[[strip]]\ntype = "auto"\n')
    window = make_window()
    preview = window.preview
    first, second, third = (x_of(window, index) for index in range(3))
    view = preview.strips[0]

    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    # a small move is still a click
    qtbot.mouseMove(view, QPoint(52, 51))
    assert not preview.dragging
    qtbot.mouseMove(view, QPoint(50 + third - first, 50))

    assert preview.dragging
    assert view.lifted
    # its place is free and the strips it passed moved over, gliding
    assert preview.drop_target == 2
    # back and forth: the strips change their way (the mouse is where the strip is now)
    qtbot.mouseMove(view, QPoint(50 + second - view.x(), 50))
    assert preview.drop_target == 1
    qtbot.mouseMove(view, QPoint(50 + third - view.x(), 50))
    assert preview.drop_target == 2
    qtbot.waitUntil(lambda: x_of(window, 1) == first and x_of(window, 2) == second)
    assert not window.grab().isNull()

    # dropped beyond the configured strips, it goes after the last one
    qtbot.mouseMove(view, QPoint(50 + 7 * (third - second), 50))
    assert preview.drop_target == 2
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(50 + 7 * (third - second), 50))

    assert not preview.dragging
    assert [strip.type for strip in window.document.strips] == ["apps", "auto", "output"]
    assert window.selected == 2
    assert [x_of(window, index) for index in range(3)] == [first, second, third]
    assert window.status.text() == "Moved strip 1 to place 3."


def test_escape_cancels_a_drag(qtbot: QtBot, window: MainWindow):
    preview = window.preview
    view = preview.strips[0]
    home = view.pos()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(view, QPoint(160, 50))
    assert preview.drop_target == 1

    qtbot.keyClick(preview, Qt.Key.Key_Escape)

    assert not preview.dragging
    assert view.pos() == home
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(160, 50))
    assert [strip.type for strip in window.document.strips] == ["output", "apps"]
    # a drag that ends where it started moves nothing either
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(view, QPoint(60, 50))
    qtbot.keyClick(view, Qt.Key.Key_Escape)
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(view, QPoint(60, 50))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(60, 50))
    assert [strip.type for strip in window.document.strips] == ["output", "apps"]
    assert window.history.can_undo is False


def test_strips_that_are_not_configured_do_not_move(qtbot: QtBot, window: MainWindow):
    view = window.preview.strips[6]
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    qtbot.mouseMove(view, QPoint(80, 60))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton)

    assert not window.preview.dragging
    assert window.selected == 6


def test_the_keyboard_selects_and_moves_strips(qtbot: QtBot, window: MainWindow):
    strips = window.preview.strips
    strips[0].setFocus()

    qtbot.keyClick(strips[0], Qt.Key.Key_Right)
    assert window.selected == 1
    qtbot.keyClick(strips[1], Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    assert [strip.type for strip in window.document.strips] == ["apps", "output"]
    assert window.selected == 0
    # not past the configured strips, nor past the ends
    qtbot.keyClick(strips[0], Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(strips[1], Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(strips[0], Qt.Key.Key_Left)
    assert [strip.type for strip in window.document.strips] == ["apps", "output"]

    qtbot.keyClick(strips[0], Qt.Key.Key_End)
    assert window.selected == 7
    qtbot.keyClick(strips[7], Qt.Key.Key_Delete)
    qtbot.keyClick(strips[7], Qt.Key.Key_A)
    assert len(window.document.strips) == 2
    qtbot.keyClick(strips[7], Qt.Key.Key_Home)
    assert window.selected == 0

    qtbot.keyClick(strips[0], Qt.Key.Key_Delete)
    assert [strip.type for strip in window.document.strips] == ["output"]
    assert window.status.text() == "Removed strip 1, the strips right of it moved left. Ctrl+Z brings it back."


def test_the_menu_of_a_strip(qtbot: QtBot, window: MainWindow):
    menu = window.preview.menu_for(1)
    left, right, _, remove = menu.actions()
    assert left.text() == "Move left\tCtrl+Left"
    assert not right.isEnabled()

    left.trigger()
    assert [strip.type for strip in window.document.strips] == ["apps", "output"]
    window.preview.menu_for(0).actions()[1].trigger()
    assert [strip.type for strip in window.document.strips] == ["output", "apps"]
    remove.trigger()
    assert [strip.type for strip in window.document.strips] == ["output"]

    (configure,) = window.preview.menu_for(4).actions()
    configure.trigger()
    assert len(window.document.strips) == 5
    assert window.selected == 4


def test_a_strip_that_is_not_configured_is_configured_by_a_double_click(qtbot: QtBot, window: MainWindow):
    qtbot.mouseDClick(window.preview.strips[3], Qt.MouseButton.LeftButton)
    assert len(window.document.strips) == 4
    # a configured one stays as it is
    qtbot.mouseDClick(window.preview.strips[0], Qt.MouseButton.LeftButton)
    assert len(window.document.strips) == 4


def test_the_context_menu_opens_on_the_strip(qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch):
    shown: list[list[str]] = []
    monkeypatch.setattr(QMenu, "exec", lambda menu, *args: shown.append([a.text() for a in menu.actions()]))
    view = window.preview.strips[5]
    qtbot.mousePress(view, Qt.MouseButton.RightButton)

    view.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), view.mapToGlobal(QPoint())))

    assert shown == [["Configure strip 6"]]
    assert window.selected == 5


# -- the live view ------------------------------------------------------------------------------------------------


class FakeLiveDaemon:
    """The live view of a daemon: a local server that sends the lines the test gives it."""

    def __init__(self, path: Path):
        self.server = QLocalServer()
        assert self.server.listen(str(path)), self.server.errorString()
        self.clients: list[QLocalSocket] = []
        self.server.newConnection.connect(self._connected)

    @property
    def path(self) -> Path:
        return Path(self.server.fullServerName())

    def _connected(self) -> None:
        while self.server.hasPendingConnections():
            client = self.server.nextPendingConnection()
            assert client is not None
            self.clients.append(client)

    def send_line(self, line: bytes) -> None:
        for client in self.clients:
            client.write(line)
            client.flush()

    def send(self, snapshot: Snapshot) -> None:
        self.send_line(live.encode(snapshot))

    def close(self) -> None:
        for client in self.clients:
            client.disconnectFromServer()
        self.clients = []
        self.server.close()


@pytest.fixture
def live_daemon(qapp: QApplication) -> Iterator[FakeLiveDaemon]:
    # a short path: the one of a Unix socket has at most 107 bytes, which tmp_path may exceed
    with tempfile.TemporaryDirectory(prefix="xtg-") as directory:
        fake = FakeLiveDaemon(Path(directory) / "live.sock")
        yield fake
        fake.close()


def strip_state(text: tuple[str, str] = ("", ""), **changes: object) -> StripState:
    state = StripState(
        color="off",
        text=text,
        leds={"rec": "off", "solo": "off", "mute": "off", "select": "off"},
        ring=0,
        ring_mode="dot",
        fader=None,
        touched=False,
        meter=0,
    )
    return dataclasses.replace(state, **changes)  # pyright: ignore[reportArgumentType]


def snapshot(window: MainWindow, first: StripState, device: bool = True) -> Snapshot:
    saved = window.document.saved_config
    assert saved is not None
    strips = (first, *(strip_state() for _ in range(7)))
    return Snapshot(live.fingerprint(saved), device, sound_server=True, mqtt=None, strips=strips)


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
    qtbot.waitUntil(lambda: window.preview.strips[0].face.live)

    assert window.preview.strips[0].face.state == first
    assert window.mode_pill.text() == "Live"
    assert window.sync_label.text() == "The device runs the saved file."
    # Select flashes
    assert window.preview.blinker.isActive()
    blink = window.preview.blink
    window.preview.blinker.timeout.emit()
    assert window.preview.blink != blink
    assert not window.preview.grab().isNull()

    # an edited strip shows how it will look, the others stay live
    type_into(qtbot, row(window, "label").line, "Boxes")
    face = window.preview.strips[0].face
    assert (face.live, face.edited, face.state.text[0]) == (False, True, "Boxes")
    assert window.preview.strips[1].face.live
    assert not window.preview.blinker.isActive()
    assert window.sync_label.text() == (
        "The device runs the saved file. 1 strip with unsaved changes show how they will look."
    )
    assert not window.preview.grab().isNull()

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
    assert not window.preview.strips[0].face.live


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


# -- undo ---------------------------------------------------------------------------------------------------------


def test_edits_are_undone_and_redone(qtbot: QtBot, window: MainWindow):
    assert not window.undo_button.isEnabled()
    type_into(qtbot, row(window, "label").line, "Boxes")
    window.remove_strip(1)
    assert window.undo_button.isEnabled()

    click(qtbot, window.undo_button)
    assert len(window.document.strips) == 2
    assert window.status.text() == "Undone."
    # typing into one option is one step
    window.select(0)
    window.undo()
    assert window.document.get(("strip", 0, "label")) == "Speaker"
    assert row(window, "label").line.text() == "Speaker"
    assert not window.undo_button.isEnabled()
    window.undo()

    click(qtbot, window.redo_button)
    assert window.document.get(("strip", 0, "label")) == "Boxes"
    assert window.status.text() == "Redone."
    window.redo()
    assert len(window.document.strips) == 1
    assert not window.redo_button.isEnabled()
    window.redo()


def test_undo_works_in_a_text_field_too(qtbot: QtBot, window: MainWindow):
    line = row(window, "label").line
    type_into(qtbot, line, "Boxes")
    line.setFocus()

    qtbot.keyClick(line, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert window.document.get(("strip", 0, "label")) == "Speaker"
    # other keys reach the field
    line = row(window, "label").line
    qtbot.waitUntil(line.isVisible)
    line.end(False)
    qtbot.keyClick(line, Qt.Key.Key_Backspace)
    assert window.document.get(("strip", 0, "label")) == "Speake"


def test_a_revert_can_be_undone(qtbot: QtBot, window: MainWindow):
    window.document.remove_strip(0)
    window.edited()
    click(qtbot, window.revert_button)
    assert len(window.document.strips) == 2

    window.undo()
    assert len(window.document.strips) == 1
    assert window.document.modified


# -- the preview: painting ---------------------------------------------------------------------------------------


def test_lit_leds_show_their_colors(window: MainWindow):
    view = window.preview.strips[0]
    mute, meter = QPoint(16, 177), QPoint(84, 200)
    dark = view.grab().toImage()
    face = view.face
    leds = {**face.state.leds, "mute": "on"}
    # what the live view shows: Mute lit, the meter a little up
    view.show_face(dataclasses.replace(face, state=dataclasses.replace(face.state, leds=leds, meter=3)), False)

    lit = view.grab().toImage()

    for point in (mute, meter):
        assert lit.pixelColor(point).lightness() > dark.pixelColor(point).lightness() + 60
    assert lit.pixelColor(mute).red() > 200 > lit.pixelColor(mute).green()
    assert lit.pixelColor(meter).green() > 150 > lit.pixelColor(meter).red()


def test_a_dragged_strip_is_outlined_and_its_place_shown(qtbot: QtBot, window: MainWindow):
    preview = window.preview
    edge = QPoint(3, 150)
    # below the lifted strip, where the place it goes to shows on the panel
    place = preview_module.slot_position(0) + QPoint(preview_module.WIDTH // 2, preview_module.HEIGHT - 6)
    strip_before = preview.strips[1].grab().toImage().pixelColor(edge)
    place_before = preview.grab().toImage().pixelColor(place)

    preview.start_drag(1, 10)
    preview.drag_to(preview_module.MARGIN_X + 10)

    assert preview.drop_target == 0
    # the strip that was there made room
    qtbot.waitUntil(lambda: preview.strips[0].pos() == preview_module.slot_position(1))
    assert preview.strips[1].grab().toImage().pixelColor(edge).blue() > strip_before.blue()
    assert preview.grab().toImage().pixelColor(place).blue() > place_before.blue() + 10
    preview.cancel_drag()


def luminance(color: str) -> float:
    def channel(value: int) -> float:
        value_ = value / 255
        return value_ / 12.92 if value_ <= 0.04045 else ((value_ + 0.055) / 1.055) ** 2.4

    rgb = QColor(color)
    return 0.2126 * channel(rgb.red()) + 0.7152 * channel(rgb.green()) + 0.0722 * channel(rgb.blue())


def contrast(foreground: str, background: str) -> float:
    """The contrast ratio of WCAG 2.2."""
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def over(color: str, background: str, alpha: int) -> str:
    """A translucent color on a background."""
    top, bottom = QColor(color).getRgb()[:3], QColor(background).getRgb()[:3]
    mix = [round(a * alpha / 255 + b * (1 - alpha / 255)) for a, b in zip(top, bottom, strict=True)]
    return QColor(*mix).name()


@pytest.mark.parametrize("mode", list(theme.ThemeMode))
def test_the_colors_are_legible(mode: theme.ThemeMode):
    """WCAG 2.2 AA: 4.5:1 for text, 3:1 for the outlines of controls."""
    colors = theme.THEMES[mode]
    surfaces = (colors.surface, colors.raised, colors.sunken, colors.chrome)
    for surface in surfaces:
        assert contrast(colors.text, surface) >= 4.5
        assert contrast(colors.text_muted, surface) >= 4.5
        assert contrast(colors.error, surface) >= 4.5
        assert contrast(colors.control_border, surface) >= 3
    assert contrast(colors.placeholder, colors.sunken) >= 4.5
    assert contrast(colors.on_accent, colors.accent) >= 4.5
    assert contrast(colors.on_accent, colors.accent_hover) >= 4.5
    assert contrast(colors.text, colors.accent_tint) >= 4.5
    for tone, background in (
        (colors.tone_good, colors.success),
        (colors.tone_warn, colors.warning),
        (colors.tone_bad, colors.error),
        (colors.tone_neutral, colors.tone_neutral),
    ):
        assert contrast(tone, over(background, colors.chrome, theme.TINT_ALPHA)) >= 4.5


def test_the_device_is_legible():
    hardware = theme.HARDWARE
    for name, color in theme.LCD_COLORS.items():
        text = theme.LCD_TEXT_OFF if name == "off" else theme.LCD_TEXT
        assert contrast(text, color) >= 4.5
        dimmed = over(color, theme.LCD_COLORS["off"], round(preview.DIM * 255))
        assert contrast(preview.LCD_TEXT_DIM, dimmed) >= 4.5
    for strip in (hardware.strip_top, hardware.strip_bottom):
        assert contrast(hardware.print, strip) >= 4.5
        assert contrast(hardware.print_dim, strip) >= 4.5
    assert contrast(hardware.badge_text, hardware.badge) >= 4.5
    for _, color in preview.BUTTONS:
        key = over(color, hardware.key, round(preview.KEY_TINT * 255))
        assert contrast(over(color, hardware.key_print, round(preview.LABEL_TINT * 255)), key) >= 4.5


# -- the fields ---------------------------------------------------------------------------------------------------


def test_numbers_switches_and_choices(qtbot: QtBot, window: MainWindow):
    window.show_page("behavior")
    spin = row(window, "encoder_step", "behavior").spin
    spin.setValue(3)
    assert window.document.get(("behavior", "encoder_step")) == 3

    hold = row(window, "auto_hold", "behavior").spin
    assert isinstance(hold, QDoubleSpinBox)
    hold.setValue(2.5)
    assert window.document.get(("behavior", "auto_hold")) == 2.5

    meters = row(window, "meters", "behavior")
    click(qtbot, meters.switch)
    assert window.document.get(("behavior", "meters")) is False
    assert not meters.reset.isHidden()

    click(qtbot, meters.reset)
    assert window.document.get(("behavior", "meters")) is None
    assert meters.switch.isChecked()

    rec = row(window, "rec")
    rec.combo.setCurrentText("muted")
    assert window.document.get(("strip", 0, "rec")) == "muted"


def test_switches_and_swatches_show_focus_and_disabled(qtbot: QtBot, window: MainWindow):
    window.show_page("behavior")
    switch = row(window, "meters", "behavior").switch
    swatch = row(window, "color").colors.swatches["red"]
    plain = (switch.grab().toImage(), swatch.grab().toImage())
    window.activateWindow()

    for widget, before in zip((switch, swatch), plain, strict=True):
        widget.setFocus()
        qtbot.waitUntil(widget.hasFocus)
        assert widget.grab().toImage() != before
    switch.setEnabled(False)
    assert switch.grab().toImage() != plain[0]


def test_colors_are_swatches(qtbot: QtBot, window: MainWindow):
    color = row(window, "color")
    assert color.colors.swatches["cyan"].isChecked()

    click(qtbot, color.colors.swatches["off"])

    assert window.document.get(("strip", 0, "color")) == "off"
    assert window.preview.strips[0].look.color == "off"
    # a value that is no color checks none
    color.colors.show_value("pink")
    assert not any(swatch.isChecked() for swatch in color.colors.swatches.values())
    assert not color.colors.grab().isNull()


def test_a_list_is_chips(qtbot: QtBot, window: MainWindow):
    window.select(1)
    chips: Chips = row(window, "match").chips

    type_into(qtbot, chips.input, "firefox")
    qtbot.keyClick(chips.input, Qt.Key.Key_Return)
    chips.add("firefox")
    chips.add("")
    assert window.document.get(("strip", 1, "match")) == ["brave", "firefox"]

    chips.remove(0)
    assert window.document.get(("strip", 1, "match")) == ["firefox"]
    assert chips.values == ["firefox"]
    # a chip, the input and the suggestions flow in the layout
    assert chips.flow.count() == 3


def test_suggestions_come_from_the_sound_server(qtbot: QtBot, window: MainWindow):
    device = row(window, "device")
    menu_button = next(button for button in device.findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()

    texts = [action.text() for action in menu.actions()]
    assert texts == ["speaker    speaker description (the default)", "buds    buds description"]
    menu.actions()[1].trigger()

    # added to the one of the file, which stood alone
    assert window.document.get(("strip", 0, "device")) == ["speaker", "buds"]
    assert device.chips.values == ["speaker", "buds"]


def test_an_empty_suggestion_list_says_so(make_window: MakeWindow):
    window = make_window(lambda: AudioState())
    window.select(1)
    menu_button = next(button for button in row(window, "match").findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()

    (action,) = menu.actions()
    assert action.text() == "The sound server has none right now"
    assert not action.isEnabled()


def test_typing_completes_from_the_sound_server(qtbot: QtBot, window: MainWindow):
    device = row(window, "device")
    click(qtbot, device.chips.chips[0].findChild(QToolButton))
    assert window.document.get(("strip", 0, "device")) is None
    assert device.chips.input.placeholderText() == "Add… (none: the default output)"

    type_into(qtbot, device.chips.input, "bu")
    completer = device.chips.input.completer()
    assert completer is not None
    assert completer.model().stringList() == ["speaker", "buds"]  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]

    completer.activated.emit("buds")
    assert window.document.get(("strip", 0, "device")) == ["buds"]


def test_an_unset_label_shows_the_default(qtbot: QtBot, window: MainWindow):
    label = row(window, "label")
    click(qtbot, label.reset)

    assert window.document.get(("strip", 0, "label")) is None
    assert label.line.placeholderText() == "speaker"
    # the device decides the default label, like on the device: the start of its description, or the type
    window.document.set(("strip", 0, "device"), ["buds"])
    label.load()
    assert label.line.placeholderText() == "buds de"
    window.document.unset(("strip", 0, "device"))
    label.load()
    assert label.line.placeholderText() == "Output"


# -- sections -----------------------------------------------------------------------------------------------------


def test_an_optional_section_is_added_and_removed(qtbot: QtBot, window: MainWindow):
    page = window.pages["mqtt"]
    assert isinstance(page, SectionPage)
    (add,) = [button for button in page.findChildren(QPushButton) if button.text() == "Add [mqtt]"]

    click(qtbot, add)

    assert window.document.has_section("mqtt")
    assert row(window, "host", "mqtt").error.text() == "Field required"
    password = row(window, "password", "mqtt")
    assert password.line.echoMode() == QLineEdit.EchoMode.Password
    type_into(qtbot, password.line, "secret")
    assert window.document.get(("mqtt", "password")) == "secret"
    reveal = next(button for button in password.findChildren(QToolButton) if button.isCheckable())
    click(qtbot, reveal)
    assert password.line.echoMode() == QLineEdit.EchoMode.Normal

    (remove,) = [button for button in page.findChildren(QPushButton) if button.text() == "Remove [mqtt]"]
    click(qtbot, remove)
    assert not window.document.has_section("mqtt")


def test_a_file_is_chosen_with_a_dialog(qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch):
    window.document.add_section("mqtt")
    window.reload_pages()
    password_file = row(window, "password_file", "mqtt")
    browse = next(button for button in password_file.findChildren(QToolButton) if button.toolTip() == "Choose the file")
    chosen = [str(Path.home() / ".mqtt-password"), "", "/etc/mqtt-password"]
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (chosen.pop(0), ""))

    click(qtbot, browse)
    assert window.document.get(("mqtt", "password_file")) == "~/.mqtt-password"
    click(qtbot, browse)
    assert window.document.get(("mqtt", "password_file")) == "~/.mqtt-password"
    click(qtbot, browse)
    assert window.document.get(("mqtt", "password_file")) == "/etc/mqtt-password"


def test_aliases_are_edited(qtbot: QtBot, window: MainWindow):
    page = window.pages["aliases"]
    assert isinstance(page, AliasesPage)
    (name, alias) = page.edits[0]
    assert (name.text(), alias.text()) == ("WEBRTC VoiceEngine", "Discord")

    (add,) = [button for button in page.findChildren(QPushButton) if button.text() == "Add alias"]
    click(qtbot, add)
    assert window.document.aliases == [("WEBRTC VoiceEngine", "Discord"), ("", "")]
    new_name, new_alias = page.edits[1]
    assert new_name.property("problem") is True
    assert page.problem.text() == "'': the name of the application is missing"

    menu_button = [button for button in page.findChildren(QToolButton) if button.menu()][1]
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()
    menu.actions()[0].trigger()
    type_into(qtbot, new_alias, "Browser")
    assert window.document.aliases[1] == ("Brave", "Browser")

    remove = [button for button in page.findChildren(QToolButton) if button.toolTip() == "Remove the alias"]
    click(qtbot, remove[0])
    assert window.document.aliases == [("Brave", "Browser")]


# -- the service and the file -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("properties", "pill", "tone", "button", "command"),
    [
        (MISSING, "not installed", "warn", "Install and start", ["systemctl", "--user", "daemon-reload"]),
        (STOPPED, "stopped", "neutral", "Start", ["systemctl", "--user", "enable", "--now", UNIT_NAME]),
        (RUNNING, "running", "good", "Restart", ["systemctl", "--user", "restart", UNIT_NAME]),
    ],
)
def test_the_service_is_shown_and_controlled(
    qtbot: QtBot,
    make_window: MakeWindow,
    systemctl: FakeSystemctl,
    monkeypatch: pytest.MonkeyPatch,
    properties: str,
    pill: str,
    tone: str,
    button: str,
    command: list[str],
    isolated: Dialogs,
):
    monkeypatch.setattr(window_module, "executable", lambda: "/opt/xtouch-daemon")
    systemctl.properties = properties
    window = make_window()
    assert (window.pill.text(), window.pill.property("tone"), window.service_button.text()) == (pill, tone, button)
    isolated.answer = QMessageBox.StandardButton.Yes

    click(qtbot, window.service_button)

    assert command in systemctl.commands
    assert window.status.text().endswith("the service.")
    # installing and starting ask first, a restart of the running service doesn't
    assert len(isolated.shown) == (0 if properties == RUNNING else 1)


@pytest.mark.parametrize("properties", [MISSING, STOPPED])
def test_a_service_is_installed_or_started_only_when_confirmed(
    qtbot: QtBot, make_window: MakeWindow, systemctl: FakeSystemctl, isolated: Dialogs, tmp_path: Path, properties: str
):
    systemctl.properties = properties
    window = make_window()
    shows = len(systemctl.commands)

    isolated.answer = QMessageBox.StandardButton.No
    click(qtbot, window.service_button)

    assert systemctl.commands[shows:] == []
    assert not (tmp_path / "systemd").exists()
    assert window.status.text() == ""


def test_a_new_window_starts_with_the_keys_on_the_strips(window: MainWindow):
    assert window.focusWidget() is window.preview.strips[0]


def test_keys_typed_into_a_new_window_do_not_press_the_service_button(window: MainWindow):
    assert window.service_button.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_a_failing_systemctl_is_reported(qtbot: QtBot, make_window: MakeWindow, systemctl, isolated: Dialogs):
    window = make_window()

    def fail(command: list[str]) -> str:
        raise ServiceError("systemctl --user restart failed: nope")

    window.service._run = fail
    click(qtbot, window.service_button)
    assert isolated.shown == ["systemctl --user restart failed: nope"]
    assert window.pill.text() == "unavailable"
    assert window.service_button.isHidden()


def test_a_changed_device_offers_a_restart(qtbot: QtBot, window: MainWindow, systemctl: FakeSystemctl):
    window.document.set(("device", "name"), "Other")
    window.refresh()

    assert window.save()
    assert not window.restart_button.isHidden()

    click(qtbot, window.restart_button)
    assert systemctl.commands[-2] == ["systemctl", "--user", "restart", UNIT_NAME]
    assert window.status.text() == "Restarted the service."


def test_a_changed_mqtt_section_offers_a_restart_instead_of_a_reload(window: MainWindow, daemon: RecordingInstance):
    window.document.add_section("mqtt")
    window.document.set(("mqtt", "host"), "broker")
    window.refresh()

    assert window.save()

    assert daemon.reloads == []
    assert window.status.text() == "Saved. The [mqtt] section changed: restart the service to use the configuration."
    assert not window.restart_button.isHidden()


def test_a_failing_restart_or_reload_is_reported(
    qtbot: QtBot, window: MainWindow, systemctl: FakeSystemctl, isolated: Dialogs
):
    window.document.set(("device", "name"), "Other")
    window.refresh()
    window.save()

    def fail(command: list[str]) -> str:
        if command[2] == "show":
            return RUNNING
        raise ServiceError(f"{command[2]} failed")

    window.service._run = fail
    click(qtbot, window.restart_button)
    assert isolated.shown == ["restart failed"]

    # it ended a moment ago
    window.daemon = RecordingInstance(1234, window.document.path.resolve(), systemd=True, gone=True)
    window.document.set(("device", "name"), "Third")
    window.refresh()
    assert window.save()
    assert window.status.text() == "Saved, but reloading the service failed: [Errno 3] No such process"


def test_a_daemon_started_elsewhere_is_shown_and_reloaded(qtbot: QtBot, make_window: MakeWindow, path: Path):
    daemon = RecordingInstance(4242, path.resolve(), systemd=False)
    window = make_window(find_daemon=lambda: daemon)

    assert (window.pill.text(), window.pill.property("tone")) == ("running elsewhere", "good")
    assert "process 4242" in window.pill.toolTip()
    assert window.service_button.isHidden()

    window.document.set(("device", "name"), "Other")
    window.refresh()
    assert window.save()

    assert daemon.reloads == [4242]
    assert window.status.text().endswith("restart the daemon (process 4242) for that to take effect.")
    # the window restarts only the service
    assert window.restart_button.isHidden()


def test_without_a_daemon_saving_only_saves(make_window: MakeWindow, systemctl: FakeSystemctl):
    systemctl.properties = STOPPED
    window = make_window(find_daemon=lambda: None)
    window.document.set(("device", "name"), "Other")
    window.refresh()

    assert window.save()

    assert window.status.text() == "Saved. The daemon is not running: start it to use the configuration."
    assert window.restart_button.isHidden()


def test_saving_what_did_not_change_does_nothing(window: MainWindow, path: Path):
    before = path.stat().st_mtime_ns
    assert window.save()
    assert path.stat().st_mtime_ns == before


def test_a_file_that_can_not_be_written_is_reported(window: MainWindow, path: Path, isolated: Dialogs):
    window.document.set(("behavior", "max_volume"), 110)
    window.refresh()
    path.chmod(0o400)
    try:
        assert not window.save()
    finally:
        path.chmod(0o600)
    assert isolated.shown[0].startswith("[Errno 13] Permission denied")


def test_a_new_file_can_be_saved_right_away(make_window: MakeWindow, tmp_path: Path):
    window = make_window(file=tmp_path / "new.toml")

    assert window.path_label.text().endswith("new file")
    assert window.save_button.isEnabled()
    assert window.save()
    assert tomllib.loads((tmp_path / "new.toml").read_text())["strip"][0] == {"type": "auto", "color": "cyan"}
    assert window.status.text().startswith("Saved. The service reads")


def test_revert_drops_the_changes(qtbot: QtBot, window: MainWindow):
    window.document.remove_strip(0)
    window.refresh()

    click(qtbot, window.revert_button)

    assert len(window.document.strips) == 2
    assert window.status.text() == "Reverted to the file. Ctrl+Z brings the changes back."


@pytest.mark.parametrize(
    ("answer", "closed", "saved"),
    [
        (QMessageBox.StandardButton.Discard, True, False),
        (QMessageBox.StandardButton.Save, True, True),
        (QMessageBox.StandardButton.Cancel, False, False),
    ],
)
def test_closing_asks_about_unsaved_changes(
    window: MainWindow, path: Path, isolated: Dialogs, answer: QMessageBox.StandardButton, closed: bool, saved: bool
):
    window.document.set(("behavior", "max_volume"), 110)
    window.refresh()
    isolated.answer = answer

    assert window.close() == closed
    assert isolated.shown == ["Save the changes before closing?"]
    assert ("max_volume = 110" in path.read_text()) == saved
    isolated.answer = QMessageBox.StandardButton.Discard


def test_closing_without_changes_does_not_ask(window: MainWindow, isolated: Dialogs):
    assert window.close()
    assert isolated.shown == []


def test_the_theme_switches_and_is_remembered(qtbot: QtBot, window: MainWindow):
    click(qtbot, window.theme_button)
    assert theme.current_mode() == theme.ThemeMode.LIGHT
    assert theme.load_theme_mode() == theme.ThemeMode.LIGHT

    click(qtbot, window.theme_button)
    assert theme.load_theme_mode() == theme.ThemeMode.DARK
    QSettings().setValue("theme", "purple")
    assert theme.load_theme_mode() == theme.ThemeMode.DARK


def test_run_gui_shows_the_window(path: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication):
    shown: list[MainWindow] = []
    monkeypatch.setattr(qt, "QApplication", lambda args: qapp)
    monkeypatch.setattr(MainWindow, "show", lambda window: shown.append(window))
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    handlers: dict[int, Callable[..., object]] = {}
    monkeypatch.setattr(qt.signal, "signal", lambda signum, handler: handlers.update({signum: handler}))
    closed: list[bool] = []
    monkeypatch.setattr(qapp, "closeAllWindows", lambda: closed.append(True))

    assert qt.run_gui(path) == 0
    assert shown[0].document.path == path
    assert QCoreApplication.applicationName() == "xtouch-daemon-gui"
    # Ctrl+C closes the window like its close button
    handlers[signal.SIGINT](signal.SIGINT, None)
    assert closed == [True]
    shown[0].deleteLater()


def test_a_homeassistant_strip_has_its_id_as_placeholder(window: MainWindow):
    window.document.add_section("mqtt")
    window.document.set_strip_type(1, "homeassistant")
    window.select(1)

    assert row(window, "id").line.placeholderText() == "strip_2"
    assert window.preview.strips[1].look.detail.startswith("entities of Home Assistant (strip_<position>)")


def test_a_homeassistant_strip_leads_to_its_connection(qtbot: QtBot, window: MainWindow):
    window.document.set_strip_type(1, "homeassistant")
    window.select(1)
    (setup,) = buttons(window.strip_page, QPushButton, lambda button: button.text() == "Set up the connection")

    click(qtbot, setup)
    assert window.current_page == "mqtt"
    # no strip is selected while the global settings show
    assert not any(view.selected for view in window.preview.strips)

    window.document.add_section("mqtt")
    window.document.set(("mqtt", "host"), "broker")
    window.select(1)
    (settings,) = buttons(window.strip_page, QPushButton, lambda button: button.text() == "Connection settings")
    assert [label for label in window.strip_page.findChildren(QLabel) if "MQTT broker broker" in label.text()]
    click(qtbot, settings)
    assert window.current_page == "mqtt"


def test_global_settings_are_apart_from_the_strips(qtbot: QtBot, window: MainWindow):
    assert window.tabs.tabText(0) == "Strip 1 · Speaker"
    assert window.tabs.tabText(1) == "Global settings"
    assert [button.text() for button in window.nav_buttons.values()] == [
        "Behavior",
        "Aliases",
        "Home Assistant",
        "Device",
    ]

    click(qtbot, window.nav_buttons["device"])
    assert window.current_page == "device"
    # the page stays when the pages are built again
    window.reload_pages()
    assert window.current_page == "device"
    window.tabs.setCurrentIndex(0)
    assert window.current_page == "strip"
    assert window.preview.strips[0].selected


def test_faders_are_picked_with_buttons(qtbot: QtBot, window: MainWindow):
    click(qtbot, window.nav_buttons["device"])
    faders = row(window, "touchless_faders", "device").numbers
    assert list(faders.buttons) == list(range(1, 9))
    assert faders.values == []

    click(qtbot, faders.buttons[3])
    click(qtbot, faders.buttons[1])
    assert window.document.get(("device", "touchless_faders")) == [1, 3]
    click(qtbot, faders.buttons[1])
    click(qtbot, faders.buttons[3])
    # none: the option goes away
    assert window.document.get(("device", "touchless_faders")) is None

    # a value of another type shows none
    window.document.set(("device", "touchless_faders"), "1")
    window.reload_pages()
    assert row(window, "touchless_faders", "device").numbers.values == []


def test_help_shows_quotes_and_code_as_they_are_meant(window: MainWindow):
    # the help of the label has quotes but no tag, which Qt would show as plain text, entities and all
    (help_label,) = [
        widget for widget in row(window, "label").findChildren(QLabel) if "start of the device" in widget.text()
    ]
    assert help_label.textFormat() == Qt.TextFormat.RichText
    document = QTextDocument()
    document.setHtml(help_label.text())
    assert '"Output"' in document.toPlainText()
    assert "&quot;" not in document.toPlainText()


def test_profiles_are_lines_of_label_and_profile(qtbot: QtBot, window: MainWindow):
    profiles = row(window, "profiles")
    tables: Tables = profiles.tables
    assert tables.values == []

    click(qtbot, tables.add_button)
    type_into(qtbot, tables.lines[0][0], "Analog")
    # the profiles of the card come from the sound server
    menu_button = next(button for button in tables.findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()
    assert [action.text() for action in menu.actions()] == [
        "output:analog-stereo    Analog Stereo Output (active)",
        "output:iec958-stereo    Digital Output",
    ]
    menu.actions()[0].trigger()
    assert tables.lines[0][1].text() == "output:analog-stereo"

    # one profile is not enough, and a label is required
    click(qtbot, tables.add_button)
    assert profiles.error.text() == "2. label: Field required\n2. profile: Field required"
    type_into(qtbot, tables.lines[1][0], "Digital")
    completer = tables.lines[1][1].completer()
    assert completer is not None
    completer.activated.emit("output:iec958-stereo")
    assert profiles.error.text() == ""

    assert window.document.get(("strip", 0, "profiles")) == [
        {"label": "Analog", "profile": "output:analog-stereo"},
        {"label": "Digital", "profile": "output:iec958-stereo"},
    ]
    type_into(qtbot, tables.lines[1][0], "")
    assert window.document.get(("strip", 0, "profiles"))[1] == {"profile": "output:iec958-stereo"}  # type: ignore[index]

    tables.remove(1)
    assert profiles.error.text() == "at least two to switch between"
    tables.remove(0)
    assert window.document.get(("strip", 0, "profiles")) is None
    assert profiles.error.text() == ""


def test_profiles_of_the_file_are_shown_and_saved_as_tables(qtbot: QtBot, window: MainWindow):
    window.document.set(
        ("strip", 0, "profiles"),
        [{"label": "Analog", "profile": "output:analog-stereo"}, {"label": "Digital", "profile": "Digital Output"}],
    )
    profiles = row(window, "profiles")
    profiles.load()
    assert [[line.text() for line in lines] for lines in profiles.tables.lines] == [
        ["Analog", "output:analog-stereo", "", ""],
        ["Digital", "Digital Output", "", ""],
    ]
    assert 'label = "Digital"' in window.document.render()
    # something else than a list of tables shows none: its problem says what is wrong
    window.document.set(("strip", 0, "profiles"), "analog")
    profiles.load()
    assert profiles.tables.values == []


def test_tables_without_suggestions_have_no_menu(qtbot: QtBot):
    columns = row_options("output", "profiles").columns
    tables = Tables(columns, None)
    qtbot.addWidget(tables)
    tables.show_values([{"label": "Analog"}])
    assert [[line.text() for line in lines] for lines in tables.lines] == [["Analog", "", "", ""]]
    assert not [button for button in tables.findChildren(QToolButton) if button.menu()]


def test_an_unset_number_says_what_applies(qtbot: QtBot, window: MainWindow):
    window.document.set(("behavior", "max_volume"), 120)
    maximum = row(window, "max_volume")
    maximum.load()
    assert maximum.spin.value() == -1
    assert maximum.spin.text() == "default: 120 (behavior)"

    maximum.spin.setValue(180)
    assert window.document.get(("strip", 0, "max_volume")) == 180
    # back below the range: not set
    maximum.spin.setValue(-1)
    assert window.document.get(("strip", 0, "max_volume")) is None
    assert row(window, "min_volume").spin.text() == "default: 0"


def test_numbers_of_tables_are_numbers(qtbot: QtBot, window: MainWindow):
    tables: Tables = row(window, "profiles").tables
    click(qtbot, tables.add_button)
    type_into(qtbot, tables.lines[0][3], "200")
    assert window.document.get(("strip", 0, "profiles")) == [{"max_volume": 200}]
    # one that is none stays text: its problem says so
    type_into(qtbot, tables.lines[0][3], "lots")
    assert window.document.get(("strip", 0, "profiles")) == [{"max_volume": "lots"}]


def test_a_switch_looks_different_on_and_off(qtbot: QtBot):
    switch = Switch()
    qtbot.addWidget(switch)
    switch.resize(switch.sizeHint())
    off = switch.grab().toImage()
    switch.setChecked(True)
    assert switch.grab().toImage() != off


# -- Home Assistant ---------------------------------------------------------------------------------------------


def test_the_connection_to_home_assistant_shows_while_the_daemon_uses_it(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    window.document.add_section("mqtt")
    window.document.set(("mqtt", "host"), "broker")
    window.reload_pages()
    window.save()
    window.show_page("mqtt")
    page = window.mqtt_page
    assert page.box is not None
    # the daemon runs without [mqtt]: it reads it when it starts
    live_daemon.send(snapshot(window, strip_state()))
    qtbot.waitUntil(lambda: page.box is not None and page.box.live_pill.text() == "not in use")
    assert window.mqtt_pill.isHidden()

    refused = MqttState("broker:1883", None, False, False, "[code:5] Connection refused: Not authorised", 4)
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), mqtt=False, mqtt_state=refused))
    qtbot.waitUntil(lambda: window.mqtt_pill.text() == "Home Assistant · not authorized")
    assert not window.mqtt_pill.isHidden()
    assert "check <code>username</code>" in page.box.live_detail.text()

    # the pill leads to the settings
    window.show_page("behavior")
    qtbot.mouseClick(window.mqtt_pill, Qt.MouseButton.LeftButton)
    assert window.current_page == "mqtt"

    connected = dataclasses.replace(refused, connected=True, ready=True, error=None)
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), mqtt=True, mqtt_state=connected))
    qtbot.waitUntil(lambda: window.mqtt_pill.text() == "Home Assistant")
    assert page.box.live_pill.text() == "connected"


def test_the_settings_of_home_assistant_can_be_tried_before_they_are_saved(qtbot: QtBot, make_window: MakeWindow):
    tried: list[MqttConfig] = []

    async def works(config: MqttConfig) -> Status:
        tried.append(config)
        return Status(f"Connected to {config.host}:{config.port}: these settings work.", Tone.GOOD)

    window = make_window(test_broker=works)
    page = window.mqtt_page
    # nothing to try without the section
    assert page.box is None
    window.show_page("mqtt")
    window.document.add_section("mqtt")
    window.reload_pages()
    box = page.box
    assert box is not None
    assert box.live_pill.text() == "unknown"

    # the settings miss the host
    click(qtbot, box.test_button)
    assert box.test_result.text() == "Fix the problems of the settings first."
    assert tried == []

    window.document.set(("mqtt", "host"), "broker")
    click(qtbot, box.test_button)
    qtbot.waitUntil(lambda: box.test_result.text() == "Connected to broker:1883: these settings work.")
    assert box.test_button.isEnabled()
    assert box.test_hint.isHidden()
    # unsaved: the editor's settings, not the file's
    assert window.document.modified
    assert [config.host for config in tried] == ["broker"]

    # the result stays when the page is built again
    window.reload_pages()
    assert page.box is not None
    assert page.box.test_result.text() == "Connected to broker:1883: these settings work."


def test_a_failed_test_says_what_to_check(qtbot: QtBot, window: MainWindow):
    window.show_page("mqtt")
    window.document.add_section("mqtt")
    window.document.set(("mqtt", "host"), "broker")
    window.reload_pages()
    box = window.mqtt_page.box
    assert box is not None
    click(qtbot, box.test_button)
    qtbot.waitUntil(lambda: "Connection refused" in box.test_result.text())
    assert box.test_hint.text() == "Is it running?"
    assert not box.test_hint.isHidden()

    # a result that comes after the section was removed has nowhere to go
    window.document.remove_section("mqtt")
    window.reload_pages()
    window.mqtt_page.tester.finished.emit(Status("late", Tone.GOOD))
    assert window.mqtt_page.box is None
