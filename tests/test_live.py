import asyncio
import dataclasses
import logging
import os
import socket
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from tests.support.hardware import RecordingSurface
from tests.support.tasks import finish_tasks
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import strip as strip_module
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.live import server as server_module
from xtouch_daemon.live.codec import decode, decode_message, decode_request, encode, encode_reply, encode_request
from xtouch_daemon.live.messages import (
    FEATURES,
    EndPreview,
    KeepPreview,
    MqttState,
    Reply,
    Request,
    Snapshot,
    StartPreview,
    StripState,
    SwitchLayout,
    VoipState,
    fingerprint,
)
from xtouch_daemon.live.server import INTERVAL, MAX_BUFFER, METER_FALL, LiveServer, peer_uid, strip_states


@pytest.fixture
def socket_dir() -> Iterator[Path]:
    """A directory with a short path: the path of a Unix socket has at most 107 bytes, which tmp_path may exceed."""
    with tempfile.TemporaryDirectory(prefix="xtl-") as path:
        yield Path(path)


@pytest.fixture(autouse=True)
async def no_tasks_left() -> AsyncIterator[None]:
    yield
    await finish_tasks()


def snapshot_of(surface: RecordingSurface, config: str = "abc") -> Snapshot:
    return Snapshot(config, device=True, sound_server=False, mqtt=None, strips=strip_states(surface, 0.0))


async def serve(server: LiveServer) -> asyncio.Task[None]:
    task = asyncio.create_task(server.run())
    for _ in range(100):
        if server.path.exists():
            # a moment without clients
            await asyncio.sleep(2 * INTERVAL)
            return task
        await asyncio.sleep(0.005)
    raise AssertionError("the server did not start")


def test_a_strip_is_described_as_the_device_shows_it(surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch):
    strip = surface.strips[2]
    strip.set_color(Color.CYAN)
    strip.set_text(0, "Speaker")
    strip.set_text(1, "46%")
    strip.set_led(Button.MUTE, Led.ON)
    strip.set_led(Button.SELECT, Led.FLASH)
    strip.set_ring(7, RingMode.WRAP)
    strip.fader = 8191
    monkeypatch.setattr(strip_module.time, "monotonic", lambda: 100.0)
    strip.set_meter(10)
    monkeypatch.undo()

    states = strip_states(surface, 100.0 + 2 * METER_FALL + 0.01)

    assert states[2] == StripState(
        color="cyan",
        text=("Speaker", "46%"),
        leds={"rec": "off", "solo": "off", "mute": "on", "select": "flash"},
        ring=7,
        ring_mode="wrap",
        fader=0.5,
        touched=False,
        meter=8,
    )
    # nothing known yet: dark, and no fader position
    assert states[0].color == "off"
    assert states[0].fader is None
    # the meter falls to 0, not below
    assert strip_states(surface, 1000.0)[2].meter == 0


async def test_the_fader_is_where_the_motor_put_it(surface: RecordingSurface):
    strip = surface.strips[0]
    strip.set_fader(1.0)
    strip.moved_by_hand(4095)

    assert strip_states(surface, 0.0)[0].fader == round(4095 / 16383, 4)


def test_a_snapshot_goes_through_a_line(surface: RecordingSurface):
    surface.strips[0].set_text(0, "Mic")
    snapshot = snapshot_of(surface)
    line = encode(snapshot)

    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
    assert decode(line) == snapshot
    assert decode(b'{"version": 0}') is None
    # with the connection to the broker
    state = MqttState("broker:1883", "me", connected=False, ready=False, error="Not authorized", entities=3)
    with_mqtt = Snapshot("abc", True, False, False, snapshot.strips, state)
    assert decode(encode(with_mqtt)) == with_mqtt
    # with its version
    versioned = Snapshot("abc", True, False, None, snapshot.strips, daemon_version="1.2.3")
    assert decode(encode(versioned)) == versioned
    # with strips that moved
    placed = Snapshot("abc", True, False, None, snapshot.strips, placement=(0, 2, 3, 4, 5, 6, 7, None))
    assert decode(encode(placed)) == placed
    # an older daemon does not tell more than whether it is connected, nor its version
    older = line.replace(b',"mqtt_state":null', b"").replace(b',"daemon_version":null', b"")
    assert b"mqtt_state" not in older
    assert b"daemon_version" not in older
    assert decode(older) == snapshot
    with pytest.raises(ValueError, match="Expecting value"):
        decode(b"garbage")


def test_the_fingerprint_tells_configurations_apart():
    speaker = parse_config('[[strip]]\ntype = "output"\nlabel = "Speaker"\n')
    secret = '[mqtt]\nhost = "broker"\npassword = "{}"\n'

    assert fingerprint(speaker) == fingerprint(parse_config('[[strip]]\ntype = "output"\nlabel = "Speaker"\n'))
    assert fingerprint(speaker) != fingerprint(parse_config('[[strip]]\ntype = "output"\nlabel = "Boxes"\n'))
    # also a changed password, which a dump shows as stars
    assert fingerprint(parse_config(secret.format("one"))) != fingerprint(parse_config(secret.format("two")))
    assert len(fingerprint(speaker)) == 16


async def test_a_client_gets_the_state_at_once_and_then_every_change(surface: RecordingSurface, socket_dir: Path):
    server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface))
    task = await serve(server)
    assert server.path.stat().st_mode & 0o777 == 0o600

    reader, writer = await asyncio.open_unix_connection(server.path)
    first = decode(await reader.readline())
    assert first is not None
    assert first.strips[0].text == ("", "")

    surface.strips[0].set_text(0, "Mic")
    second = decode(await asyncio.wait_for(reader.readline(), 1))
    assert second is not None
    assert second.strips[0].text == ("Mic", "")

    # nothing changed: nothing is sent
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(reader.readline(), 3 * INTERVAL)

    writer.write(b"ignored\n")
    writer.close()
    await writer.wait_closed()
    for _ in range(100):
        if not server.clients:
            break
        await asyncio.sleep(0.005)
    assert server.clients == set()

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not server.path.exists()


async def test_a_client_that_does_not_read_is_dropped(
    surface: RecordingSurface, socket_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface))
    task = await serve(server)
    reader, writer = await asyncio.open_unix_connection(server.path)
    await reader.readline()
    for _ in range(100):
        if server.clients:
            break
        await asyncio.sleep(0.005)
    (client,) = server.clients
    monkeypatch.setattr(client.transport, "get_write_buffer_size", lambda: MAX_BUFFER + 1)

    surface.strips[0].set_text(0, "Mic")
    # the server closes the connection instead of sending more
    assert await asyncio.wait_for(reader.read(), 1) == b""

    assert server.clients == set()
    assert "Dropping a live view client that does not keep up" in caplog.text
    writer.close()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_clients_are_closed_when_the_server_stops(surface: RecordingSurface, socket_dir: Path):
    server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface))
    task = await serve(server)
    reader, writer = await asyncio.open_unix_connection(server.path)
    await reader.readline()

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert await asyncio.wait_for(reader.read(), 1) == b""
    writer.close()


async def test_a_socket_left_behind_is_replaced(surface: RecordingSurface, socket_dir: Path):
    path = socket_dir / "live.sock"
    path.write_text("left behind")
    server = LiveServer(path, lambda: snapshot_of(surface))
    task = asyncio.create_task(server.run())
    for _ in range(100):
        if path.is_socket():
            break
        await asyncio.sleep(0.005)

    reader, writer = await asyncio.open_unix_connection(path)
    assert decode(await reader.readline()) is not None
    writer.close()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_without_a_socket_the_daemon_runs_on(
    surface: RecordingSurface, socket_dir: Path, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.ERROR)
    (socket_dir / "file").write_text("")
    server = LiveServer(socket_dir / "file" / "live.sock", lambda: snapshot_of(surface))

    await server.run()

    assert "No live view for the GUI, can't serve" in caplog.text


# -- requests -------------------------------------------------------------------------------------------------------


def test_requests_and_replies_go_through_a_line(surface: RecordingSurface):
    for request in (StartPreview('[[strip]]\ntype = "empty"\n'), KeepPreview(), EndPreview(), SwitchLayout("+1")):
        line = encode_request(request)
        assert line.count(b"\n") == 1
        assert decode_request(line) == request
    with pytest.raises(ValueError, match="not JSON"):
        decode_request(b"garbage")
    with pytest.raises(ValueError, match="unknown"):
        decode_request(b'{"request": "reboot"}')
    with pytest.raises(ValueError, match="unknown"):
        decode_request(b'{"request": "preview", "config": 1}')
    with pytest.raises(ValueError, match="unknown"):
        decode_request(b'{"request": "layout"}')

    reply = Reply("preview", False, "strip[1].type: wrong")
    assert decode_message(encode_reply(reply)) == reply
    # a GUI that knows no replies ignores them like lines of another version
    assert decode(encode_reply(reply)) is None
    assert b'"version"' not in encode_reply(reply)
    # the snapshot of a daemon that previews, and of one that does not know previews
    snapshot = dataclasses.replace(snapshot_of(surface), preview=True, features=FEATURES)
    assert decode_message(encode(snapshot)) == snapshot
    older = encode(snapshot_of(surface)).replace(b',"preview":false,"features":[]', b"")
    assert b"features" not in older
    decoded = decode(older)
    assert decoded is not None
    assert (decoded.preview, decoded.features) == (False, ())


class Requests:
    """What the daemon would do with the requests: recorded, and answered."""

    def __init__(self) -> None:
        self.received: list[tuple[object, Request]] = []
        self.closed: list[object] = []

    def handle(self, client: object, request: Request) -> Reply | None:
        self.received.append((client, request))
        return Reply("preview", True) if isinstance(request, StartPreview) else None


async def replies(reader: asyncio.StreamReader, count: int = 1) -> list[Reply]:
    """The next `count` replies, past the snapshots."""
    result: list[Reply] = []
    while len(result) < count:
        message = decode_message(await asyncio.wait_for(reader.readline(), 1))
        if isinstance(message, Reply):
            result.append(message)
    return result


async def until(condition: object) -> None:
    for _ in range(200):
        if callable(condition) and condition():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("the condition never became true")


async def test_requests_of_the_user_are_handled_and_answered(surface: RecordingSurface, socket_dir: Path):
    requests = Requests()
    server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface), requests.handle, requests.closed.append)
    task = await serve(server)
    reader, writer = await asyncio.open_unix_connection(server.path)

    writer.write(encode_request(StartPreview("text")) + encode_request(KeepPreview()) + b"nonsense\n")
    assert await replies(reader, 2) == [
        Reply("preview", True),
        Reply("error", False, "Can't read the request: not JSON (Expecting value: line 1 column 1 (char 0))"),
    ]
    (client,) = server.clients
    assert requests.received == [(client, StartPreview("text")), (client, KeepPreview())]

    # news it did not ask for
    server.tell(client, Reply("ended", True, "the GUI ended it"))
    assert await replies(reader) == [Reply("ended", True, "the GUI ended it")]

    writer.close()
    await writer.wait_closed()
    await until(lambda: requests.closed)
    assert requests.closed == [client]
    # it is gone: nothing to tell
    server.tell(client, Reply("ended", True, "late"))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_requests_of_other_users_are_refused(
    surface: RecordingSurface, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    requests = Requests()
    server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface), requests.handle)
    task = await serve(server)
    # e.g. root, who can connect to a socket of mode 0600
    monkeypatch.setattr(server_module, "peer_uid", lambda sock: os.getuid() + 1)
    reader, writer = await asyncio.open_unix_connection(server.path)
    # it still sees what the device shows
    assert decode(await reader.readline()) is not None

    writer.write(encode_request(StartPreview("text")))

    assert await replies(reader) == [Reply("error", False, "The daemon takes requests only from the user it runs as")]
    assert requests.received == []
    writer.close()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_without_a_handler_requests_are_refused(surface: RecordingSurface, socket_dir: Path):
    server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface))
    task = await serve(server)
    reader, writer = await asyncio.open_unix_connection(server.path)

    writer.write(encode_request(EndPreview()))

    assert (await replies(reader))[0].kind == "error"
    writer.close()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_a_request_that_is_too_long_ends_the_connection(
    surface: RecordingSurface, socket_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(server_module, "MAX_REQUEST", 1000)
    requests = Requests()
    server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface), requests.handle, requests.closed.append)
    task = await serve(server)
    reader, writer = await asyncio.open_unix_connection(server.path)

    writer.write(encode_request(StartPreview("x" * 2000)))

    assert await replies(reader) == [Reply("error", False, "A request has at most 1000 bytes")]
    assert await asyncio.wait_for(reader.read(), 1) == b""
    assert requests.received == []
    await until(lambda: requests.closed)
    assert "sent more than 1000 bytes in one line" in caplog.text
    writer.close()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_the_peer_is_the_user_itself():
    first, second = socket.socketpair(socket.AF_UNIX)
    with first, second:
        assert peer_uid(first) == os.getuid()


def test_the_layouts_go_through_a_line(surface: RecordingSurface):
    snapshot = Snapshot(
        "abc", True, True, None, strip_states(surface, 0.0), layout="gaming", layouts=("default", "gaming")
    )
    assert decode(encode(snapshot)) == snapshot
    # an older daemon does not tell them
    older = encode(snapshot).replace(b',"layout":"gaming","layouts":["default","gaming"]', b"")
    decoded = decode(older)
    assert decoded is not None
    assert (decoded.layout, decoded.layouts) == (None, ())


def test_the_live_view_shows_a_banner(surface: RecordingSurface):
    surface.strips[0].set_text(0, "Speaker")
    surface.strips[0].set_overlay(("Gaming", ""))
    assert strip_states(surface, 0.0)[0].text == ("Gaming", "")


def test_the_voice_chat_goes_through_a_line(surface: RecordingSurface):
    voip = VoipState("bridge", True, "mumble", "Lobby", 3, ("Ann", "Bob", "Carol"), ("Bob", None, "Ann"))
    snapshot = dataclasses.replace(snapshot_of(surface), voip=voip)
    assert decode(encode(snapshot)) == snapshot
    # without who is where
    plain = dataclasses.replace(voip, names=(), strips=())
    line = encode(dataclasses.replace(snapshot, voip=plain)).replace(b',"names":[],"strips":[]', b"")
    assert b"names" not in line
    decoded = decode(line)
    assert decoded is not None
    assert decoded.voip == plain
    # without [voip], and from an older daemon
    assert decode(encode(snapshot_of(surface))) == snapshot_of(surface)
    older = encode(snapshot_of(surface)).replace(b',"voip":null', b"")
    assert b"voip" not in older
    decoded = decode(older)
    assert decoded is not None
    assert decoded.voip is None
