"""
The programs of bindings, run for real: small shell scripts that set nothing and print what the tests want.
"""

import asyncio
import sys

import pytest

from xtouch_daemon.system import commands as commands_module
from xtouch_daemon.system.commands import CommandError, Commands, SimulatedCommands

pytestmark = pytest.mark.looptime(False)

SH = "/bin/sh"


async def test_a_program_runs_to_its_end() -> None:
    await Commands().run([SH, "-c", "exit 0"])


async def test_a_failing_program_says_why_with_its_last_line_of_errors() -> None:
    with pytest.raises(CommandError, match=r"^/bin/sh failed \(3\): no display DP-1$"):
        await Commands().run([SH, "-c", "echo usage >&2; echo 'no display DP-1' >&2; exit 3"])
    with pytest.raises(CommandError, match=r"^/bin/sh failed \(1\)$"):
        await Commands().run([SH, "-c", "exit 1"])


async def test_a_missing_program_can_not_start() -> None:
    with pytest.raises(CommandError, match="can't start /nonexistent/brightness: No such file or directory"):
        await Commands().run(["/nonexistent/brightness", "0.5"])
    with pytest.raises(CommandError, match="can't start /nonexistent/brightness"):
        async for _ in Commands().lines(["/nonexistent/brightness", "--watch"]):
            pass  # pragma: no cover - it does not start


async def test_a_program_that_takes_too_long_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commands_module, "RUN_TIMEOUT", 0.2)
    with pytest.raises(CommandError, match=r"took longer than 0\.2 s"):
        await Commands().run([SH, "-c", "sleep 30"])


async def test_a_watch_gives_its_lines_until_it_ends() -> None:
    lines = [line async for line in Commands().lines([SH, "-c", "echo 0.60; echo ' 0.70 '"])]
    assert lines == ["0.60", "0.70"]


async def test_a_watch_that_is_cancelled_is_killed_and_waited_for() -> None:
    commands = Commands()
    seen = asyncio.Event()

    async def watch() -> None:
        async for _ in commands.lines([SH, "-c", "echo 0.5; exec sleep 30"]):
            seen.set()

    task = commands.start(watch(), "watch")
    await asyncio.wait_for(seen.wait(), 5)
    task.cancel()
    await commands.wait_closed()
    assert task.cancelled()


async def test_the_twin_watches_but_sets_nothing() -> None:
    commands = SimulatedCommands()
    assert commands.simulated
    assert not Commands().simulated
    # a program that would fail if it ran
    await commands.run([sys.executable, "-c", "raise SystemExit(1)"])
    assert [line async for line in commands.lines([SH, "-c", "echo 0.5"])] == ["0.5"]
