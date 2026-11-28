import asyncio
import dataclasses
import json
import logging
import os
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.support.hardware import RecordingSurface
from tests.support.tasks import finish_tasks
from tests.support.waiting import until
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware import surface as surface_module
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.live import codec
from xtouch_daemon.live import server as server_module
from xtouch_daemon.live.codec import (
    decode,
    decode_message,
    decode_request,
    encode,
    encode_known,
    encode_reply,
    encode_request,
    encode_twin,
)
from xtouch_daemon.live.messages import (
    FEATURES,
    EndPreview,
    EndTest,
    ForgetDevice,
    KeepPreview,
    KeepTest,
    KnownDevice,
    KnownDevices,
    MqttState,
    Play,
    Reply,
    Request,
    SetMode,
    SetOverride,
    SlotsState,
    SlotView,
    Snapshot,
    StartPreview,
    StartTest,
    StateView,
    StripState,
    TwinView,
    VoipClient,
    VoipState,
    fingerprint,
    meter_now,
)
from xtouch_daemon.live.server import MAX_BUFFER, LiveServer, peer_uid, strip_states
from xtouch_daemon.simulator.device import METER_FALL
from xtouch_daemon.slots.outcomes import Situation


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
            await asyncio.sleep(0.02)
            return task
        await asyncio.sleep(0.005)
    raise AssertionError("the server did not start")


def test_a_strip_is_described_as_the_device_shows_it(surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(surface_module.time, "monotonic", lambda: 100.0)
    strip = surface.strips[2]
    strip.set_color(Color.CYAN)
    strip.set_text(0, "Speaker")
    strip.set_text(1, "46%")
    strip.set_led(Button.MUTE, Led.ON)
    strip.set_led(Button.SELECT, Led.FLASH)
    strip.set_ring(7, RingMode.WRAP)
    surface.send(protocol.fader(2, 8191))
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
        meter=10,
        meter_at=100.0,
    )
    # the GUI lets the meter fall from there, to 0 and not below
    assert meter_now(states[2], 100.0 + 2 * METER_FALL + 0.01) == 8
    assert meter_now(states[2], 1000.0) == 0
    # nothing known yet: dark, and no fader position
    assert states[0].color == "off"
    assert states[0].fader is None


async def test_the_fader_is_where_a_hand_put_it(surface: RecordingSurface):
    surface._on_data(protocol.fader_moved(0, 4092))

    assert strip_states(surface, 0.0)[0].fader == round(4092 / 16383, 4)


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
    # the device plugged in while the daemon drives the virtual one
    plugged = Snapshot("abc", True, False, None, snapshot.strips, virtual=True, device_plugged=True)
    assert decode(encode(plugged)) == plugged
    # with slots
    slots = SlotsState(
        "gaming",
        None,
        (SlotView(1, 0, "out", None, None, ("shows out",)), SlotView(2, 1, None, "auto", "app:Spotify", ())),
        (
            StateView(
                "call", True, False, "2026-11-17T10:00:00+00:00", "mumble runs", "auto", ((1.0, False), (2.0, True))
            ),
        ),
        {"auto": ("app:mpv",)},
    )
    with_slots = Snapshot("abc", True, False, None, snapshot.strips, slots=slots)
    assert decode(encode(with_slots)) == with_slots
    # with reality as a situation, where Simulate starts
    now = Situation("gaming", frozenset({"call", "night"}), frozenset({"voip"}), people=2, apps=1, devices=0)
    with_now = Snapshot("abc", True, False, None, snapshot.strips, slots=dataclasses.replace(slots, now=now))
    assert decode(encode(with_now)) == with_now
    assert b'"on":["call","night"]' in encode(with_now)
    with pytest.raises(TypeError, match="object is not JSON"):
        codec._sets(object())  # pyright: ignore[reportPrivateUsage]
    # with the channels that have sound; an older daemon tells none
    sounding = Snapshot("abc", True, False, None, snapshot.strips, sounding=("out", "game"))
    assert decode(encode(sounding)) == sounding
    assert decode(encode(sounding).replace(b',"sounding":["out","game"]', b"")) == dataclasses.replace(
        sounding, sounding=()
    )
    with pytest.raises(ValueError, match="Expecting value"):
        decode(b"garbage")


def test_the_fingerprint_tells_configurations_apart():
    speaker = parse_config('[channel.out]\ntype = "output"\nlabel = "Speaker"\n')
    secret = '[mqtt]\nhost = "broker"\npassword = "{}"\n'

    assert fingerprint(speaker) == fingerprint(parse_config('[channel.out]\ntype = "output"\nlabel = "Speaker"\n'))
    assert fingerprint(speaker) != fingerprint(parse_config('[channel.out]\ntype = "output"\nlabel = "Boxes"\n'))
    # also a changed password, which a dump shows as stars
    assert fingerprint(parse_config(secret.format("one"))) != fingerprint(parse_config(secret.format("two")))
    assert len(fingerprint(speaker)) == 16


async def test_a_client_gets_the_state_at_once_and_then_every_change(surface: RecordingSurface, socket_dir: Path):
    server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface))
    surface.on_change = server.changed
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

    # told again what it shows already: nothing is sent
    surface.send(protocol.lcd_text(0, 0, "Mic"))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(reader.readline(), 0.1)

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
    surface.on_change = server.changed
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
    surface.on_change = server.changed
    task = await serve(server)
    reader, writer = await asyncio.open_unix_connection(server.path)
    await reader.readline()

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert await asyncio.wait_for(reader.read(), 1) == b""
    writer.close()


async def test_a_client_that_does_not_read_keeps_neither_the_server_nor_the_daemon_from_ending(
    surface: RecordingSurface, socket_dir: Path
):
    # e.g. the GUI, frozen while it waits for `systemctl stop`: the daemon ends all the same
    server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface))
    task = await serve(server)
    frozen = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    frozen.connect(str(server.path))
    for _ in range(100):
        if server.clients:
            break
        await asyncio.sleep(0.005)
    (client,) = server.clients
    # more than the socket takes: the rest waits in the server for a read that never comes
    client.write(b"x" * 10_000_000)
    assert client.transport.get_write_buffer_size() > 0
    serving = [
        other for other in asyncio.all_tasks() if getattr(other.get_coro(), "__qualname__", "") == "LiveServer._serve"
    ]
    assert len(serving) == 1

    # the server stops, then the end of the daemon (`asyncio.run()`) cancels what is left and waits for it
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    for other in serving:
        other.cancel()
    _, pending = await asyncio.wait(serving, timeout=1)
    frozen.close()
    assert not pending


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
    for request in (
        StartPreview('[channel.x]\ntype = "empty"\n'),
        KeepPreview(),
        EndPreview(),
        SetMode("gaming"),
        SetOverride("call", "on"),
        StartPreview(
            "[slots]\n",
            Situation("gaming", frozenset({"call"}), frozenset({"mic"}), people=2, apps=1, devices=3),
            on_device=False,
        ),
        Play(protocol.ButtonPressed(2, Button.MUTE, True), preview=True),
        Play(protocol.FaderTouched(1, False)),
    ):
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
        decode_request(b'{"request": "layout", "layout": "gaming"}')

    reply = Reply("preview", False, "strip[1].type: wrong")
    assert decode_message(encode_reply(reply)) == reply

    # a GUI that knows no replies ignores them like lines of another version
    assert decode(encode_reply(reply)) is None
    assert b'"version"' not in encode_reply(reply)
    # the snapshot of a daemon that previews
    snapshot = dataclasses.replace(snapshot_of(surface), preview=True, features=FEATURES)
    assert decode_message(encode(snapshot)) == snapshot


@pytest.mark.parametrize(
    "event",
    [
        protocol.FaderMoved(0, 8191),
        protocol.FaderTouched(1, True),
        protocol.ButtonPressed(2, Button.SELECT, False),
        protocol.EncoderTurned(3, -2),
        protocol.EncoderPressed(7, True),
    ],
)
def test_every_event_a_hand_plays_goes_through_a_line(event: protocol.StripEvent):
    assert decode_request(encode_request(Play(event))) == Play(event)


def test_the_devices_the_daemon_remembers_go_through_a_line_and_are_no_snapshot():
    known = KnownDevices((KnownDevice("buds", "Buds", "output", None, None, 1.5),))
    line = encode_known(known)
    assert line.count(b"\n") == 1
    assert decode_message(line) == known
    assert decode(line) is None


def test_a_device_to_forget_goes_through_a_line():
    request = ForgetDevice("bluez_output.buds", "output")
    assert decode_request(encode_request(request)) == request


@pytest.mark.parametrize("request_", [StartTest(), KeepTest(), EndTest()])
def test_the_requests_of_the_test_go_through_a_line(request_: StartTest | KeepTest | EndTest):
    assert decode_request(encode_request(request_)) == request_


def test_a_snapshot_of_a_test_with_the_led_below_the_ring_goes_through_a_line(surface: RecordingSurface):
    surface.strips[0].set_ring(6, RingMode.SPREAD, center=True)
    snapshot = dataclasses.replace(snapshot_of(surface), test=True)
    assert snapshot.strips[0].ring_center
    assert decode(encode(snapshot)) == snapshot
    # of a daemon of 0.2.0, which tells neither
    line = encode(snapshot).replace(b',"test":true', b"").replace(b',"ring_center":true', b"")
    assert decode(line) == dataclasses.replace(
        snapshot, test=False, strips=(dataclasses.replace(snapshot.strips[0], ring_center=False), *snapshot.strips[1:])
    )


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ('{"request": "preview", "config": null, "on_device": "yes"}', "on_device is no boolean"),
        ('{"request": "preview", "config": null, "situation": {"mode": "x"}}', "not a situation"),
        (
            '{"request": "preview", "config": null, "situation": '
            '{"mode": "x", "on": [], "flipped": [], "people": -1, "apps": 0, "devices": 0}}',
            "not a situation",
        ),
        ('{"request": "play", "event": "fader_moved", "strip": 8, "value": 0}', "no strip 8"),
        ('{"request": "play", "event": "fader_moved", "strip": 0, "value": 99999}', "not a fader_moved event"),
        ('{"request": "play", "event": "button_pressed", "strip": 0, "button": 1, "pressed": true}', "not a button"),
        ('{"request": "play", "event": "reboot", "strip": 0}', "unknown"),
        ('{"request": "forget_device", "name": "x", "direction": "sideways"}', "unknown"),
    ],
)
def test_requests_that_do_not_fit_are_refused(line: str, message: str):
    with pytest.raises(ValueError, match=message):
        decode_request(line.encode())


def test_the_view_of_a_twin_goes_through_a_line_and_is_no_snapshot():
    state = StripState(
        color="cyan",
        text=("Out", "50%"),
        leds={"rec": "off", "solo": "off", "mute": "on", "select": "flash"},
        ring=3,
        ring_mode="dot",
        fader=0.5,
        touched=False,
        meter=2,
    )
    view = TwinView("abc", (state,), SlotsState("default", None, (), (), {}))
    line = encode_twin(view)
    assert line.count(b"\n") == 1
    assert decode_message(line) == view
    assert decode(line) is None


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
    surface.on_change = server.changed
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


def test_the_live_view_shows_a_banner(surface: RecordingSurface):
    surface.strips[0].set_text(0, "Speaker")
    surface.strips[0].set_overlay(("Gaming", ""))
    assert strip_states(surface, 0.0)[0].text == ("Gaming", "")


def test_the_voice_chat_goes_through_a_line(surface: RecordingSurface):
    voip = VoipState(
        "bridge",
        True,
        "mumble, teamspeak",
        "Lobby",
        3,
        ("Ann", "Bob", "Carol"),
        ("mumble:a", "mumble:b", "teamspeak:c"),
        (VoipClient("mumble", "Lobby"), VoipClient("teamspeak")),
    )
    snapshot = dataclasses.replace(snapshot_of(surface), voip=voip)
    assert decode(encode(snapshot)) == snapshot
    # from an older daemon, without the clients
    line = json.loads(encode(snapshot))
    del line["voip"]["clients"]
    decoded = decode((json.dumps(line) + "\n").encode())
    assert isinstance(decoded, Snapshot)
    assert decoded.voip == dataclasses.replace(voip, clients=())
    # without [voip]
    assert decode(encode(snapshot_of(surface))) == snapshot_of(surface)
