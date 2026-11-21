"""
The TeamSpeak 3 plugin (integrations/teamspeak), built with CMake and loaded into a fake TeamSpeak
(test/fake_teamspeak.c) that calls its callbacks like TeamSpeak does, against the daemon's `BridgeProvider`. Skipped
without cmake and a C compiler, and without TeamSpeak's plugin SDK (the first build downloads it).
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from tests.support.waiting import until
from xtouch_daemon.voip import teamspeak
from xtouch_daemon.voip.bridge import BridgeProvider
from xtouch_daemon.voip.provider import Capability, Participant

pytestmark = [
    pytest.mark.skipif(not teamspeak.can_build(), reason="needs cmake and a C compiler"),
    # a real plugin in a real process: it answers in real time
    pytest.mark.looptime(False),
]


@pytest.fixture(scope="module")
def built() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="xtd-teamspeak-") as directory:
        build = Path(directory)
        configured = subprocess.run(
            ["cmake", "-S", str(teamspeak.SOURCE_DIR), "-B", str(build), "-DXTD_TESTS=ON", "-DCMAKE_C_FLAGS=-Werror"],
            capture_output=True,
            text=True,
            check=False,
        )
        if configured.returncode != 0 and "Can't download TeamSpeak's plugin SDK" in configured.stderr:
            pytest.skip("needs TeamSpeak's plugin SDK, which the first build downloads")
        assert configured.returncode == 0, configured.stderr
        subprocess.run(["cmake", "--build", str(build)], check=True, capture_output=True)
        yield build


class FakeTeamSpeak:
    """The fake TeamSpeak with the plugin, driven line by line."""

    def __init__(self, process: asyncio.subprocess.Process):
        self.process = process

    async def line(self) -> str:
        assert self.process.stdout is not None
        return (await asyncio.wait_for(self.process.stdout.readline(), 5)).decode().strip()

    async def do(self, command: str) -> list[str]:
        """Runs a command of the script, returns what it printed."""
        assert self.process.stdin is not None
        self.process.stdin.write(command.encode() + b"\n")
        await self.process.stdin.drain()
        output: list[str] = []
        while (line := await self.line()) != "ok":
            output.append(line)
        return output

    async def collect(self, expected: list[str], seconds: float = 5) -> None:
        """Runs `record` until all it printed together is `expected`."""
        output: list[str] = []
        for _ in range(int(seconds / 0.01)):
            output += await self.do("record")
            if output == expected:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"record: {output}")


async def start(built: Path, path: Path) -> FakeTeamSpeak:
    process = await asyncio.create_subprocess_exec(
        str(built / "fake_teamspeak"),
        str(built / teamspeak.LIBRARY_NAME),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env={**os.environ, "XTOUCH_DAEMON_VOIP_SOCKET": str(path)},
    )
    host = FakeTeamSpeak(process)
    [name, version, api, number] = (await host.line()).split()[1:]
    assert (name, api, number) == ("xtouch-daemon", "api", "26")
    assert version.count(".") == 2
    assert await host.line() == "ready"
    return host


@pytest.fixture
async def setup(built: Path) -> AsyncIterator[tuple[BridgeProvider, FakeTeamSpeak]]:
    with tempfile.TemporaryDirectory(prefix="xtd-") as directory:
        path = Path(directory) / "voip.sock"
        provider = BridgeProvider(path)
        task = asyncio.create_task(provider.run())
        await until(path.exists, seconds=5)
        host = await start(built, path)
        yield provider, host
        if host.process.returncode is None:
            assert await host.do("quit") == []
            assert await host.process.wait() == 0
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def quiet(id: str, name: str, **values: object) -> Participant:
    return Participant(id, name, level=0.0, pre_fader_level=0.0, **values)  # pyright: ignore[reportArgumentType]


def names(provider: BridgeProvider) -> list[str]:
    return [each.name for each in provider.participants]


async def test_the_plugin_tells_the_channel_and_takes_the_commands(setup: tuple[BridgeProvider, FakeTeamSpeak]):
    provider, host = setup
    seen: list[Participant | None] = []
    provider.subscribe(lambda: seen.append(provider.participant("2")))
    # connected before TeamSpeak is
    await until(lambda: provider.connected, seconds=5)
    assert provider.client == "teamspeak"
    assert provider.capabilities == {Capability.VOLUME, Capability.MUTE, Capability.LEVELS}
    assert provider.participants == ()

    await host.do("connect 1 1 5")
    await host.do("user 1 2 5 Alice")
    await host.do('user 1 3 5 Bob "the builder"')
    # in another channel, and a ServerQuery client
    await host.do("user 1 4 6 Carol")
    await host.do("query 1 9 5 serveradmin")
    await until(lambda: names(provider) == ["Alice", 'Bob "the builder"'])
    assert provider.channel == "Channel 5"
    assert provider.participants[0] == quiet("2", "Alice")

    # who talks, and how loud
    await host.do("talk 1 2 1")
    assert await host.do("audio 1 2 0.5") == ["audio 0.500"]
    await until(lambda: Participant("2", "Alice", talking=True, level=0.5, pre_fader_level=0.5) in seen)
    # the level of what came since the line before
    await until(lambda: provider.participant("2") == quiet("2", "Alice", talking=True))
    await host.do("talk 1 2 0")
    await until(lambda: provider.participant("2") == quiet("2", "Alice"))

    # the fader is TeamSpeak's volume modifier, in dB
    await provider.set_volume("2", 50)
    await host.collect(["volume 1 2 -6.02 0"])
    assert provider.participant("2") == quiet("2", "Alice", volume=50)
    # TeamSpeak changes the voice after the plugin had it: the level after the volume is the plugin's sum
    assert await host.do("audio 1 2 0.8") == ["audio 0.800"]
    await provider.set_volume("3", 500)
    await host.collect(["volume 1 3 6.02 0"])
    await until(lambda: getattr(provider.participant("3"), "volume", None) == 200)
    # with the next line (nobody talks)
    assert Participant("2", "Alice", volume=50, level=0.4, pre_fader_level=0.8) in seen
    # at 0 % the plugin silences the voice itself
    await provider.set_volume("3", 0)
    await host.collect(["volume 1 3 -60.00 0"])
    assert await host.do("audio 1 3 0.5") == ["audio 0.000"]
    await until(lambda: provider.participant("3") == quiet("3", 'Bob "the builder"', volume=0))

    # Mute is TeamSpeak's Mute Client: the server sends no voice of Alice then
    await provider.set_muted("2", True)
    await until(lambda: getattr(provider.participant("2"), "muted", False))
    await host.collect(["mute 1 2 0"])
    assert await host.do("audio 1 2 0.8") == ["audio muted"]
    await provider.set_muted("2", False)
    await host.collect(["unmute 1 2 0"])
    await until(lambda: provider.participant("2") == quiet("2", "Alice", volume=50))
    # someone the plugin does not know: nothing happens
    await provider.set_muted("44", True)
    await provider.set_volume("44", 10)

    # a new nickname
    await host.do("rename 1 2 Alice2")
    await until(lambda: names(provider) == ["Alice2", 'Bob "the builder"'])
    # the volume stays while people come and go
    await host.do("user 1 4 5 Carol")
    await until(lambda: len(provider.participants) == 3)
    assert provider.participant("2") == quiet("2", "Alice2", volume=50)
    # still listed for a moment after the callback, as TeamSpeak may
    await host.do("leave 1 3")
    await until(lambda: [each.id for each in provider.participants] == ["2", "4"])
    await asyncio.sleep(0.1)
    assert [each.id for each in provider.participants] == ["2", "4"]
    # the user goes to another channel
    await host.do("user 1 1 6 me")
    await until(lambda: names(provider) == [])
    assert provider.channel == "Channel 6"
    await host.do("disconnect 1")
    await until(lambda: provider.channel is None)
    assert await host.do("record") == []


async def test_the_plugin_connects_again(built: Path):
    with tempfile.TemporaryDirectory(prefix="xtd-") as directory:
        path = Path(directory) / "voip.sock"
        host = await start(built, path)
        await host.do("connect 1 1 5")
        await host.do("user 1 2 5 Alice")
        # the daemon starts after TeamSpeak, and restarts
        for _ in range(2):
            provider = BridgeProvider(path)
            task = asyncio.create_task(provider.run())
            await until(lambda provider=provider: names(provider) == ["Alice"], seconds=6)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert await host.do("quit") == []
        assert await host.process.wait() == 0


async def test_a_mute_or_volume_set_in_teamspeak_reaches_the_strip(setup: tuple[BridgeProvider, FakeTeamSpeak]):
    provider, host = setup
    await host.do("connect 1 1 5")
    await host.do("user 1 2 5 Alice")
    # Carol comes muted and quieter (TeamSpeak remembers both for her)
    await host.do("user 1 3 6 Carol")
    await host.do("localmute 1 3 1")
    await host.do("localvolume 1 3 -12")
    await host.do("user 1 3 5 Carol")
    await until(lambda: len(provider.participants) == 2)
    assert provider.participant("3") == quiet("3", "Carol", muted=True, volume=25)

    # TeamSpeak has no event for them: the plugin reads them every POLL_MS (500 ms)
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    await host.do("localmute 1 2 1")
    await host.do("localvolume 1 2 6")
    await until(lambda: provider.participant("2") == quiet("2", "Alice", muted=True, volume=200))
    assert loop.time() - start_time < 1.5
    await host.do("localmute 1 2 0")
    await host.do("localmute 1 3 0")
    await host.do("localvolume 1 3 0")
    await until(lambda: [(each.muted, each.volume) for each in provider.participants] == [(False, 200), (False, 100)])
    # the plugin only read them
    assert await host.do("record") == []


async def test_a_mute_or_volume_teamspeak_refuses_goes_back(setup: tuple[BridgeProvider, FakeTeamSpeak]):
    provider, host = setup
    await host.do("connect 1 1 5")
    await host.do("user 1 2 5 Alice")
    await until(lambda: len(provider.participants) == 1)
    await host.do("refuse 1 2")
    await provider.set_muted("2", True)
    await host.collect(
        ["mute 1 2 512", "log 2 xtouch-daemon xtouch-daemon: can't mute Alice in TeamSpeak: invalid clientID"]
    )
    await until(lambda: provider.participant("2") == quiet("2", "Alice"))
    await provider.set_volume("2", 50)
    await host.collect(
        [
            "volume 1 2 -6.02 512",
            "log 2 xtouch-daemon xtouch-daemon: can't set the volume of Alice in TeamSpeak: invalid clientID",
        ]
    )
    await until(lambda: provider.participant("2") == quiet("2", "Alice"))
    assert await host.do("audio 1 2 0.5") == ["audio 0.500"]


async def test_the_shown_tab_and_otherwise_the_first_connected_one(setup: tuple[BridgeProvider, FakeTeamSpeak]):
    provider, host = setup
    await host.do("connect 1 1 5")
    await host.do("user 1 2 5 Alice")
    await host.do("connect 2 7 3")
    await host.do("user 2 8 3 Dave")
    await host.do("user 2 2 3 Erin")
    # the first tab is shown
    await until(lambda: names(provider) == ["Alice"])
    # a tab of its own: what happens in the other one does not count
    await host.do("talk 2 2 1")
    assert await host.do("audio 2 2 0.5") == ["audio 0.500"]
    await asyncio.sleep(0.2)
    assert provider.participant("2") == quiet("2", "Alice")

    await host.do("tab 2")
    await until(lambda: names(provider) == ["Dave", "Erin"])
    assert provider.channel == "Channel 3"
    await provider.set_muted("2", True)
    await host.collect(["mute 2 2 0"])
    # the shown tab disconnects: the first connected one
    await host.do("disconnect 2")
    await until(lambda: names(provider) == ["Alice"])
    await host.do("disconnect 1")
    await until(lambda: provider.channel is None)
    assert provider.participants == ()


async def test_the_callbacks_never_wait_for_teamspeak(setup: tuple[BridgeProvider, FakeTeamSpeak]):
    provider, host = setup
    await host.do("connect 1 1 5")
    await host.do("user 1 2 5 Alice")
    await host.do("user 1 3 5 Bob")
    await until(lambda: len(provider.participants) == 2)
    # TeamSpeak takes a second for each mute
    await host.do("slow 1000")
    await provider.set_muted("2", True)
    await provider.set_muted("3", True)
    await until(lambda: all(each.muted for each in provider.participants))
    await asyncio.sleep(0.1)
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    await host.do("talk 1 2 1")
    assert await host.do("audio 1 2 0.5") == ["audio 0.500"]
    await host.do("user 1 4 5 Carol")
    assert loop.time() - start_time < 0.5
    # the shutdown waits for the mute under way, then the thread makes no more calls (the fake would abort)
    [line] = await host.do("shutdown")
    assert int(line.split()[1]) < 1500
    assert await host.do("record") == ["mute 1 2 0"]


def test_the_build_of_the_plugin(built: Path):
    with tempfile.TemporaryDirectory(prefix="xtd-src-") as directory:
        source = Path(directory) / "teamspeak"
        shutil.copytree(teamspeak.SOURCE_DIR, source, ignore=shutil.ignore_patterns("build", "sdk"))
        # the SDK the module's build used, not a download
        sdk = next((teamspeak.SOURCE_DIR / "sdk").iterdir())
        (source / "sdk").mkdir()
        (source / "sdk" / sdk.name).symlink_to(sdk)
        library = teamspeak.build(source)
        assert library == source / "build" / teamspeak.LIBRARY_NAME
        assert library.is_file()
        # a broken source
        (source / "plugin.c").write_text("this is no C\n")
        with pytest.raises(teamspeak.TeamSpeakError, match="cmake --build failed"):
            teamspeak.build(source)
