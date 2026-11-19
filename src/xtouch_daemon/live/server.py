"""
The socket of the live view in the daemon: it sends the snapshots of the device to every client, takes the requests
of the clients of the same user, and sends the log to those that watch it.
"""

import asyncio
import contextlib
import dataclasses
import logging
import os
import socket
import struct
from collections.abc import Callable
from pathlib import Path

from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.live.codec import decode_request, encode, encode_known, encode_log, encode_reply, encode_twin
from xtouch_daemon.live.log import LogBuffer
from xtouch_daemon.live.messages import (
    DaemonRequest,
    EndLog,
    Glide,
    KnownDevices,
    LogLines,
    LogRequest,
    Reply,
    Snapshot,
    StripState,
    TwinView,
    VoipState,
    WatchLog,
)
from xtouch_daemon.live.messages import steady as steady_strips
from xtouch_daemon.voip.provider import VoipProvider

_LOGGER = logging.getLogger(__name__)


MAX_BUFFER = 768 * 1024
"""Bytes a client may lag behind (about 300 states, 5 s) before it is dropped."""
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
        position, mode, center = strip.ring
        top, bottom = mirror.text(index)
        # the strips of the test while it has the device
        motion = surface.front[index].glide
        glide: Glide | None = None
        if motion is not None and strip.known:
            # from where the daemon has it, which the motor follows: the GUI draws the rest of the way
            at, velocity, target, slow = motion
            fader: float | None = at / protocol.FADER_MAX
            glide = Glide(now, velocity / protocol.FADER_MAX, target / protocol.FADER_MAX, slow)
        elif strip.known:
            # where the motor goes: it gets there in a moment, without anything else to tell
            fader = round((strip.target if strip.moving and not strip.touched else strip.fader) / protocol.FADER_MAX, 4)
        else:
            fader = None
        states.append(
            StripState(
                color=_color_name(strip.color),
                text=(top.rstrip(), bottom.rstrip()),
                leds={button.name.lower(): _led_name(strip.leds[button]) for button in Button},
                ring=position,
                ring_mode=mode.name.lower(),
                fader=fader,
                # the surface's touch: on a fader without a working sensor a move is one
                touched=surface.front[index].touched,
                meter=strip.meter,
                # a dark meter has nothing to fall from: when it was set again does not matter
                meter_at=strip.meter_at if strip.meter else None,
                glide=glide,
                ring_center=center,
            )
        )
    return tuple(states)


def voip_state(provider: VoipProvider) -> VoipState:
    """The voice chat, for the live view."""
    return VoipState(
        provider=provider.name,
        connected=provider.connected,
        client=provider.client,
        channel=provider.channel,
        participants=len(provider.participants),
        names=tuple(participant.name for participant in provider.participants),
        ids=tuple(participant.id for participant in provider.participants),
    )


def _led_name(led: Led) -> str:
    return led.name.lower()


def peer_uid(sock: socket.socket) -> int:
    """The user of the process at the other end of a Unix socket, as the kernel tells it (SO_PEERCRED)."""
    credentials = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", credentials)
    return uid


type RequestHandler = Callable[[object, DaemonRequest], Reply | None]
"""Handles a request of a client (the object stands for it, see `LiveServer.tell()`), returns the answer if any."""


class LiveServer:
    """
    Serves the snapshots of `snapshot` on the Unix socket at `path`, for as long as `run()` runs: a new one whenever
    something changed (see `changed()`), not on a timer. What moves by itself (a meter that falls, a fader that
    glides) is told once, and the GUI draws it moving (see `StripState`). `on_request` handles
    the requests of clients of the user the daemon runs as (without it, requests are refused), `on_close` learns of
    every client whose connection ended. `log` has the records a client gets with `WatchLog` (without it, the request
    is refused).
    """

    def __init__(
        self,
        path: Path,
        snapshot: Callable[[], Snapshot],
        on_request: RequestHandler | None = None,
        on_close: Callable[[object], None] = lambda client: None,
        known: Callable[[], KnownDevices] = lambda: KnownDevices(()),
        log: LogBuffer | None = None,
    ):
        self.path = path
        self._snapshot = snapshot
        self._on_request = on_request
        self._on_close = on_close
        self._known = known
        self.clients: set[asyncio.StreamWriter] = set()
        self._last: Snapshot | None = None
        """What the clients were sent last, `steady()`: a snapshot that tells nothing else is not sent."""
        self._due = False
        """Whether a snapshot goes out once the event loop is through with what it does now."""
        self._log = log
        self._watchers: dict[asyncio.StreamWriter, int] = {}
        """The clients that watch the log, with the `seq` of the latest record each was sent."""
        self._log_due = False
        """Whether new records go out once the event loop gets to it."""
        self._loop: asyncio.AbstractEventLoop | None = None

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
            await asyncio.Event().wait()
        finally:
            server.close()
            for client in list(self.clients):
                client.close()
            self.clients.clear()
            self._watchers.clear()
            self._unwatched()
            self.path.unlink(missing_ok=True)

    def tell(self, client: object, reply: Reply) -> None:
        """Sends a reply the client did not ask for, e.g. that its preview ended. Nothing for one that is gone."""
        if client in self.clients:
            assert isinstance(client, asyncio.StreamWriter)
            self._send(client, encode_reply(reply))

    def tell_view(self, client: object, view: TwinView) -> None:
        """Sends the view of the twin of `client` to it alone. Nothing for one that is gone."""
        if client in self.clients:
            assert isinstance(client, asyncio.StreamWriter)
            self._send(client, encode_twin(view))

    def publish_known(self) -> None:
        """The devices the daemon remembers changed: every client gets them."""
        line = encode_known(self._known())
        for client in list(self.clients):
            self._send(client, line)

    def changed(self) -> None:
        """
        Something the snapshot tells may have changed: the clients get the new one once the event loop is through
        with what it does now, so that what changes together goes out together. As often as things change, no less.
        """
        if not self.clients or self._due:
            return
        self._due = True
        asyncio.get_running_loop().call_soon(self._publish)

    def _publish(self) -> None:
        self._due = False
        if not self.clients:
            return
        snapshot = self._snapshot()
        steady = dataclasses.replace(snapshot, strips=steady_strips(snapshot.strips))
        if steady == self._last:
            return
        self._last = steady
        line = encode(snapshot)
        for client in list(self.clients):
            self._send(client, line)

    def _send(self, client: asyncio.StreamWriter, line: bytes) -> None:
        if client.transport.get_write_buffer_size() > MAX_BUFFER:
            # it does not read: dropped rather than waited for (it can connect again)
            self.clients.discard(client)
            self._unwatch(client)
            client.close()
            _LOGGER.warning("Dropping a live view client that does not keep up")
            return
        client.write(line)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.clients.add(writer)
        # the whole state right away, not only once something changes
        self._send(writer, encode(self._snapshot()))
        if (known := self._known()).devices:
            self._send(writer, encode_known(known))
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
            self._unwatch(writer)
            self._on_close(writer)
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    def _request(self, client: asyncio.StreamWriter, line: bytes, trusted: bool) -> None:
        refused = Reply("error", False, "The daemon takes requests only from the user it runs as")
        if not trusted:
            reply: Reply | None = refused
        else:
            try:
                request = decode_request(line)
            except ValueError as e:
                reply = Reply("error", False, f"Can't read the request: {e}")
            else:
                if isinstance(request, WatchLog | EndLog):
                    reply = self._log_request(client, request)
                elif self._on_request is None:
                    reply = refused
                else:
                    reply = self._on_request(client, request)
        if reply is not None:
            self._send(client, encode_reply(reply))

    # -- the log ------------------------------------------------------------------------------------------------------

    def _log_request(self, client: asyncio.StreamWriter, request: LogRequest) -> Reply | None:
        if isinstance(request, EndLog):
            self._unwatch(client)
            return None
        if self._log is None:
            return Reply("error", False, "The daemon keeps no log")
        # what it kept, then every new record
        entries = self._log.since(0)
        self._watchers[client] = entries[-1].seq if entries else self._log.last
        self._send(client, encode_log(LogLines(entries, backlog=True)))
        self._loop = asyncio.get_running_loop()
        self._log.on_entry = self._logged
        return None

    def _logged(self) -> None:
        """A new record (in the thread that logged it): the watchers get it once the event loop gets to it."""
        if self._log_due:
            return
        self._log_due = True
        assert self._loop is not None, "set with the first watcher"
        self._loop.call_soon_threadsafe(self._publish_log)

    def _publish_log(self) -> None:
        self._log_due = False
        assert self._log is not None
        for client, seq in list(self._watchers.items()):
            entries = self._log.since(seq)
            if entries:
                self._watchers[client] = entries[-1].seq
                self._send(client, encode_log(LogLines(entries)))

    def _unwatch(self, client: asyncio.StreamWriter) -> None:
        self._watchers.pop(client, None)
        if not self._watchers:
            self._unwatched()

    def _unwatched(self) -> None:
        """Nobody watches the log: a record costs nothing more than its place in the buffer."""
        if self._log is not None:
            self._log.on_entry = None
