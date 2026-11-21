import asyncio
import contextlib
import json
import logging
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from tests.support.tasks import finish_tasks, settle
from xtouch_daemon import __version__
from xtouch_daemon.config.sections import VoipConfig
from xtouch_daemon.live.messages import VoipClient
from xtouch_daemon.live.server import voip_state
from xtouch_daemon.voip import Capability, Participant, VoipProvider, build_provider
from xtouch_daemon.voip import demo as demo_module
from xtouch_daemon.voip.bridge import BridgeProvider, ProtocolError, parse_state
from xtouch_daemon.voip.demo import DemoProvider
from xtouch_daemon.voip.provider import Client


@pytest.fixture(autouse=True)
async def no_tasks_left() -> AsyncIterator[None]:
    yield
    await finish_tasks()


@pytest.fixture
def short_dir() -> Iterator[Path]:
    # Unix socket paths are short (108 bytes), the temporary directories of pytest are long
    with tempfile.TemporaryDirectory(prefix="xtd-") as directory:
        yield Path(directory)


def test_the_provider_is_the_demo_or_the_bridge(tmp_path: Path):
    demo = build_provider(VoipConfig(provider="demo", participants=("Ann",)), tmp_path / "s")
    assert isinstance(demo, DemoProvider)
    assert [person.name for person in demo.participants] == ["Ann"]
    bridge = build_provider(VoipConfig(), tmp_path / "s")
    assert isinstance(bridge, BridgeProvider)
    assert bridge.path == tmp_path / "s"


def test_listeners_hear_of_changes_only():
    provider = DemoProvider(("Ann", "Bob"))
    heard: list[str] = []

    def listener() -> None:
        heard.append("changed")

    provider.subscribe(listener)
    provider.update(provider.participants, connected=True)
    assert heard == []
    provider.update(provider.participants[:1])
    assert heard == ["changed"]
    provider.unsubscribe(listener)
    provider.unsubscribe(listener)
    provider.update(())
    assert heard == ["changed"]
    assert provider.participant("1") is None


def test_the_demo_participants_talk_in_turns():
    provider = DemoProvider(("Ann", "Bob"))
    assert provider.connected
    assert provider.capabilities == frozenset(Capability)
    provider.tick(0.0)
    ann, bob = provider.participants
    assert ann.talking
    assert ann.level is not None
    assert ann.level > 0
    assert not bob.talking
    assert bob.level == 0.0
    provider.tick(demo_module.TURN)
    assert [person.talking for person in provider.participants] == [False, True]
    provider.tick(2 * demo_module.TURN)
    # a pause after the last one
    assert [person.talking for person in provider.participants] == [False, False]


async def test_the_demo_keeps_volume_and_mute():
    provider = DemoProvider(("Ann", "Bob"))
    provider.tick(0.0)
    await provider.set_volume("1", 40)
    await provider.set_muted("2", True)
    ann, bob = provider.participants
    assert (ann.volume, ann.talking, bob.muted) == (40, True, True)
    await provider.set_muted("1", True)
    provider.tick(0.0)
    # a muted participant still talks, as in Mumble, but is not heard
    assert provider.participants[0] == Participant(
        "1", "Ann", talking=True, muted=True, volume=40, level=0.0, pre_fader_level=0.0
    )
    await provider.set_muted("1", False)
    provider.tick(0.0)
    assert provider.participants[0].level == pytest.approx(0.35 * 0.4)
    assert provider.participants[0].pre_fader_level == pytest.approx(0.35)


async def test_the_demo_tells_its_listeners_while_it_runs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(demo_module, "TICK", 0.0)
    provider = DemoProvider(("Ann",))
    heard: list[int] = []
    provider.subscribe(lambda: heard.append(1))
    task = asyncio.create_task(provider.run())
    for _ in range(5):
        await asyncio.sleep(0)
    task.cancel()
    assert heard


def test_the_lines_of_the_plugin():
    state = parse_state(
        b'{"client": "mumble", "capabilities": ["volume", "levels"], "unknown": 1, "participants": ['
        b'{"id": 12, "name": "Ann", "talking": true, "volume": 250, "level": 1.5, "pre_fader_level": -0.5, "x": 1},'
        b'{"id": "b", "name": "Bob", "muted": true, "volume": 80.4}]}'
    )
    assert state.client == "mumble"
    assert state.capabilities == (Capability.VOLUME, Capability.LEVELS)
    assert tuple(each.participant() for each in state.participants) == (
        Participant("12", "Ann", talking=True, volume=200, level=1.0, pre_fader_level=0.0),
        Participant("b", "Bob", muted=True, volume=80),
    )
    empty = parse_state(b'{"participants": []}')
    assert (empty.protocol, empty.client, empty.channel, empty.capabilities, empty.participants) == (
        1,
        None,
        None,
        (),
        (),
    )


def test_the_plugin_may_send_numbers_and_truths_of_other_kinds():
    # as the daemon always took them: a number as text, any value for its truth, an empty channel as none
    state = parse_state(
        b'{"protocol": 1.0, "client": 7, "channel": "", "participants": ['
        b'{"id": "1", "name": "Ann", "talking": 1, "muted": "", "volume": "80.6", "level": "0.25", '
        b'"pre_fader_level": null}]}'
    )
    assert state.client == "7"
    assert state.channel is None
    assert state.participants[0].participant() == Participant("1", "Ann", talking=True, volume=81, level=0.25)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (b"nope", "no JSON"),
        (b"[]", "no object with participants"),
        (b'{"participants": 3}', "no object with participants"),
        (b'{"participants": [], "capabilities": ["fly"]}', "capabilities"),
        (b'{"participants": [], "capabilities": null}', "capabilities"),
        (b'{"protocol": "one", "participants": [{"id": 1}]}', "protocol 'one', this daemon speaks 1"),
        (b'{"protocol": 2}', "no object with participants"),
        (b'{"capabilities": ["fly"]}', "no object with participants"),
        (b'{"participants": [{"id": 1.5, "name": "Ann"}]}', "without id or name"),
        (b'{"participants": [{"id": 1, "name": 2}]}', "without id or name"),
        (b'{"participants": [{"id": 1, "name": "Ann", "volume": null}]}', "the volume or level of Ann"),
        (b'{"participants": [{"id": 1, "name": "Ann", "volume": NaN}]}', "the volume or level of Ann"),
        (b'{"participants": [{"id": 1, "name": "Ann", "pre_fader_level": "x"}]}', "the volume or level of Ann"),
        (b'{"participants": [{"id": 1, "name": "Ann", "volume": "x"}, {"name": "Bob"}]}', "the volume or level of"),
        (b'{"participants": [{"name": "Ann"}]}', "without id or name"),
        (b'{"participants": [{"id": 1}]}', "without id or name"),
        (b'{"participants": ["Ann"]}', "without id or name"),
        (
            b'{"participants": [{"id": 1, "name": "Ann", "volume": "loud"}]}',
            "the volume or level of Ann: could not convert string to float: 'loud'",
        ),
        (b'{"participants": [{"id": 1, "name": "Ann", "volume": 1e999}]}', "the volume or level of Ann"),
        (b'{"participants": [{"id": 1, "name": "Ann", "level": []}]}', "the volume or level of Ann"),
        (b'{"protocol": 2, "participants": []}', "protocol 2, this daemon speaks 1: update the plugin or the daemon"),
    ],
)
def test_lines_that_are_not_the_protocol(line: bytes, message: str):
    with pytest.raises(ProtocolError, match=message):
        parse_state(line)


async def _wait(condition: object) -> None:
    for _ in range(200):
        if callable(condition) and condition():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("never happened")


async def _plugin(path: Path, *lines: bytes) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """A plugin that connects, reads the greeting and sends `lines`."""
    reader, writer = await asyncio.open_unix_connection(path)
    assert json.loads(await reader.readline()) == {"daemon": "xtouch-daemon", "version": __version__, "protocol": 1}
    for line in lines:
        writer.write(line + b"\n")
    await writer.drain()
    return reader, writer


async def _close(*writers: asyncio.StreamWriter) -> None:
    for each in writers:
        each.close()
        with contextlib.suppress(ConnectionError):
            await each.wait_closed()


async def test_the_bridge_takes_the_participants_of_a_plugin(short_dir: Path, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)
    path = short_dir / "run" / "voip.sock"
    provider = BridgeProvider(path)
    heard: list[tuple[Participant, ...]] = []
    provider.subscribe(lambda: heard.append(provider.participants))
    task = asyncio.create_task(provider.run())
    await _wait(path.exists)
    assert path.stat().st_mode & 0o777 == 0o600
    # without a plugin, commands go nowhere
    await provider.set_volume("mumble:1", 50)
    assert provider.clients == ()

    reader, writer = await _plugin(
        path,
        b'{"protocol": 1, "client": "mumble", "channel": "Lobby", "capabilities": ["volume", "mute"], '
        b'"participants": [{"id": 1, "name": "A"}]}',
        b"",
        b"rubbish",
    )
    await _wait(lambda: provider.connected)
    assert provider.client == "mumble"
    assert provider.channel == "Lobby"
    assert provider.capabilities == {Capability.VOLUME, Capability.MUTE}
    assert provider.clients == (Client("mumble", "Lobby", frozenset({Capability.VOLUME, Capability.MUTE})),)
    # the client in front of the id
    assert provider.participants == (Participant("mumble:1", "A"),)
    assert provider.capabilities_of("mumble:1") == {Capability.VOLUME, Capability.MUTE}
    assert provider.capabilities_of("mumble:9") == frozenset()
    await _wait(lambda: "Ignoring a line of the voice chat plugin: no JSON" in caplog.text)

    # the commands have the id of the client
    await provider.set_volume("mumble:1", 70)
    await provider.set_muted("mumble:1", True)
    # nobody of that id: nothing goes out
    await provider.set_muted("mumble:9", True)
    assert json.loads(await reader.readline()) == {"set_volume": {"id": "1", "volume": 70}}
    assert json.loads(await reader.readline()) == {"set_muted": {"id": "1", "muted": True}}

    # another plugin of the same client is refused at its first state line, and said so once
    for _ in range(2):
        refused_reader, refused_writer = await _plugin(path, b'{"client": "mumble", "participants": []}')
        assert json.loads(await refused_reader.readline()) == {"error": "another mumble plugin is connected"}
        assert await refused_reader.read() == b""
        await _close(refused_writer)
    assert caplog.text.count("Refusing another voice chat plugin of mumble") == 1
    assert provider.participants == (Participant("mumble:1", "A"),)

    # once it is gone, the next one comes in
    await _close(writer)
    await _wait(lambda: not provider.connected)
    assert "The voice chat plugin of mumble is gone" in caplog.text
    assert provider.participants == ()
    assert provider.client is None
    assert provider.channel is None
    assert heard[-1] == ()
    reader2, writer2 = await _plugin(path, b'{"participants": [{"id": 2, "name": "B"}]}')
    # it does not say which client it is, nor a channel
    await _wait(lambda: provider.participants == (Participant("a client:2", "B"),))
    assert provider.client == "a client"
    assert provider.channel is None
    # another one that doesn't say either is refused as before
    refused_reader, refused_writer = await _plugin(path, b'{"participants": []}')
    assert json.loads(await refused_reader.readline()) == {"error": "another plugin is connected"}
    await _close(refused_writer, writer2)
    await _wait(lambda: not provider.connected)

    # a plugin that is still connected when the daemon stops, and one that sent nothing yet
    _, writer3 = await _plugin(path, b'{"participants": []}')
    reader4, writer4 = await _plugin(path)
    await _wait(lambda: provider.connected)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not path.exists()
    assert await reader4.read() == b""
    await _close(writer3, writer4)
    assert await reader2.read() == b""


async def test_the_bridge_takes_a_plugin_of_each_client(short_dir: Path, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)
    path = short_dir / "voip.sock"
    provider = BridgeProvider(path)
    task = asyncio.create_task(provider.run())
    await _wait(path.exists)
    # connected, but no state yet: it counts for nothing, so it can't keep another one out
    quiet_reader, quiet_writer = await _plugin(path)
    mumble_reader, mumble_writer = await _plugin(
        path,
        b'{"client": "mumble", "channel": "Lobby", "capabilities": ["volume", "mute", "levels"], '
        b'"participants": [{"id": 12, "name": "Alice"}]}',
    )
    await _wait(lambda: len(provider.participants) == 1)
    assert not quiet_reader.at_eof()
    teamspeak_reader, teamspeak_writer = await _plugin(
        path,
        b'{"client": "teamspeak", "capabilities": ["mute"], '
        b'"participants": [{"id": 12, "name": "Bob"}, {"id": 3, "name": "Carol", "muted": true}]}',
    )
    await _wait(lambda: len(provider.participants) == 3)

    # the people of both, with their client in front of the ids, which are the same in each client
    assert provider.participants == (
        Participant("mumble:12", "Alice"),
        Participant("teamspeak:12", "Bob"),
        Participant("teamspeak:3", "Carol", muted=True),
    )
    assert provider.clients == (
        Client("mumble", "Lobby", frozenset(Capability)),
        Client("teamspeak", None, frozenset({Capability.MUTE})),
    )
    assert provider.client == "mumble, teamspeak"
    # the first channel there is: the user is in a call
    assert provider.channel == "Lobby"
    assert provider.capabilities == frozenset(Capability)
    assert provider.capabilities_of("teamspeak:12") == {Capability.MUTE}

    # each command goes to the plugin of the participant, with the id there
    await provider.set_muted("teamspeak:3", False)
    await provider.set_volume("mumble:12", 80)
    assert json.loads(await teamspeak_reader.readline()) == {"set_muted": {"id": "3", "muted": False}}
    assert json.loads(await mumble_reader.readline()) == {"set_volume": {"id": "12", "volume": 80}}

    # a line changes the people of its client only
    teamspeak_writer.write(
        b'{"client": "teamspeak", "channel": "Room", "participants": [{"id": 3, "name": "Carol"}]}\n'
    )
    await teamspeak_writer.drain()
    await _wait(lambda: len(provider.participants) == 2)
    assert [each.id for each in provider.participants] == ["mumble:12", "teamspeak:3"]
    assert provider.clients[1] == Client("teamspeak", "Room")

    # when one goes, only its people go
    await _close(mumble_writer)
    await _wait(lambda: provider.participants == (Participant("teamspeak:3", "Carol"),))
    assert provider.connected
    assert provider.client == "teamspeak"
    assert provider.channel == "Room"
    assert provider.capabilities == frozenset()
    await provider.set_volume("mumble:12", 50)
    assert "The voice chat plugin of mumble is gone" in caplog.text

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await _close(quiet_writer, teamspeak_writer)


class FakeWriter:
    """The parts of a `StreamWriter` the bridge uses."""

    def __init__(self) -> None:
        self.closed = False
        self.lines: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.lines.append(data)

    def close(self) -> None:
        self.closed = True


async def test_a_socket_that_can_not_be_made_is_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    blocker = tmp_path / "file"
    blocker.write_text("")
    provider: VoipProvider = BridgeProvider(blocker / "voip.sock")
    await provider.run()
    assert "No voice chat participants, can't serve" in caplog.text


async def test_the_bridge_stops_without_a_plugin(short_dir: Path):
    path = short_dir / "voip.sock"
    task = asyncio.create_task(BridgeProvider(path).run())
    await _wait(path.exists)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not path.exists()


class RecordingProvider(VoipProvider):
    """Records the commands; the participants are set by the tests."""

    def __init__(self) -> None:
        super().__init__(frozenset(Capability))
        self.commands: list[tuple[str, str, object]] = []

    async def run(self) -> None:
        await asyncio.Event().wait()

    async def set_volume(self, participant_id: str, volume: int) -> None:
        self.commands.append(("volume", participant_id, volume))

    async def set_muted(self, participant_id: str, muted: bool) -> None:
        self.commands.append(("muted", participant_id, muted))


async def test_volume_and_mute_last_while_a_person_is_away():
    provider = RecordingProvider()
    provider.update((Participant("1", "Alice"), Participant("2", "Bob")))
    await provider.change_volume("1", 40)
    await provider.change_muted("2", True)
    # someone who is not there keeps nothing
    await provider.change_volume("9", 10)
    await provider.change_muted("9", True)
    assert provider.commands == [("volume", "1", 40), ("muted", "2", True), ("volume", "9", 10), ("muted", "9", True)]
    provider.commands.clear()
    # they leave, and come back with new ids, as the clients start them: at 100 %, not muted
    provider.update(())
    provider.update((Participant("3", "ALICE"), Participant("4", "Bob"), Participant("5", "Carol")))
    await settle()
    assert provider.commands == [("volume", "3", 40), ("muted", "4", True)]
    provider.commands.clear()
    # what the client tells already, and someone who stays, get nothing again
    provider.update((Participant("3", "ALICE", volume=40), Participant("6", "bob", muted=True)))
    await settle()
    assert provider.commands == []
    # Bob unmuted in the client (Mumble's local mute), Alice muted there: what the strips set does not undo it when
    # they come back; Alice's mute was never set by a strip, so the client keeps it on its own
    provider.update((Participant("3", "ALICE", volume=40, muted=True), Participant("6", "bob")))
    provider.update(())
    provider.update((Participant("7", "Alice", muted=True), Participant("8", "Bob")))
    await settle()
    assert provider.commands == [("volume", "7", 40)]


def test_a_provider_of_one_client_has_it_as_its_clients():
    provider = RecordingProvider()
    assert provider.clients == ()
    provider.client = "mumble"
    provider.channel = "Lobby"
    # not before it is connected
    assert provider.clients == ()
    provider.update((Participant("1", "Ann"),))
    assert provider.clients == (Client("mumble", "Lobby", frozenset(Capability)),)
    assert provider.capabilities_of("1") == frozenset(Capability)
    assert voip_state(provider).clients == (VoipClient("mumble", "Lobby"),)
    # the demo tells no client
    assert DemoProvider(("Ann",)).clients == ()
