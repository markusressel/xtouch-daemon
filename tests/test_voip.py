import asyncio
import contextlib
import json
import logging
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from tests.conftest import finish_tasks, settle
from xtouch_daemon import __version__
from xtouch_daemon.config import VoipConfig
from xtouch_daemon.voip import Capability, Participant, VoipProvider, build_provider
from xtouch_daemon.voip import demo as demo_module
from xtouch_daemon.voip.bridge import BridgeProvider, ProtocolError, parse_state
from xtouch_daemon.voip.demo import DemoProvider


@pytest.fixture(autouse=True)
async def no_tasks_left() -> AsyncIterator[None]:
    yield
    await finish_tasks()


@pytest.fixture
def short_dir() -> Iterator[Path]:
    # Unix socket paths are short (108 bytes), the temporary directories of pytest are long
    with tempfile.TemporaryDirectory(prefix="xtd-") as directory:
        yield Path(directory)


def test_build_provider(tmp_path: Path):
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
    # a muted participant is not heard
    assert provider.participants[0] == Participant("1", "Ann", talking=False, muted=True, volume=40, level=0.0)


async def test_the_demo_runs(monkeypatch: pytest.MonkeyPatch):
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
    participants, capabilities = parse_state(
        b'{"client": "mumble", "capabilities": ["volume", "levels"], "participants": ['
        b'{"id": 12, "name": "Ann", "talking": true, "volume": 250, "level": 1.5},'
        b'{"id": "b", "name": "Bob", "muted": true, "volume": 80.4}]}'
    )
    assert capabilities == {Capability.VOLUME, Capability.LEVELS}
    assert participants == (
        Participant("12", "Ann", talking=True, volume=200, level=1.0),
        Participant("b", "Bob", muted=True, volume=80),
    )
    assert parse_state(b'{"participants": []}') == ((), frozenset())


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (b"nope", "no JSON"),
        (b"[]", "no object with participants"),
        (b'{"participants": 3}', "no object with participants"),
        (b'{"participants": [], "capabilities": ["fly"]}', "capabilities"),
        (b'{"participants": [{"name": "Ann"}]}', "without id or name"),
        (b'{"participants": [{"id": 1}]}', "without id or name"),
        (b'{"participants": ["Ann"]}', "without id or name"),
        (b'{"participants": [{"id": 1, "name": "Ann", "volume": "loud"}]}', "the volume or level of Ann"),
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
    await provider.set_volume("1", 50)

    reader, writer = await asyncio.open_unix_connection(path)
    # the daemon says who it is first
    assert json.loads(await reader.readline()) == {"daemon": "xtouch-daemon", "version": __version__, "protocol": 1}
    writer.write(
        b'{"protocol": 1, "client": "mumble", "channel": "Lobby", "capabilities": ["volume", "mute"], '
        b'"participants": [{"id": 1, "name": "A"}]}\n'
    )
    writer.write(b"\n")
    writer.write(b"rubbish\n")
    await writer.drain()
    await _wait(lambda: provider.connected)
    assert provider.client == "mumble"
    assert provider.channel == "Lobby"
    assert provider.capabilities == {Capability.VOLUME, Capability.MUTE}
    assert provider.participants == (Participant("1", "A"),)
    assert "Ignoring a line of the voice chat plugin: no JSON" in caplog.text

    await provider.set_volume("1", 70)
    await provider.set_muted("1", True)
    assert json.loads(await reader.readline()) == {"set_volume": {"id": "1", "volume": 70}}
    assert json.loads(await reader.readline()) == {"set_muted": {"id": "1", "muted": True}}

    # a second plugin is refused while the first one is there, and said so once
    for _ in range(2):
        refused_reader, refused_writer = await asyncio.open_unix_connection(path)
        assert json.loads(await refused_reader.readline()) == {"error": "another plugin is connected"}
        assert await refused_reader.read() == b""
        refused_writer.close()
    assert caplog.text.count("Refusing another voice chat plugin") == 1
    assert provider.participants == (Participant("1", "A"),)

    # once it is gone, the next one comes in
    writer.close()
    await _wait(lambda: not provider.connected)
    reader2, writer2 = await asyncio.open_unix_connection(path)
    writer2.write(b'{"participants": [{"id": 2, "name": "B"}]}\n')
    await writer2.drain()
    await _wait(lambda: provider.participants == (Participant("2", "B"),))
    # it does not say which client it is
    assert provider.client == "a client"
    # it tells no channel
    assert provider.channel is None

    writer2.close()
    await _wait(lambda: not provider.connected)
    assert provider.participants == ()
    assert provider.client is None
    assert heard[-1] == ()
    assert "The voice chat plugin is gone" in caplog.text

    # a plugin that is still connected when the daemon stops
    _, writer3 = await asyncio.open_unix_connection(path)
    writer3.write(b'{"participants": []}\n')
    await writer3.drain()
    await _wait(lambda: provider.connected)
    assert provider.client == "a client"
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not path.exists()
    for each in (writer, writer2, writer3):
        each.close()
        with contextlib.suppress(ConnectionError):
            await each.wait_closed()
    # its greeting, then nothing
    assert json.loads(await reader2.readline())["daemon"] == "xtouch-daemon"
    assert await reader2.read() == b""


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
