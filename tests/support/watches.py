"""
Programs of your own run by nobody, with a `watch` or a `poll` each: `ProgramCommands` prints a line to the watches of
one program, and a text for the polls of one, so a test can feed a strip with several (its color, its LEDs, its
presence, a target each).
"""

import asyncio
import shlex
from collections.abc import AsyncIterator, Sequence

from tests.support.commands import FakeCommands
from xtouch_daemon.system.commands import CommandError


class ProgramCommands(FakeCommands):
    """
    `FakeCommands` whose watches print what `print_to()` feeds their program (by its command line). A line fed before
    the watch starts waits for it. A poll prints what `polled` has for its program, else nothing.
    """

    def __init__(self) -> None:
        super().__init__()
        self._queues: dict[str, asyncio.Queue[str | None]] = {}
        self.polled: dict[str, str] = {}
        """What each poll program (by its command line) prints."""

    def _queue(self, program: str) -> asyncio.Queue[str | None]:
        return self._queues.setdefault(program, asyncio.Queue())

    def print_to(self, program: str, line: str | None) -> None:
        """A line the `watch` program `program` (e.g. `"color --watch"`) prints; None: it ends."""
        self._queue(program).put_nowait(line)

    def watching(self, program: str) -> int:
        """How often the program was started as a watch."""
        return sum(1 for argv in self.watches if shlex.join(argv) == program)

    async def lines(self, argv: Sequence[str]) -> AsyncIterator[str]:
        self.watches.append(list(argv))
        if self.unstartable:
            raise CommandError(f"can't start {argv[0]}: No such file or directory")
        queue = self._queue(shlex.join(argv))
        while (line := await queue.get()) is not None:
            yield line

    def polling(self, program: str) -> int:
        """How often the program ran as a poll."""
        return sum(1 for argv, _ in self.polls if shlex.join(argv) == program)

    async def output(self, argv: Sequence[str], limit: float) -> str:
        await super().output(argv, limit)
        return self.polled.get(shlex.join(argv), "")
