"""
The live view: the running daemon tells what the device shows right now (the LCDs, LEDs, rings, faders and meters),
so the GUI can show the strips as they are instead of what a file would make of them.

The daemon serves a Unix socket next to its runtime file (see `instance.socket_file()`). Every client gets the whole
state as one line of JSON when it connects, and again whenever something changed, at most every `INTERVAL`. Whole
states rather than changes: a line is about 2 KB, and a client that missed one (or connects late) needs nothing else
to be right. A client that does not keep up is dropped instead of being waited for, so a stuck GUI never slows down
the daemon.

A client of the same user may also send requests, a line of JSON each: the live preview of the GUI (`StartPreview`,
`KeepPreview`, `EndPreview`) and the switch to another layout (`SwitchLayout`). The daemon answers with `Reply` lines,
which have no `version`: a GUI that does not know replies ignores them like lines of another version, and an older
daemon ignores the requests.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import socket
import struct
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

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
MAX_REQUEST = 1024 * 1024
"""
The longest line a client may send; a configuration has a few KB. A longer one ends the connection: the daemon reads
nothing without a limit.
"""
FEATURES = ("preview", "layout")
"""The requests this daemon takes. An older daemon tells none, so the GUI knows that it can't preview."""
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
class VoipState:
    """Where the participants of `voip` strips come from (`[voip]`)."""

    provider: str
    """`bridge` or `demo`."""
    connected: bool
    """Whether the provider knows the voice chat now; for `bridge`: a plugin is connected."""
    client: str | None
    """What the plugin calls its voice chat client, e.g. "mumble"."""
    channel: str | None
    """The channel of the user, if the plugin tells it."""
    participants: int


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
    daemon_version: str | None = None
    """The version of the daemon that runs (an older daemon does not tell it)."""
    preview: bool = False
    """
    Whether the daemon runs a configuration that a GUI previews (`StartPreview`) instead of its file; `config` is the
    fingerprint of that one then.
    """
    features: tuple[str, ...] = ()
    """The requests the daemon takes (`FEATURES`), none for an older daemon."""
    layout: str | None = None
    """The name of the layout the device shows (an older daemon does not tell it)."""
    layouts: tuple[str, ...] = ()
    """The names of every layout of the configuration, the default one first."""
    voip: VoipState | None = None
    """The voice chat, None without `[voip]` (or for an older daemon)."""


@dataclass(frozen=True)
class StartPreview:
    """
    Run this configuration (the whole TOML text) instead of the file, without writing the file. The daemon answers
    with a `Reply` of kind "preview"; sent again, the device follows. The preview ends with `EndPreview`, with the
    connection, without a request for `daemon.PREVIEW_TIMEOUT` (see `KeepPreview`), and when the file is loaded again.
    """

    config: str


@dataclass(frozen=True)
class KeepPreview:
    """The heartbeat of a preview: the client is still there (a hung GUI keeps its connection open, but sends none)."""


@dataclass(frozen=True)
class EndPreview:
    """Back to the configuration file."""


@dataclass(frozen=True)
class SwitchLayout:
    """
    Show another layout: `layout` is its name, or "+1" ("-1") for the next (previous) one. The daemon answers with a
    `Reply` of kind "layout".
    """

    layout: str


type Request = StartPreview | KeepPreview | EndPreview | SwitchLayout

type ReplyKind = Literal["preview", "ended", "layout", "error"]


@dataclass(frozen=True)
class Reply:
    """
    An answer of the daemon, or news for a client. "preview": whether a `StartPreview` runs now (`message` says why
    not, e.g. the errors of the configuration, as `check-config` tells them). "ended": the preview of this client
    ended, `message` says why. "layout": whether a `SwitchLayout` was carried out (`message` is the layout shown
    then, or why not). "error": a request could not be read, or is not allowed.
    """

    kind: ReplyKind
    ok: bool
    message: str = ""


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
                text=strip.shown_text,
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
    """
    A snapshot of the daemon, None for a line of another version or a reply. Raises ValueError (or KeyError) for a
    line that is neither.
    """
    message = decode_message(line)
    return message if isinstance(message, Snapshot) else None


def decode_message(line: bytes) -> Snapshot | Reply | None:
    """A line of the daemon: a snapshot or a reply, None for a snapshot of another version."""
    data = json.loads(line)
    if "reply" in data:
        return Reply(data["reply"], bool(data["ok"]), str(data.get("message", "")))
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
        data.get("daemon_version"),
        bool(data.get("preview", False)),
        tuple(data.get("features", ())),
        data.get("layout"),
        tuple(data.get("layouts", ())),
        VoipState(**voip) if (voip := data.get("voip")) is not None else None,
    )


def encode_reply(reply: Reply) -> bytes:
    return json.dumps({"reply": reply.kind, "ok": reply.ok, "message": reply.message}).encode() + b"\n"


_REQUEST_NAMES: dict[type, str] = {
    StartPreview: "preview",
    KeepPreview: "keep_preview",
    EndPreview: "end_preview",
    SwitchLayout: "layout",
}


def encode_request(request: Request) -> bytes:
    data = {"request": _REQUEST_NAMES[type(request)]}
    if isinstance(request, StartPreview):
        data["config"] = request.config
    elif isinstance(request, SwitchLayout):
        data["layout"] = request.layout
    return json.dumps(data).encode() + b"\n"


def decode_request(line: bytes) -> Request:
    """A request of a client. Raises ValueError for a line that is none."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"not JSON ({e})") from e
    match data:
        case {"request": "preview", "config": str(config)}:
            return StartPreview(config)
        case {"request": "keep_preview"}:
            return KeepPreview()
        case {"request": "end_preview"}:
            return EndPreview()
        case {"request": "layout", "layout": str(layout)}:
            return SwitchLayout(layout)
        case _:
            raise ValueError("unknown")


def peer_uid(sock: socket.socket) -> int:
    """The user of the process at the other end of a Unix socket, as the kernel tells it (SO_PEERCRED)."""
    credentials = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", credentials)
    return uid


type RequestHandler = Callable[[object, Request], Reply | None]
"""Handles a request of a client (the object stands for it, see `LiveServer.tell()`), returns the answer if any."""


class LiveServer:
    """
    Serves the snapshots of `snapshot` on the Unix socket at `path`, for as long as `run()` runs. `on_request` handles
    the requests of clients of the user the daemon runs as (without it, requests are refused), `on_close` learns of
    every client whose connection ended.
    """

    def __init__(
        self,
        path: Path,
        snapshot: Callable[[], Snapshot],
        on_request: RequestHandler | None = None,
        on_close: Callable[[object], None] = lambda client: None,
    ):
        self.path = path
        self._snapshot = snapshot
        self._on_request = on_request
        self._on_close = on_close
        self.clients: set[asyncio.StreamWriter] = set()
        self._last = b""

    async def run(self) -> None:
        """Serves until cancelled. A socket that can't be made is logged: the daemon works without the live view."""
        try:
            # the user's own: $XDG_RUNTIME_DIR is, and so is the fallback directory (see `instance.runtime_file()`)
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            # left behind by a daemon that was killed; registering the instance made sure that none runs
            self.path.unlink(missing_ok=True)
            server = await asyncio.start_unix_server(self._serve, self.path, limit=MAX_REQUEST)
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

    def tell(self, client: object, reply: Reply) -> None:
        """Sends a reply the client did not ask for, e.g. that its preview ended. Nothing for one that is gone."""
        if client in self.clients:
            assert isinstance(client, asyncio.StreamWriter)
            self._send(client, encode_reply(reply))

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
        # the socket is 0600, but root can connect anyway
        trusted = peer_uid(writer.get_extra_info("socket")) == os.getuid()
        try:
            # until it closes the connection
            with contextlib.suppress(ConnectionError):
                while line := await reader.readline():
                    self._request(writer, line, trusted)
        except ValueError:
            # longer than MAX_REQUEST: where the next request starts is lost
            _LOGGER.warning(f"Dropping a live view client that sent more than {MAX_REQUEST} bytes in one line")
            self._send(writer, encode_reply(Reply("error", False, f"A request has at most {MAX_REQUEST} bytes")))
        finally:
            self.clients.discard(writer)
            self._on_close(writer)
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    def _request(self, client: asyncio.StreamWriter, line: bytes, trusted: bool) -> None:
        if not trusted or self._on_request is None:
            reply: Reply | None = Reply("error", False, "The daemon takes requests only from the user it runs as")
        else:
            try:
                request = decode_request(line)
            except ValueError as e:
                reply = Reply("error", False, f"Can't read the request: {e}")
            else:
                reply = self._on_request(client, request)
        if reply is not None:
            self._send(client, encode_reply(reply))
