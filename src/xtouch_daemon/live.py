"""
The live view: the running daemon tells what the device shows right now (the LCDs, LEDs, rings, faders and meters),
so the GUI can show the strips as they are instead of what a file would make of them.

The daemon serves a Unix socket next to its runtime file (see `instance.socket_file()`). Every client gets the whole
state as one line of JSON when it connects, and again whenever something changed, at most every `INTERVAL`. Whole
states rather than changes: a line is about 2 KB, and a client that missed one (or connects late) needs nothing else
to be right. Clients only read; what they send is ignored. A client that does not keep up is dropped instead of being
waited for, so a stuck GUI never slows down the daemon.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from xtouch_daemon import protocol
from xtouch_daemon.config import Config
from xtouch_daemon.protocol import Button, Color, Led
from xtouch_daemon.surface import Surface

_LOGGER = logging.getLogger(__name__)

VERSION = 1
"""Changes when a line means something else; a client ignores lines of another version."""
INTERVAL = 0.05
"""How often the state is checked for changes: 20 times a second, enough for a fader that glides."""
MAX_BUFFER = 256 * 1024
"""Bytes a client may lag behind (about 100 states) before it is dropped."""
METER_FALL = 0.15
"""
Seconds per level in which a meter falls when it is not sent again, about as fast as on the device (which lets it fall
by itself, see `Strip.set_meter()`).
"""


@dataclass(frozen=True)
class StripState:
    """What one strip shows."""

    color: str
    """The backlight of the LCD, a color name of the configuration ("off" for dark)."""
    text: tuple[str, str]
    """The two lines of the LCD."""
    leds: dict[str, str]
    """The LED of each button ("rec", "solo", "mute", "select"): "off", "on" or "flash"."""
    ring: int
    """The position of the LED ring, 0 (off) to `protocol.RING_MAX`."""
    ring_mode: str
    """How the ring shows the position, a `RingMode` in lower case: "dot", "boost_cut", "wrap" or "spread"."""
    fader: float | None
    """Where the fader is (0..1), None while that is not known."""
    touched: bool
    """Whether a finger is on the fader."""
    meter: int
    """The level of the meter, 0..`protocol.METER_MAX`."""


@dataclass(frozen=True)
class MqttState:
    """The connection to the MQTT broker of Home Assistant."""

    broker: str
    """`host:port`."""
    username: str | None
    connected: bool
    ready: bool
    """Connected, and the states Home Assistant keeps for the entities are in."""
    error: str | None
    """Why the last attempt to connect failed or the connection ended (the broker's words), None while connected."""
    entities: int
    """The entities of the configuration in Home Assistant."""


@dataclass(frozen=True)
class Snapshot:
    """The state of the daemon and of everything the device shows."""

    config: str
    """The `fingerprint()` of the configuration the daemon uses."""
    device: bool
    """Whether the device is connected. The strips show what it would show (and does once it is back)."""
    sound_server: bool
    mqtt: bool | None
    """Whether the MQTT broker is connected; None without an [mqtt] section."""
    strips: tuple[StripState, ...]
    mqtt_state: MqttState | None = None
    """More on the connection of `mqtt` (an older daemon does not tell it)."""


def fingerprint(config: Config) -> str:
    """
    A short hash of everything in a configuration, so the GUI can tell whether the daemon uses the saved file (a
    reload keeps the old configuration when the new one can't be used).
    """

    def plain(value: Any) -> Any:
        return value.get_secret_value() if isinstance(value, SecretStr) else str(value)

    data = json.dumps(config.model_dump(), default=plain, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _color_name(color: Color) -> str:
    return "off" if color == Color.BLACK else color.name.lower()


def strip_states(surface: Surface, now: float) -> tuple[StripState, ...]:
    """What the strips of the surface show at `now` (`time.monotonic()`)."""
    states: list[StripState] = []
    for strip in surface.strips:
        position, mode = strip.ring
        level, at = strip.meter
        fader = strip.position if strip.position is not None else strip.fader
        states.append(
            StripState(
                color=_color_name(strip.color),
                text=(strip.text[0], strip.text[1]),
                leds={button.name.lower(): _led_name(strip.leds[button]) for button in Button},
                ring=position,
                ring_mode=mode.name.lower(),
                fader=None if fader is None else round(fader / protocol.FADER_MAX, 4),
                touched=strip.touched,
                meter=max(0, level - int((now - at) / METER_FALL)),
            )
        )
    return tuple(states)


def _led_name(led: Led) -> str:
    return led.name.lower()


def encode(snapshot: Snapshot) -> bytes:
    return json.dumps({"version": VERSION, **asdict(snapshot)}, separators=(",", ":")).encode() + b"\n"


def decode(line: bytes) -> Snapshot | None:
    """A line of the daemon, None for one of another version. Raises ValueError (or KeyError) for one that is not."""
    data = json.loads(line)
    if data.get("version") != VERSION:
        return None
    strips = tuple(
        StripState(
            color=strip["color"],
            text=(strip["text"][0], strip["text"][1]),
            leds=dict(strip["leds"]),
            ring=strip["ring"],
            ring_mode=strip["ring_mode"],
            fader=strip["fader"],
            touched=strip["touched"],
            meter=strip["meter"],
        )
        for strip in data["strips"]
    )
    mqtt_state = data.get("mqtt_state")
    return Snapshot(
        data["config"],
        data["device"],
        data["sound_server"],
        data["mqtt"],
        strips,
        MqttState(**mqtt_state) if mqtt_state is not None else None,
    )


class LiveServer:
    """Serves the snapshots of `snapshot` on the Unix socket at `path`, for as long as `run()` runs."""

    def __init__(self, path: Path, snapshot: Callable[[], Snapshot]):
        self.path = path
        self._snapshot = snapshot
        self.clients: set[asyncio.StreamWriter] = set()
        self._last = b""

    async def run(self) -> None:
        """Serves until cancelled. A socket that can't be made is logged: the daemon works without the live view."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # left behind by a daemon that was killed; registering the instance made sure that none runs
            self.path.unlink(missing_ok=True)
            server = await asyncio.start_unix_server(self._serve, self.path)
            self.path.chmod(0o600)
        except OSError as e:
            _LOGGER.error(f"No live view for the GUI, can't serve {self.path}: {e}")
            return
        try:
            while True:
                await asyncio.sleep(INTERVAL)
                if self.clients:
                    self._publish(encode(self._snapshot()))
        finally:
            server.close()
            for client in list(self.clients):
                client.close()
            self.clients.clear()
            self.path.unlink(missing_ok=True)

    def _publish(self, line: bytes) -> None:
        if line == self._last:
            return
        self._last = line
        for client in list(self.clients):
            self._send(client, line)

    def _send(self, client: asyncio.StreamWriter, line: bytes) -> None:
        if client.transport.get_write_buffer_size() > MAX_BUFFER:
            # it does not read: dropped rather than waited for (it can connect again)
            _LOGGER.warning("Dropping a live view client that does not keep up")
            self.clients.discard(client)
            client.close()
            return
        client.write(line)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.clients.add(writer)
        # the whole state right away, not only once something changes
        self._send(writer, encode(self._snapshot()))
        try:
            # until it closes the connection; what it sends means nothing
            with contextlib.suppress(ConnectionError):
                while await reader.read(4096):
                    pass
        finally:
            self.clients.discard(writer)
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()
