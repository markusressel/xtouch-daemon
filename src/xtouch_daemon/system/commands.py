"""
The programs of bindings and custom channels (`set`, `watch`, `poll`, `run`): one that sets a value (or runs for a
button) and ends, one that watches it and prints a line per change, and one that prints it and ends (`output()`). They
run without a shell. The services of Home Assistant
that bindings of entities call go through here too (`call_service()`, with the connection `hass`). The tests use a
`Commands` of their own (`tests/support/commands.py`), the twin one that only watches (`SimulatedCommands`), and reads
entities but calls no services.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Coroutine, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from xtouch_daemon.homeassistant.client import HomeAssistantError

if TYPE_CHECKING:
    from xtouch_daemon.homeassistant.client import HomeAssistant

RUN_TIMEOUT = 10.0
"""Seconds a program that sets a value may take before it is killed."""


class CommandError(Exception):
    """A program could not be started, failed, or took too long."""


class Commands:
    """Runs the programs, and the tasks that own them: `wait_closed()` waits until they ended."""

    simulated = False
    """Whether nothing is set for real (Simulate): values start in the middle, so the preview is not dark."""

    def __init__(self, hass: HomeAssistant | None = None) -> None:
        self._tasks: set[asyncio.Task[None]] = set()
        self.hass = hass
        """The connection to Home Assistant, for the parts bound to its entities; None without one."""

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
        await _run(argv, RUN_TIMEOUT, output=False)

    async def output(self, argv: Sequence[str], limit: float) -> str:
        """
        Runs a program to its end and returns what it printed (a `poll`, also in Simulate: it only reads);
        CommandError if it can't start, fails, or takes longer than `limit` seconds.
        """
        return (await _run(argv, limit, output=True)).decode(errors="replace")

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

    async def call_service(self, service: str, data: Mapping[str, Any] | None, entity_id: str | None) -> None:
        """Calls a service of Home Assistant, on an entity; HomeAssistantError if it can't."""
        if self.hass is None:
            raise HomeAssistantError("no connection to Home Assistant")
        await self.hass.call_service(service, data, entity_id)


class SimulatedCommands(Commands):
    """
    Runs the `watch` and `poll` programs only, never `set` and `run`, and calls no services: for the twin, whose
    controls must not change the machine or the home. It reads the entities of `hass`, if it has one.
    """

    simulated = True

    async def run(self, argv: Sequence[str]) -> None:
        pass

    async def call_service(self, service: str, data: Mapping[str, Any] | None, entity_id: str | None) -> None:
        pass


async def _run(argv: Sequence[str], limit: float, output: bool) -> bytes:
    """Runs a program to its end, and returns what it printed if `output`; see `Commands.run()`."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE if output else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        raise CommandError(f"can't start {argv[0]}: {e.strerror or e}") from e
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), limit)
    except TimeoutError:
        raise CommandError(f"{argv[0]} took longer than {limit:g} s") from None
    finally:
        await end(process)
    if process.returncode != 0:
        lines = stderr.decode(errors="replace").strip().splitlines()
        raise CommandError(f"{argv[0]} failed ({process.returncode})" + (f": {lines[-1]}" if lines else ""))
    return stdout or b""


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
