"""
Helpers for the tests of the window: the configuration and sound server they start with, a fake live view, and
the fakes that keep the window away from the machine (no plugin, broker or Home Assistant is reached).
"""

import dataclasses
from math import cos, radians, sin
from pathlib import Path

from PyQt6.QtCore import QPointF
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from tests.support.audio import output, source, stream
from xtouch_daemon.audio.model import AudioState, Card, Profile
from xtouch_daemon.config.sections import HomeAssistantConfig, MqttConfig
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.domain.voip import CLIENTS, NO_PLUGIN
from xtouch_daemon.gui.quick.device.geometry import ENCODER, RING_RADII, ring_angle
from xtouch_daemon.gui.quick.pages.settings_support import PluginInstaller
from xtouch_daemon.homeassistant.client import Fetched, HomeAssistantError
from xtouch_daemon.live.codec import decode_request, encode, encode_log, encode_twin
from xtouch_daemon.live.messages import LogLines, Request, Snapshot, StripState, TwinView
from xtouch_daemon.voip import mumble

CONFIG = """\
# my mixer
[behavior]
max_volume = 120

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[channel.out]
type = "output"
device = "speaker"
label = "Speaker"
color = "cyan"

[channel.browser]
type = "apps"
match = ["brave"]
label = "Browser"

[state.call]
voice_chat = true

[slots]
1 = "out"
2 = ["browser if call", "auto"]
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


def no_install() -> str:
    raise mumble.MumbleError("Mumble is not installed")


def no_plugins() -> list[PluginInstaller]:
    """Nothing of this machine: neither a plugin nor a voice chat client."""
    return [PluginInstaller(client, no_install, lambda: NO_PLUGIN) for client in CLIENTS]


async def unreachable_broker(config: MqttConfig) -> Status:
    """No test of the MQTT settings reaches out to a real broker."""
    return Status(f"Can't connect to {config.host}:{config.port}: Connection refused.", Tone.BAD, "Is it running?")


async def unreachable_home_assistant(config: HomeAssistantConfig) -> Fetched:
    """No window reaches out to a real Home Assistant."""
    raise HomeAssistantError(f"can't connect to {config.websocket_url}: Connection refused")


class FakeLiveDaemon:
    """The live view of a daemon: a local server that sends the lines the test gives it."""

    def __init__(self, path: Path):
        self.server = QLocalServer()
        assert self.server.listen(str(path)), self.server.errorString()
        self.clients: list[QLocalSocket] = []
        self.requests: list[Request] = []
        """What the window asked for, in order."""
        self.server.newConnection.connect(self._connected)

    @property
    def path(self) -> Path:
        return Path(self.server.fullServerName())

    def _connected(self) -> None:
        while self.server.hasPendingConnections():
            client = self.server.nextPendingConnection()
            assert client is not None
            self.clients.append(client)
            client.readyRead.connect(lambda client=client: self._read(client))

    def _read(self, client: QLocalSocket) -> None:
        while client.canReadLine():
            self.requests.append(decode_request(bytes(client.readLine().data())))

    def send_line(self, line: bytes) -> None:
        for client in self.clients:
            client.write(line)
            client.flush()

    def send(self, snapshot: Snapshot) -> None:
        self.send_line(encode(snapshot))

    def send_twin(self, view: TwinView) -> None:
        self.send_line(encode_twin(view))

    def send_log(self, lines: LogLines) -> None:
        self.send_line(encode_log(lines))

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


def led_point(led: int) -> QPointF:
    """The middle of the LED `led` of the ring (0..12) of a strip, in its logical units."""
    angle = radians(ring_angle(led))
    return ENCODER + QPointF(cos(angle), -sin(angle)) * sum(RING_RADII) / 2
