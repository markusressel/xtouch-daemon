"""
The socket of the live view in the daemon: it sends the snapshots of the device to every client and takes the
requests of the clients of the same user.
"""

import asyncio
import contextlib
import logging
import os
import socket
import struct
from collections.abc import Callable
from pathlib import Path

from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.live.codec import decode_request, encode, encode_reply
from xtouch_daemon.live.messages import Reply, Request, Snapshot, StripState

_LOGGER = logging.getLogger(__name__)


INTERVAL = 0.05
"""How often the state is checked for changes: 20 times a second, enough for a fader that glides."""
MAX_BUFFER = 256 * 1024
"""Bytes a client may lag behind (about 100 states) before it is dropped."""
MAX_REQUEST = 1024 * 1024
"""
The longest line a client may send; a configuration has a few KB. A longer one ends the connection: the daemon reads
nothing without a limit.
"""


def _color_name(color: Color) -> str:
    return "off" if color == Color.BLACK else color.name.lower()


def strip_states(surface: Surface, now: float) -> tuple[StripState, ...]:
    """What the strips of the device show at `now` (`time.monotonic()`): the surface's mirror of it."""
    mirror = surface.mirror
    mirror.advance(now)
    states: list[StripState] = []
    for index, strip in enumerate(mirror.strips):
        position, mode, _ = strip.ring
        top, bottom = mirror.text(index)
        states.append(
            StripState(
                color=_color_name(strip.color),
                text=(top.rstrip(), bottom.rstrip()),
                leds={button.name.lower(): _led_name(strip.leds[button]) for button in Button},
                ring=position,
                ring_mode=mode.name.lower(),
                fader=round(strip.fader / protocol.FADER_MAX, 4) if strip.known else None,
                # the surface's touch: on a fader without a working sensor a move is one
                touched=surface.strips[index].touched,
                meter=mirror.meter(index),
            )
        )
    return tuple(states)


def _led_name(led: Led) -> str:
    return led.name.lower()


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
