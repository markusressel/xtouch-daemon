import asyncio
import os
import subprocess
from collections.abc import AsyncIterator, Callable, Iterator

import pytest
import pytest_asyncio
from dbus_fast import Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import PropertyAccess
from dbus_fast.service import ServiceInterface, dbus_property, method

from tests.conftest import FakeBackend, RecordingSurface, settle, stream
from xtouch_daemon import media
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.media import MediaCommandError, MprisPlayers, Player, ancestors, parent_pid, player_of
from xtouch_daemon.protocol import RingMode
from xtouch_daemon.strips import knobs
from xtouch_daemon.strips.apps import AppGroupStrip
from xtouch_daemon.strips.base import StripEnv

# -- which player plays the streams ---------------------------------------------------------------------------------


def parents(tree: dict[int, int]) -> Callable[[int], int | None]:
    return tree.get


def test_a_process_has_its_parents():
    assert ancestors(30, parents({30: 20, 20: 10, 10: 1})) == [30, 20, 10]
    # a loop ends
    assert ancestors(30, parents({30: 20, 20: 30})) == [30, 20]
    assert ancestors(30, parents({})) == [30]


def test_the_parent_of_a_real_process():
    assert parent_pid(os.getpid()) == os.getppid()
    assert ancestors(os.getpid())[:2] == [os.getpid(), os.getppid()]
    assert parent_pid(2**22 + 1) is None


def test_a_player_is_found_by_the_process_or_the_name():
    brave = Player("org.mpris.MediaPlayer2.brave.instance100", 100)
    spotify = Player("org.mpris.MediaPlayer2.spotify", 200)
    tree = parents({101: 100, 300: 1})
    assert brave.name == "brave"
    # a child process of the browser plays
    assert player_of([spotify, brave], [stream(1, "Brave", "brave", pid=101)], tree) == brave
    # by name: the process is unknown, or none of a player
    assert player_of([brave, spotify], [stream(2, "Spotify", "spotify")], tree) == spotify
    assert player_of([brave, spotify], [stream(2, "spotify", "x", pid=300)], tree) == spotify
    assert player_of([brave], [stream(3, "mpv", "mpv", pid=300)], tree) is None
    # a playing stream first
    streams = [stream(1, "Spotify", "spotify", corked=True), stream(2, "Brave", "brave", pid=101)]
    assert player_of([spotify, brave], streams, tree) == brave


# -- the session bus ------------------------------------------------------------------------------------------------


@pytest.fixture
def bus_address() -> Iterator[str]:
    """A bus of its own, so the tests don't see the players of the machine they run on."""
    daemon = subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address=1"], stdout=subprocess.PIPE, text=True
    )
    assert daemon.stdout is not None
    address = daemon.stdout.readline().strip()
    yield address
    daemon.terminate()
    daemon.wait()
    daemon.stdout.close()


class Player2(ServiceInterface):
    """The parts of the MPRIS player interface the daemon uses."""

    def __init__(self, length: int | None) -> None:
        super().__init__("org.mpris.MediaPlayer2.Player")
        self.calls: list[object] = []
        self.length = length

    @method()
    def PlayPause(self) -> None:
        self.calls.append("PlayPause")

    @method()
    def Seek(self, offset: "x") -> None:  # type: ignore[valid-type]  # noqa: F821, UP037
        self.calls.append(("Seek", offset))

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "x":  # type: ignore[valid-type]  # noqa: F821, UP037
        return 30_000_000

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> "a{sv}":  # type: ignore[valid-type]  # noqa: F722
        return {} if self.length is None else {"mpris:length": Variant("x", self.length)}


@pytest_asyncio.fixture
async def players(bus_address: str) -> AsyncIterator[MprisPlayers]:
    players = MprisPlayers(lambda: MessageBus(bus_address=bus_address).connect(), interval=0.01)
    task = asyncio.create_task(players.run())
    yield players
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def serve(bus_address: str, name: str, length: int | None) -> tuple[MessageBus, Player2]:
    bus = await MessageBus(bus_address=bus_address).connect()
    player = Player2(length)
    bus.export("/org/mpris/MediaPlayer2", player)
    await bus.request_name(name)
    return bus, player


async def wait_for(condition: Callable[[], bool]) -> None:
    for _ in range(500):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the condition did not come true")


async def test_players_come_and_go_and_take_commands(bus_address: str, players: MprisPlayers) -> None:
    bus, service = await serve(bus_address, "org.mpris.MediaPlayer2.spotify", 120_000_000)
    other, _ = await serve(bus_address, "org.example.NotAPlayer", None)
    await wait_for(lambda: bool(players.players))

    (player,) = players.players
    assert player == Player("org.mpris.MediaPlayer2.spotify", os.getpid())
    await players.play_pause(player)
    await players.seek(player, -5)
    assert service.calls == ["PlayPause", ("Seek", -5_000_000)]
    assert await players.progress(player) == 0.25

    bus.disconnect()
    other.disconnect()
    await wait_for(lambda: not players.players)
    with pytest.raises(MediaCommandError, match=r"PlayPause: org\.freedesktop\.DBus\.Error\.ServiceUnknown"):
        await players.play_pause(player)


async def test_a_track_without_a_length_has_no_progress(bus_address: str, players: MprisPlayers) -> None:
    bus, _ = await serve(bus_address, "org.mpris.MediaPlayer2.radio", None)
    await wait_for(lambda: bool(players.players))
    assert await players.progress(players.players[0]) is None
    bus.disconnect()


async def test_without_a_session_bus_there_are_no_players(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(media, "RECONNECT_DELAY", 0.01)
    attempts: list[int] = []

    async def unreachable() -> MessageBus:
        attempts.append(1)
        raise FileNotFoundError("no socket")

    players = MprisPlayers(unreachable)
    task = asyncio.create_task(players.run())
    await wait_for(lambda: len(attempts) >= 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # once
    assert caplog.text.count("No media players: the session bus is not reachable (no socket)") == 1
    assert players.players == ()
    with pytest.raises(MediaCommandError, match="not connected"):
        await players.play_pause(Player("org.mpris.MediaPlayer2.x", None))


async def test_a_player_whose_process_is_unknown(bus_address: str, monkeypatch: pytest.MonkeyPatch) -> None:
    players = MprisPlayers(lambda: MessageBus(bus_address=bus_address).connect())
    players._bus = await MessageBus(bus_address=bus_address).connect()
    bus, _ = await serve(bus_address, "org.mpris.MediaPlayer2.mpv", None)
    real_call = players._call

    async def no_pid(**message: object) -> list[object]:
        if message["member"] == "GetConnectionUnixProcessID":
            raise MediaCommandError("unknown")
        return await real_call(**message)

    monkeypatch.setattr(players, "_call", no_pid)
    assert await players._list() == (Player("org.mpris.MediaPlayer2.mpv", None),)
    bus.disconnect()
    players._bus.disconnect()


# -- the knob ---------------------------------------------------------------------------------------------------


class FakePlayers:
    def __init__(self, *players: Player) -> None:
        self.players = players
        self.calls: list[tuple[str, object]] = []
        self.progresses: dict[str, float | None] = {}
        self.failing = False

    async def run(self) -> None:
        await asyncio.Event().wait()

    async def play_pause(self, player: Player) -> None:
        self.calls.append(("play_pause", player.name))

    async def seek(self, player: Player, seconds: float) -> None:
        self.calls.append(("seek", seconds))

    async def progress(self, player: Player) -> float | None:
        if self.failing:
            raise MediaCommandError("gone")
        return self.progresses.get(player.name)


SPOTIFY = Player("org.mpris.MediaPlayer2.spotify", None)


def browser(surface: RecordingSurface, env: StripEnv, players: FakePlayers | None) -> AppGroupStrip:
    env = StripEnv(env.backend, env.behavior, players=players)
    return AppGroupStrip(surface.strips[0], env, ("spotify",), "Music", encoder="media")


async def test_the_encoder_seeks_and_plays_or_pauses_the_player(
    surface: RecordingSurface, env: StripEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knobs, "PROGRESS_INTERVAL", 0.01)
    players = FakePlayers(SPOTIFY)
    players.progresses["spotify"] = 0.5
    strip = browser(surface, env, players)
    strip.update(AudioState(streams=(stream(1, "Spotify", "spotify"),)))
    await wait_for(lambda: surface.strips[0].ring == (6, RingMode.DOT))
    # idle: no track
    strip.update(AudioState())
    await wait_for(lambda: strip.knob.progress is None)  # type: ignore[attr-defined]
    strip.update(AudioState(streams=(stream(1, "Spotify", "spotify"),)))
    await wait_for(lambda: surface.strips[0].ring == (6, RingMode.DOT))

    strip.on_encoder(-2)
    strip.on_encoder_press(True)
    strip.on_encoder_press(False)
    await settle()
    assert players.calls == [("seek", -10.0), ("play_pause", "spotify")]

    # a player that went away
    players.failing = True
    await wait_for(lambda: surface.strips[0].ring == (0, RingMode.DOT))
    strip.close()


async def test_without_a_player_the_encoder_does_nothing(
    surface: RecordingSurface, env: StripEnv, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knobs, "PROGRESS_INTERVAL", 0.01)
    players = FakePlayers()
    strip = browser(surface, env, players)
    strip.update(AudioState(streams=(stream(1, "Spotify", "spotify"),)))
    strip.on_encoder(1)
    strip.on_encoder_press(True)
    await asyncio.sleep(0.03)
    assert players.calls == []
    assert surface.strips[0].ring == (0, RingMode.DOT)
    # idle: no progress is asked for
    strip.update(AudioState())
    await asyncio.sleep(0.03)
    strip.close()

    # without media players at all
    strip = browser(surface, env, None)
    strip.update(AudioState(streams=(stream(1, "Spotify", "spotify"),)))
    strip.on_encoder(1)
    strip.on_encoder_press(True)
    await settle()
    assert backend.calls == []
    strip.close()


async def test_the_session_bus_is_the_one_of_the_environment(bus_address: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", bus_address)
    bus = await media._session_bus()
    assert bus.connected
    bus.disconnect()
