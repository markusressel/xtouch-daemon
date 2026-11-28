"""
The screenshots of the documentation (`just screenshot`): the GUI with a demo configuration and a device that shows
it, and small pictures of a strip and of its parts (`controls/`), rendered offscreen. Nothing of the machine is used:
no daemon, device, sound server or settings of the user.

    uv run --extra gui python scripts/screenshot.py [OUT_DIR]
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QImage

    from xtouch_daemon.live.messages import StripState

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
SCALE = 2
"""Device pixels per pixel: sharp on screens with a high density, and on GitHub."""
SIZE = (1100, 1000)
SELECTED = 2

CONFIG = """\
[channel.out]
type = "output"
device = "alsa_output.pci-0000_11_00.4.*"
color = "cyan"
profiles = [
  { label = "Phones", profile = "output:analog-stereo+input:analog-stereo" },
  { label = "Speaker", profile = "output:iec958-stereo+input:analog-stereo", max_volume = 200 },
]

[channel.buds]
type = "output"
device = ["bluez_output.*"]
label = "Buds"
color = "green"

[channel.browser]
type = "apps"
match = ["@browsers"]
label = "Browser"
color = "blue"
meter = true

[channel.games]
type = "apps"
match = ["@games"]
label = "Games"
color = "red"

[channel.voip]
type = "apps"
match = ["@voip"]
label = "VoIP"
color = "yellow"
lit_when_idle = true

[channel.mic]
type = "input"
device = "alsa_input.pci-0000_11_00.4.analog-stereo"
label = "Mic"
color = "magenta"

[channel.light]
type = "homeassistant"
label = "Light"
color = "yellow"

[state.gaming]
mode = true
processes = ["@steam-games"]

[slots]
1 = "out"
2 = "buds"
3 = "browser"
4 = ["games if gaming", "auto"]
5 = "voip"
6 = "auto"
7 = "mic"
8 = "light"

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

    from xtouch_daemon.audio.model import DISCONNECTED, AudioState, Card, Device, Direction, Profile, Stream
    from xtouch_daemon.gui.domain.slots_document import SlotsDocument
    from xtouch_daemon.gui.domain.tokens import Motion, ThemeMode
    from xtouch_daemon.gui.quick.app import App, Dependencies, close_window, load_window
    from xtouch_daemon.gui.quick.device.geometry import PANEL
    from xtouch_daemon.gui.quick.engine import make_engine
    from xtouch_daemon.gui.quick.theme import Theme
    from xtouch_daemon.live.codec import encode
    from xtouch_daemon.live.messages import (
        FEATURES,
        MqttState,
        SlotsState,
        SlotView,
        Snapshot,
        StateView,
        fingerprint,
    )
    from xtouch_daemon.slots.outcomes import simulate
    from xtouch_daemon.system.instance import Instance
    from xtouch_daemon.system.systemd import Service

    QCoreApplication.setOrganizationName("xtouch-daemon-screenshot")
    QCoreApplication.setApplicationName("xtouch-daemon-screenshot")
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(home / "settings"))
    qapp = QApplication(sys.argv[:1])
    # every change at once: a picture shows the end of it, not a fade
    Motion.enabled = False

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

    document = SlotsDocument.open(path)
    saved = document.saved_config
    assert saved is not None
    mqtt = MqttState("homeassistant.local:1883", "xtouch", connected=True, ready=True, error=None, entities=6)
    # gaming is on (strip 4 shows the games, none of which plays), as the rules found it; Spotify plays on `auto`
    resolved = simulate(saved.slots.scene, "gaming", (), (), apps=1)
    views = tuple(
        SlotView(
            slot,
            shown.candidate,
            shown.channel,
            shown.pool,
            "app:Spotify" if shown.member is not None else None,
            resolved.why[slot],
        )
        for slot, shown in resolved.slots.items()
    )
    gaming = StateView("gaming", True, True, None, "a Steam game runs", "auto")
    slots = SlotsState(mode="gaming", mode_pick=None, slots=views, states=(gaming,), waiting={})
    snapshot = Snapshot(
        fingerprint(saved),
        True,
        sound_server=True,
        mqtt=True,
        strips=strips,
        mqtt_state=mqtt,
        features=FEATURES,
        slots=slots,
    )

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
    app = App(Dependencies(document, Service(systemctl), lambda: audio, lambda: daemon, live_socket=socket))
    engine = make_engine(Theme(ThemeMode.DARK))
    window = load_window(app, engine)
    window.resize(*SIZE)
    window.show()
    shell = app.shell
    wait(qapp, lambda: shell.live.snapshot is not None and shell.audio is not DISCONNECTED)
    slots: Any = app.slots
    slots.selectSlot(SELECTED + 1)
    settle(qapp)
    # the path of the file (in the temporary directory) is in the title of the window, which a grab doesn't show

    out.mkdir(parents=True, exist_ok=True)
    whole = window.grabWindow()
    save_image(whole, out / "gui.png")
    from PyQt6.QtCore import QRectF

    stage = find(window, "drawingStage")
    device: Any = app.device
    drawing = device.drawing
    save_image(
        crop_of(
            whole,
            window,
            stage,
            QRectF(
                drawing.origin.x() - 3,
                drawing.origin.y() - 3,
                PANEL.width() * drawing.scale + 6,
                PANEL.height() * drawing.scale + 6,
            ),
        ),
        out / "device.png",
    )
    close_window(engine, app)
    server.close()
    shoot_controls(out / "controls")


def strip(
    color: str,
    text: tuple[str, str],
    fader: float,
    meter: int = 0,
    ring: int = 6,
    ring_mode: str = "boost_cut",
    **leds: str,
) -> StripState:
    from xtouch_daemon.live.messages import StripState

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


def shoot_controls(out: Path) -> None:
    """
    Small pictures of a strip and of its parts for the documentation, drawn as the window Device draws them: on a
    transparent background, with rounded corners, at 2 device pixels per pixel of `CONTROL_SCALE`.
    """
    import dataclasses

    from PyQt6.QtCore import QRectF

    from xtouch_daemon.gui.quick.device.geometry import (
        BUTTON_TOP,
        BUTTON_X,
        BUTTONS_BOTTOM,
        ENCODER,
        HEIGHT,
        LCD,
        METER,
        RING_RADII,
        SELECT_SIZE,
        UNITY,
        WIDTH,
        button_rect,
    )

    out.mkdir(parents=True, exist_ok=True)
    ring = RING_RADII[1] + 5
    # the top of the ring, without the number of the strip printed above it
    encoder = QRectF(ENCODER.x() - ring, ENCODER.y() - ring + 1, 2 * ring, 2 * ring - 1)
    lcd = LCD.adjusted(-4, -4, 4, 4)
    browser = strip("blue", ("Browser", "60%"), 0.6, meter=10, ring=7, ring_mode="wrap", select="on")
    lit = strip("blue", ("Browser", "60%"), 0.6, rec="on", solo="on", mute="on", select="on")
    pictures: list[tuple[str, StripState, QRectF, float]] = [
        ("strip", browser, QRectF(0, 0, WIDTH, HEIGHT), 1.0),
        ("encoder", browser, encoder, CONTROL_SCALE),
        ("lcd", browser, lcd, CONTROL_SCALE),
        ("meter", browser, QRectF(METER.left() - 5, METER.top() - 5, METER.width() + 36, METER.height() + 10), 1.5),
        (
            "buttons",
            lit,
            QRectF(BUTTON_X - 25, BUTTON_TOP - 6, 50, BUTTONS_BOTTOM - BUTTON_TOP + 6),
            1.5,
        ),
        ("fader", strip("blue", ("", ""), UNITY), QRectF(4, BUTTONS_BOTTOM, WIDTH - 8, HEIGHT - 4 - BUTTONS_BOTTOM), 1),
    ]
    for row, name in enumerate(("rec", "solo", "mute", "select")):
        top = button_rect(row).top()
        width = SELECT_SIZE.width() + 20
        # only this one lit: the glow of the next one would show at the bottom
        alone = dataclasses.replace(lit, leds={button: "on" if button == name else "off" for button in lit.leds})
        pictures.append((name, alone, QRectF(BUTTON_X - width / 2, top - 1, width, 35), CONTROL_SCALE))
    # the color alone: another backlight than the blue of the LCD above
    pictures.append(("color", strip("magenta", ("color", ""), 0.0), lcd, CONTROL_SCALE))
    for name, state, crop, scale in pictures:
        save_image(render_part(state, crop, scale), out / f"{name}.png")
    # the colors of the backlight, each on an LCD with its name
    colors = ("white", "red", "yellow", "green", "cyan", "blue", "magenta", "off")
    save_image(
        side_by_side([render_part(strip(color, (color, ""), 0.0), lcd, CONTROL_SCALE) for color in colors]),
        out / "colors.png",
    )


CONTROL_SCALE = 2.0
"""The pixels of the documentation per logical unit of a strip, for the pictures of single parts."""


def render_part(state: StripState, crop: QRectF, scale: float) -> QImage:
    """The strip showing `state`, cut to `crop` (in logical units of a strip), with rounded corners."""
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import QImage, QPainter, QPainterPath

    from xtouch_daemon.gui.domain.looks import StripFace, StripLook
    from xtouch_daemon.gui.quick.device.render import render_strip

    ratio = 2
    look = StripLook("preview", state.text[0], "", state.color, printed=" ")
    whole = render_strip(StripFace(look, state, live=True, dimmed=False), scale, ratio)
    pixels = ratio * scale
    cut = whole.copy(
        round(crop.left() * pixels),
        round(crop.top() * pixels),
        round(crop.width() * pixels),
        round(crop.height() * pixels),
    )
    cut.setDevicePixelRatio(ratio)
    width, height = cut.width() / ratio, cut.height() / ratio
    rounded = QImage(cut.size(), QImage.Format.Format_ARGB32_Premultiplied)
    rounded.setDevicePixelRatio(ratio)
    rounded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), 8, 8)
    painter.setClipPath(path)
    painter.drawImage(QPointF(), cut)
    painter.end()
    return rounded


def find(window: object, name: str) -> object:
    """The item of the window named `name`."""
    from PyQt6.QtQuick import QQuickItem, QQuickWindow

    assert isinstance(window, QQuickWindow)
    stack: list[QQuickItem] = [window.contentItem()]  # pyright: ignore[reportAssignmentType]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    raise LookupError(name)


def crop_of(whole: QImage, window: object, item: object, rect: QRectF) -> QImage:
    """The part `rect` (in the coordinates of `item`) of a picture of the window, without what is around it."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtQuick import QQuickItem, QQuickWindow

    assert isinstance(item, QQuickItem)
    assert isinstance(window, QQuickWindow)
    ratio = window.devicePixelRatio()
    top_left = item.mapToScene(QPointF(rect.x(), rect.y()))
    cut = whole.copy(
        round(top_left.x() * ratio),
        round(top_left.y() * ratio),
        round(rect.width() * ratio),
        round(rect.height() * ratio),
    )
    cut.setDevicePixelRatio(ratio)
    return cut


def side_by_side(parts: list[QImage], gap: int = 8) -> QImage:
    """Pictures of the same height next to each other, `gap` pixels apart, on a transparent background."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QImage, QPainter

    ratio = parts[0].devicePixelRatio()
    width = sum(part.width() for part in parts) + round(gap * ratio) * (len(parts) - 1)
    joined = QImage(width, parts[0].height(), QImage.Format.Format_ARGB32_Premultiplied)
    joined.setDevicePixelRatio(ratio)
    joined.fill(Qt.GlobalColor.transparent)
    painter = QPainter(joined)
    x = 0.0
    for part in parts:
        painter.drawImage(QPointF(x, 0), part)
        x += part.width() / ratio + gap
    painter.end()
    return joined


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


def save_image(image: QImage, path: Path) -> None:
    assert image.save(str(path), "PNG", 0), path
    print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {image.width()}x{image.height()}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
