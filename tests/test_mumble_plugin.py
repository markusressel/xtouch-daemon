"""
The Mumble plugin (integrations/mumble), built with CMake and loaded into a fake Mumble (test/fake_mumble.c) that
calls its callbacks like Mumble does, against the daemon's `BridgeProvider`. Skipped without cmake and a C compiler.
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from xtouch_daemon import mumble
from xtouch_daemon.voip.bridge import BridgeProvider
from xtouch_daemon.voip.provider import Capability, Participant

pytestmark = [
    pytest.mark.skipif(not mumble.can_build(), reason="needs cmake and a C compiler"),
    # a real plugin in a real process: it answers in real time
    pytest.mark.looptime(False),
]


@pytest.fixture(scope="module")
def built() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="xtd-mumble-") as directory:
        build = Path(directory)
        for command in (
            ["cmake", "-S", str(mumble.SOURCE_DIR), "-B", str(build), "-DXTD_TESTS=ON"],
            ["cmake", "--build", str(build)],
        ):
            subprocess.run(command, check=True, capture_output=True)
        yield build


class FakeMumble:
    """The fake Mumble with the plugin, driven line by line."""

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

    async def collect(self, command: str, expected: list[str], seconds: float = 5) -> None:
        """Runs a command until all it printed together is `expected`."""
        output: list[str] = []
        for _ in range(int(seconds / 0.01)):
            output += await self.do(command)
            if output == expected:
                return
            if command != "record":
                output = []
            await asyncio.sleep(0.01)
        raise AssertionError(f"{command}: {output}")


@pytest.fixture
async def setup(built: Path) -> AsyncIterator[tuple[BridgeProvider, FakeMumble]]:
    with tempfile.TemporaryDirectory(prefix="xtd-") as directory:
        path = Path(directory) / "voip.sock"
        provider = BridgeProvider(path)
        task = asyncio.create_task(provider.run())
        await until(path.exists)
        process = await asyncio.create_subprocess_exec(
            str(built / "fake_mumble"),
            str(built / mumble.LIBRARY_NAME),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={**os.environ, "XTOUCH_DAEMON_VOIP_SOCKET": str(path)},
        )
        host = FakeMumble(process)
        assert await host.line() == "plugin xtouch-daemon api 1.0.0 features 2"
        assert await host.line() == "ready"
        yield provider, host
        if process.returncode is None:
            assert await host.do("quit") == []
            assert await process.wait() == 0
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def until(condition: object, seconds: float = 5) -> None:
    for _ in range(int(seconds / 0.01)):
        if callable(condition) and condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("never happened")


def test_the_bundle_has_the_manifest_and_the_library_only(built: Path):
    with zipfile.ZipFile(built / mumble.BUNDLE_NAME) as bundle:
        assert sorted(bundle.namelist()) == ["libxtouch-daemon.so", "manifest.xml"]
        manifest = bundle.read("manifest.xml").decode()
    assert '<plugin os="linux" arch="x64">libxtouch-daemon.so</plugin>' in manifest
    assert "<name>xtouch-daemon</name>" in manifest


async def test_the_plugin_tells_the_channel_and_takes_the_commands(setup: tuple[BridgeProvider, FakeMumble]):
    provider, host = setup
    seen: list[Participant | None] = []
    provider.subscribe(lambda: seen.append(provider.participant("2")))
    # connected before anyone is there
    await until(lambda: provider.connected)
    assert provider.client == "mumble"
    assert provider.capabilities == {Capability.VOLUME, Capability.MUTE, Capability.LEVELS}
    assert provider.participants == ()

    await host.do("connect 1 5")
    await host.do("user 2 5 Alice")
    await host.do('user 3 5 Bob "the builder"')
    # in another channel
    await host.do("user 4 6 Carol")
    await until(lambda: [each.name for each in provider.participants] == ["Alice", 'Bob "the builder"'])
    assert provider.channel == "Channel 5"
    assert provider.participants[0] == Participant("2", "Alice", level=0.0)

    # who talks, and how loud
    await host.do("talk 2 1")
    assert await host.do("audio 2 0.5") == ["audio 0 0.500"]
    await until(lambda: Participant("2", "Alice", talking=True, level=0.5) in seen)
    # the level of what came since the line before
    await until(lambda: provider.participant("2") == Participant("2", "Alice", talking=True, level=0.0))
    await host.do("talk 2 0")
    await until(lambda: provider.participant("2") == Participant("2", "Alice", level=0.0))

    # the fader and Mute
    await provider.set_volume("2", 50)
    await until(lambda: getattr(provider.participant("2"), "volume", None) == 50)
    assert await host.do("audio 2 0.8") == ["audio 1 0.400"]
    await provider.set_volume("3", 500)
    await until(lambda: getattr(provider.participant("3"), "volume", None) == 200)
    # Mute is Mumble's local mute: Mumble fetches no audio of Alice then
    await provider.set_muted("2", True)
    await until(lambda: getattr(provider.participant("2"), "muted", False))
    assert await host.do("record") == ["requestLocalMute 2 1 0"]
    assert await host.do("audio 2 0.8") == ["audio muted"]
    # she talks, muted
    await host.do("talk 2 4")
    await until(lambda: getattr(provider.participant("2"), "talking", False))
    await host.do("talk 2 0")
    # someone the plugin does not know: nothing changes
    await provider.set_muted("9", True)
    assert await host.do("audio 9 0.8") == ["audio 0 0.800"]

    # the volume stays while people come and go
    await host.do("user 4 5 Carol")
    await until(lambda: len(provider.participants) == 3)
    assert provider.participant("2") == Participant("2", "Alice", muted=True, volume=50, level=0.0)
    await host.do("leave 3")
    await until(lambda: [each.id for each in provider.participants] == ["2", "4"])
    # the user goes to another channel
    await host.do("user 1 6 me")
    await until(lambda: [each.name for each in provider.participants] == [])
    await host.do("disconnect")
    await until(lambda: provider.channel is None)


async def test_the_plugin_connects_again(built: Path):
    with tempfile.TemporaryDirectory(prefix="xtd-") as directory:
        path = Path(directory) / "voip.sock"
        process = await asyncio.create_subprocess_exec(
            str(built / "fake_mumble"),
            str(built / mumble.LIBRARY_NAME),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={**os.environ, "XTOUCH_DAEMON_VOIP_SOCKET": str(path)},
        )
        host = FakeMumble(process)
        await host.line()
        await host.line()
        await host.do("connect 1 5")
        await host.do("user 2 5 Alice")
        # the daemon starts after Mumble, and restarts
        for _ in range(2):
            provider = BridgeProvider(path)
            task = asyncio.create_task(provider.run())
            await until(lambda provider=provider: [each.name for each in provider.participants] == ["Alice"], seconds=6)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert await host.do("quit") == []
        assert await process.wait() == 0


async def test_a_mute_set_in_mumble_lights_the_button(setup: tuple[BridgeProvider, FakeMumble]):
    provider, host = setup
    await host.do("connect 1 5")
    await host.do("user 2 5 Alice")
    # Carol comes muted (Mumble remembers the local mute of registered users)
    await host.do("user 3 6 Carol")
    await host.do("localmute 3 1")
    await host.do("user 3 5 Carol")
    await until(lambda: len(provider.participants) == 2)
    assert provider.participant("3") == Participant("3", "Carol", muted=True, level=0.0)

    # Mumble has no event for it: the plugin reads it every POLL_MS (500 ms)
    loop = asyncio.get_running_loop()
    start = loop.time()
    await host.do("localmute 2 1")
    await until(lambda: getattr(provider.participant("2"), "muted", False))
    assert loop.time() - start < 1.5
    await host.do("localmute 2 0")
    await host.do("localmute 3 0")
    await until(lambda: [each.muted for each in provider.participants] == [False, False])
    # the plugin only read it
    assert await host.do("record") == []


async def test_a_mute_mumble_refuses_goes_back(setup: tuple[BridgeProvider, FakeMumble]):
    provider, host = setup
    await host.do("connect 1 5")
    await host.do("user 2 5 Alice")
    await until(lambda: len(provider.participants) == 1)
    await host.do("refuse 2")
    await provider.set_muted("2", True)

    await host.collect(
        "record", ["requestLocalMute 2 1 -1", "log xtouch-daemon: can't mute Alice in Mumble: Generic error"]
    )
    await until(lambda: provider.participant("2") == Participant("2", "Alice", level=0.0))
    assert await host.do("audio 2 0.5") == ["audio 0 0.500"]


async def test_the_plugin_shuts_down_with_a_mute_under_way(setup: tuple[BridgeProvider, FakeMumble]):
    provider, host = setup
    await host.do("connect 1 5")
    await host.do("user 2 5 Alice")
    await until(lambda: len(provider.participants) == 1)
    # Mumble's main thread is busy: the request waits for it
    await host.do("pause")
    await provider.set_muted("2", True)
    await until(lambda: getattr(provider.participant("2"), "muted", False))
    await host.collect("queued", ["queued requestLocalMute 2 1"])
    # mumble_shutdown waits for the call, which can't run while it waits: Mumble gives up on it after 800 ms; the
    # plugin makes no call after that (the fake would abort)
    [line] = await host.do("shutdown")
    assert line.startswith("shutdown ")
    assert 700 <= int(line.split()[1]) < 1500
    assert await host.do("record") == ["requestLocalMute 2 1 timeout"]
    assert await host.do("quit") == []
    assert await host.process.wait() == 0


async def test_a_shutdown_drops_the_requests_that_did_not_start(setup: tuple[BridgeProvider, FakeMumble]):
    provider, host = setup
    await host.do("connect 1 5")
    await host.do("user 2 5 Alice")
    await host.do("user 3 5 Bob")
    await until(lambda: len(provider.participants) == 2)
    await host.do("pause")
    await provider.set_muted("2", True)
    await provider.set_muted("3", True)
    await until(lambda: all(each.muted for each in provider.participants))
    await host.collect("queued", ["queued requestLocalMute 2 1"])
    [line] = await host.do("shutdown")
    assert int(line.split()[1]) < 1500
    # Bob's request never started
    assert await host.do("record") == ["requestLocalMute 2 1 timeout"]


def test_the_build_of_the_bundle():
    with tempfile.TemporaryDirectory(prefix="xtd-src-") as directory:
        source = Path(directory) / "mumble"
        shutil.copytree(mumble.SOURCE_DIR, source, ignore=shutil.ignore_patterns("build"))
        bundle = mumble.build(source)
        assert bundle == source / "build" / mumble.BUNDLE_NAME
        assert bundle.is_file()
        # a broken source
        (source / "plugin.c").write_text("this is no C\n")
        with pytest.raises(mumble.MumbleError, match="cmake --build failed"):
            mumble.build(source)
