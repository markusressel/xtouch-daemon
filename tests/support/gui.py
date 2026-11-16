"""
Helpers for the tests of the window: the configuration and sound server they start with, the dialogs they answer,
a fake live view, and clicking and typing.
"""

import dataclasses
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QAbstractButton,
    QLineEdit,
    QMessageBox,
    QWidget,
)
from pytestqt.qtbot import QtBot

from tests.support.audio import output, source, stream
from xtouch_daemon.audio.model import AudioState, Card, Profile
from xtouch_daemon.config.sections import MqttConfig
from xtouch_daemon.gui.domain.schema import Option, strip_options
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.codec import encode
from xtouch_daemon.live.messages import Snapshot, StripState, fingerprint
from xtouch_daemon.voip import mumble

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
        self.pick: str | None = None
        """The button a message box of its own (`exec()`) gets clicked by its text; None for its Cancel."""

    def question(self, parent: object, title: str, text: str, *args: object) -> QMessageBox.StandardButton:
        self.shown.append(text)
        return self.answer

    def message(self, parent: object, title: str, text: str) -> QMessageBox.StandardButton:
        self.shown.append(text)
        return QMessageBox.StandardButton.Ok

    def execute(self, box: QMessageBox) -> int:
        self.shown.append(box.text())
        if self.pick is None:
            button = box.button(QMessageBox.StandardButton.Cancel)
        else:
            (button,) = [button for button in box.buttons() if button.text() == self.pick]
        assert button is not None
        button.click()
        return 0


type MakeWindow = Callable[..., MainWindow]


NO_MUMBLE = mumble.Setup(bundle=None, buildable=False, installed=None, mumble=False)


def no_install() -> str:
    raise mumble.MumbleError("Mumble is not installed")


async def unreachable_broker(config: MqttConfig) -> Status:
    """No test of the MQTT settings reaches out to a real broker."""
    return Status(f"Can't connect to {config.host}:{config.port}: Connection refused.", Tone.BAD, "Is it running?")


def row_options(strip_type: str, name: str) -> Option:
    return next(option for option in strip_options(strip_type) if option.name == name)


def row(window: MainWindow, name: str, page: str = "strip") -> OptionRow:
    return next(option_row for option_row in window.pages[page].rows if option_row.option.name == name)


def shows(widget: QWidget, parent: QWidget) -> bool:
    """Whether `widget` shows when `parent` does (the stubs of `isVisibleTo` want a widget of the same class)."""
    return QWidget.isVisibleTo(widget, parent)


def buttons[T: QAbstractButton](parent: QWidget, kind: type[T], match: Callable[[T], bool]) -> list[T]:
    """The buttons on `parent` that `match`, of the parts of it that show (not e.g. the forms of other strip types)."""
    return [button for button in parent.findChildren(kind) if shows(button, parent) and match(button)]


def type_into(qtbot: QtBot, edit: QLineEdit, text: str) -> None:
    edit.selectAll()
    qtbot.keyClick(edit, Qt.Key.Key_Backspace)
    qtbot.keyClicks(edit, text)


def click(qtbot: QtBot, button: object) -> None:
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # pyright: ignore[reportArgumentType]


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
        self.send_line(encode(snapshot))

    def close(self) -> None:
        for client in self.clients:
            client.disconnectFromServer()
        self.clients = []
        self.server.close()


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
    return Snapshot(fingerprint(saved), device, sound_server=True, mqtt=None, strips=strips)


LAYOUT_CONFIG = (
    CONFIG
    + """
[voip]
provider = "demo"

[[layout]]
name = "gaming"
apps = ["steam_app_"]

[[layout.strip]]
type = "inherit"

[[layout.strip]]
type = "voip"

[[layout.strip]]
type = "voip"

[[layout]]
name = "music"
"""
)
