"""
The programs of bindings, run by nobody: `FakeCommands` records what it would run and prints what a test feeds
it as the lines of a `watch`, or as what a `poll` prints.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence

from xtouch_daemon.system.commands import CommandError, Commands

END = None
"""Fed to `FakeCommands.print()`: the `watch` program ends."""


class FakeCommands(Commands):
    """
    Records each run (`runs`); a run takes `run_time` seconds (virtual), and fails while `failing` says why. A `watch`
    prints what `print()` feeds it, and can't start while `unstartable`. A `poll` (`polls`, with the time it started)
    prints `printed` after `poll_time` seconds, fails while `failing` says why, and is stopped after its limit.
    """

    def __init__(self) -> None:
        super().__init__()
        self.runs: list[list[str]] = []
        self.run_time = 0.0
        self.failing: str | None = None
        self.unstartable = False
        self.watches: list[list[str]] = []
        """The `watch` programs started so far."""
        self._lines: asyncio.Queue[str | None] = asyncio.Queue()
        self.polls: list[tuple[list[str], float]] = []
        """The `poll` programs run so far, each with the (virtual) time it started."""
        self.printed = ""
        self.poll_time = 0.0

    async def run(self, argv: Sequence[str]) -> None:
        self.runs.append(list(argv))
        await asyncio.sleep(self.run_time)
        if self.failing is not None:
            raise CommandError(self.failing)

    def print(self, line: str | None) -> None:
        """A line the `watch` program prints; END: it ends."""
        self._lines.put_nowait(line)

    async def lines(self, argv: Sequence[str]) -> AsyncIterator[str]:
        self.watches.append(list(argv))
        if self.unstartable:
            raise CommandError(f"can't start {argv[0]}: No such file or directory")
        while (line := await self._lines.get()) is not None:
            yield line

    async def output(self, argv: Sequence[str], limit: float) -> str:
        self.polls.append((list(argv), asyncio.get_running_loop().time()))
        await asyncio.sleep(min(self.poll_time, limit))
        if self.poll_time > limit:
            raise CommandError(f"{argv[0]} took longer than {limit:g} s")
        if self.failing is not None:
            raise CommandError(self.failing)
        return self.printed
