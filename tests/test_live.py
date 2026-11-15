import asyncio
import logging
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from tests.conftest import RecordingSurface, finish_tasks
from xtouch_daemon import live
from xtouch_daemon import surface as surface_module
from xtouch_daemon.config import parse_config
from xtouch_daemon.live import LiveServer, Snapshot, StripState, decode, encode, fingerprint, strip_states
from xtouch_daemon.protocol import Button, Color, Led, RingMode


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
            await asyncio.sleep(2 * live.INTERVAL)
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
    monkeypatch.setattr(surface_module.time, "monotonic", lambda: 100.0)
    strip.set_meter(10)
    monkeypatch.undo()

    states = strip_states(surface, 100.0 + 2 * live.METER_FALL + 0.01)

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
        await asyncio.wait_for(reader.readline(), 3 * live.INTERVAL)

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
    monkeypatch.setattr(client.transport, "get_write_buffer_size", lambda: live.MAX_BUFFER + 1)

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
