"""
The screenshots of the documentation (`just screenshot`): the GUI with a demo configuration and a device that shows
it, rendered offscreen. Nothing of the machine is used: no daemon, device, sound server or settings of the user.

    uv run --extra gui python scripts/screenshot.py [OUT_DIR]
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
SCALE = 2
"""Device pixels per pixel: sharp on screens with a high density, and on GitHub."""
SIZE = (1100, 1000)
SELECTED = 2

CONFIG = """\
[behavior]
auto_hold = 5

[[strip]]
type = "output"
device = "alsa_output.pci-0000_11_00.4.*"
color = "cyan"
profiles = [
  { label = "Phones", profile = "output:analog-stereo+input:analog-stereo" },
  { label = "Speaker", profile = "output:iec958-stereo+input:analog-stereo", max_volume = 200 },
]

[[strip]]
type = "output"
device = ["bluez_output.*"]
label = "Buds"
color = "green"

[[strip]]
type = "apps"
match = ["@browsers"]
label = "Browser"
color = "blue"
meter = true

[[strip]]
type = "apps"
match = ["@games"]
label = "Games"
color = "red"

[[strip]]
type = "apps"
match = ["@voip"]
label = "VoIP"
color = "yellow"
lit_when_idle = true

[[strip]]
type = "auto"
color = "white"

[[strip]]
type = "input"
device = "alsa_input.pci-0000_11_00.4.analog-stereo"
label = "Mic"
color = "magenta"

[[strip]]
type = "homeassistant"
id = "living_room"
label = "Light"
color = "yellow"

[mqtt]
host = "homeassistant.local"
username = "xtouch"
"""


def main(out: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="xts-") as directory:
        home = Path(directory)
        # nothing of the user: settings, configuration and runtime directory in the temporary one
        os.environ["XDG_CONFIG_HOME"] = str(home / "config")
        os.environ["XDG_RUNTIME_DIR"] = str(home / "runtime")
        os.environ["XDG_STATE_HOME"] = str(home / "state")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_SCALE_FACTOR"] = str(SCALE)
        (home / "runtime").mkdir()
        shoot(home, out)


def shoot(home: Path, out: Path) -> None:
    # after the environment: Qt reads it when it starts
    from PyQt6.QtCore import QCoreApplication, QSettings
    from PyQt6.QtNetwork import QLocalServer
    from PyQt6.QtWidgets import QApplication

    from xtouch_daemon.audio.model import AudioState, Card, Device, Direction, Profile, Stream
    from xtouch_daemon.gui.domain.document import ConfigDocument
    from xtouch_daemon.gui.qt import theme
    from xtouch_daemon.gui.qt.window import MainWindow
    from xtouch_daemon.instance import Instance
    from xtouch_daemon.live.codec import encode
    from xtouch_daemon.live.messages import MqttState, Snapshot, StripState, fingerprint
    from xtouch_daemon.systemd import Service

    QCoreApplication.setOrganizationName("xtouch-daemon-screenshot")
    QCoreApplication.setApplicationName("xtouch-daemon-screenshot")
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(home / "settings"))
    app = QApplication(sys.argv[:1])
    theme.apply_theme(theme.ThemeMode.DARK)

    path = home / "config" / "xtouch-daemon" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(CONFIG)

    card = "alsa_card.pci-0000_11_00.4"
    audio = AudioState(
        outputs=(
            Device("alsa_output.pci-0000_11_00.4.analog-stereo", "Headphones", Direction.OUTPUT, 46, False, True, card),
            Device("bluez_output.4C_D7_3A_EA_02_76.1", "Buds", Direction.OUTPUT, 44, False, False, None, 0.0),
        ),
        inputs=(Device("alsa_input.pci-0000_11_00.4.analog-stereo", "Mic", Direction.INPUT, 80, False, True, card),),
        streams=(
            Stream(1, "Brave", "brave", 60, False, False, 0.0),
            Stream(2, "Spotify", "spotify", 72, False, False, 0.0),
        ),
        cards=(
            Card(
                card,
                "output:analog-stereo+input:analog-stereo",
                (
                    Profile("output:analog-stereo+input:analog-stereo", "Analog Stereo Duplex"),
                    Profile("output:iec958-stereo+input:analog-stereo", "Digital Stereo (IEC958) Output"),
                ),
            ),
        ),
        default_output="alsa_output.pci-0000_11_00.4.analog-stereo",
        default_input="alsa_input.pci-0000_11_00.4.analog-stereo",
    )

    def strip(
        color: str,
        text: tuple[str, str],
        fader: float,
        meter: int = 0,
        ring: int = 6,
        ring_mode: str = "boost_cut",
        **leds: str,
    ) -> StripState:
        return StripState(
            color=color,
            text=text,
            leds={"rec": "off", "solo": "off", "mute": "off", "select": "off"} | leds,
            ring=ring,
            ring_mode=ring_mode,
            fader=fader,
            touched=False,
            meter=meter,
        )

    strips = (
        strip("cyan", ("Phones", "46%"), 0.35, meter=7, rec="on"),
        strip("green", ("Buds", "44%"), 0.34),
        strip("blue", ("Browser", "60%"), 0.46, meter=10, select="on"),
        strip("off", ("Games", "idle"), 0.0, ring=0),
        strip("yellow", ("VoIP", "idle"), 0.0, ring=0),
        strip("white", ("Spotify", "72%"), 0.55, meter=9),
        strip("magenta", ("Mic", "80%"), 0.62, meter=5, rec="on"),
        strip("yellow", ("Light", "65%"), 0.65, ring=8, ring_mode="spread"),
    )

    document = ConfigDocument.open(path)
    saved = document.saved_config
    assert saved is not None
    mqtt = MqttState("homeassistant.local:1883", "xtouch", connected=True, ready=True, error=None, entities=6)
    snapshot = Snapshot(fingerprint(saved), True, sound_server=True, mqtt=True, strips=strips, mqtt_state=mqtt)

    socket = home / "runtime" / "live.sock"
    server = QLocalServer()
    assert server.listen(str(socket)), server.errorString()

    def connected() -> None:
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            assert client is not None
            client.write(encode(snapshot))
            client.flush()

    server.newConnection.connect(connected)

    def systemctl(command: list[str]) -> str:
        if command[2] == "show":
            return "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
        return ""

    daemon = Instance(os.getpid(), path.resolve(), systemd=True)
    window = MainWindow(document, Service(systemctl), lambda: audio, lambda: daemon, socket)
    window.resize(*SIZE)
    window.show()
    wait(app, lambda: window.live.snapshot is not None and window.audio_label.text() != "Reading the sound server…")
    window.select(SELECTED)
    settle(app)
    # the file as it is on a machine of a user, not in the temporary directory
    window.path_label.setText(window.path_label.text().replace(str(path), "~/.config/xtouch-daemon/config.toml"))

    out.mkdir(parents=True, exist_ok=True)
    save(window.grab(), out / "gui.png")
    save(window.preview.grab(), out / "device.png")
    window.close()
    server.close()


def wait(app: object, ready: object, timeout: float = 10.0) -> None:
    import time

    from PyQt6.QtWidgets import QApplication

    assert isinstance(app, QApplication)
    end = time.monotonic() + timeout
    while not ready():  # type: ignore[operator]
        if time.monotonic() > end:
            raise TimeoutError("the window did not get the live view and the sound server")
        app.processEvents()
        time.sleep(0.01)


def settle(app: object, seconds: float = 0.5) -> None:
    """Lets the faders glide and the layout settle."""
    import time

    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QApplication

    assert isinstance(app, QApplication)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        # outside of `exec()` Qt deletes no widgets by itself: the pages replaced by a selection would stay visible
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.01)


def save(picture: object, path: Path) -> None:
    from PyQt6.QtGui import QPixmap

    assert isinstance(picture, QPixmap)
    assert picture.save(str(path), "PNG", 0), path  # 0: the smallest file
    print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {picture.width()}x{picture.height()}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
