"""
`xtouch-daemon test` while the daemon runs: the daemon has the device, so it runs the test (`StartTest`), and the
command keeps it alive until Ctrl+C or until the daemon ends it.
"""

import asyncio
import contextlib
from collections.abc import Callable
from pathlib import Path

from xtouch_daemon.live.codec import decode_message, encode_request
from xtouch_daemon.live.messages import EndTest, KeepTest, Reply, Request, StartTest

HEARTBEAT = 3.0
"""How often the command tells the daemon that it is still there (`daemon.TEST_TIMEOUT` is 10 s)."""
LINE_LIMIT = 1 << 20
"""The longest line the command reads: a snapshot of the daemon has a few KB."""


class TestRefused(Exception):
    """The daemon did not start the test (e.g. the device is not connected)."""

    __test__ = False
    """Not a test class of pytest, despite its name."""


async def run_test_in_daemon(socket: Path, echo: Callable[[str], None], heartbeat: float = HEARTBEAT) -> None:
    """
    Asks the daemon at `socket` (its live view) to test the device, and keeps the test alive until the daemon ends it
    (`echo` says why) or this is cancelled (Ctrl+C), which ends it. TestRefused if the daemon does not start it.
    """
    reader, writer = await asyncio.open_unix_connection(str(socket), limit=LINE_LIMIT)

    def send(request: Request) -> None:
        writer.write(encode_request(request))

    async def keep() -> None:
        while True:
            await asyncio.sleep(heartbeat)
            send(KeepTest())

    send(StartTest())
    keeper = asyncio.create_task(keep(), name="test heartbeat")
    try:
        while line := await reader.readline():
            match decode_message(line):
                case Reply(kind="test", ok=False, message=message):
                    raise TestRefused(message)
                case Reply(kind="test", ok=True):
                    echo("The daemon tests the device now: every strip answers its controls. Ctrl+C ends the test.")
                case Reply(kind="test_ended", message=message):
                    echo(f"The test ended: {message}.")
                    return
                case _:
                    # snapshots, and news of other requests
                    pass
        echo("The test ended: the daemon went away.")
    finally:
        keeper.cancel()
        if not writer.is_closing():
            send(EndTest())
            with contextlib.suppress(OSError, TimeoutError):
                await asyncio.wait_for(writer.drain(), 1.0)
        writer.close()
