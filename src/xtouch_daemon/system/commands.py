"""
The programs of bindings and custom channels (`set`, `watch`, `run`): one that sets a value (or runs for a button) and
ends, and one that watches it and prints a line per change. They run without a shell. The tests use a `Commands` of
their own (`tests/support/commands.py`), the twin one that only watches (`SimulatedCommands`).
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Coroutine, Sequence
from typing import Any

RUN_TIMEOUT = 10.0
"""Seconds a program that sets a value may take before it is killed."""


class CommandError(Exception):
    """A program could not be started, failed, or took too long."""


class Commands:
    """Runs the programs, and the tasks that own them: `wait_closed()` waits until they ended."""

    simulated = False
    """Whether nothing is set for real (Simulate): values start in the middle, so the preview is not dark."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, coroutine: Coroutine[Any, Any, None], name: str) -> asyncio.Task[None]:
        """A task that runs programs; it is waited for by `wait_closed()`."""
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def wait_closed(self) -> None:
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def run(self, argv: Sequence[str]) -> None:
        """Runs a program to its end; CommandError if it can't start, fails, or takes longer than RUN_TIMEOUT."""
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            raise CommandError(f"can't start {argv[0]}: {e.strerror or e}") from e
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), RUN_TIMEOUT)
        except TimeoutError:
            raise CommandError(f"{argv[0]} took longer than {RUN_TIMEOUT:g} s") from None
        finally:
            await end(process)
        if process.returncode != 0:
            lines = stderr.decode(errors="replace").strip().splitlines()
            raise CommandError(f"{argv[0]} failed ({process.returncode})" + (f": {lines[-1]}" if lines else ""))

    async def lines(self, argv: Sequence[str]) -> AsyncIterator[str]:
        """The lines a program prints, until it ends; CommandError if it can't start."""
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as e:
            raise CommandError(f"can't start {argv[0]}: {e.strerror or e}") from e
        assert process.stdout is not None
        try:
            while line := await process.stdout.readline():
                yield line.decode(errors="replace").strip()
        finally:
            await end(process)


class SimulatedCommands(Commands):
    """Runs the `watch` programs only, never `set`: for the twin, whose controls must not change the machine."""

    simulated = True

    async def run(self, argv: Sequence[str]) -> None:
        pass


async def end(process: asyncio.subprocess.Process) -> None:
    """
    Kills the program if it still runs and waits for it, also when the task is cancelled again meanwhile: otherwise
    the process is never waited for.
    """
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    cancelled = False
    while True:
        try:
            await process.wait()
        except asyncio.CancelledError:
            # killed, so the wait is short
            cancelled = True
        else:
            break
    if cancelled:
        raise asyncio.CancelledError
