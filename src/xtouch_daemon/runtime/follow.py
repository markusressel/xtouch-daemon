"""The loop that steps slots over time, for the daemon and for a virtual twin (see `runtime.twin`)."""

import asyncio
import contextlib
import time
from collections.abc import Callable


async def follow_slots(
    wake: asyncio.Event,
    deadline: Callable[[], float | None],
    step: Callable[[], None],
    interval: float,
    batch: float,
    ready: Callable[[], bool] = lambda: True,
) -> None:
    """
    Calls `step` `batch` seconds after `wake` was set (what comes together goes together: a game starts several
    streams and a process), when a delay or a dwell ends (`deadline`, a `time.monotonic()` time), and every
    `interval` seconds (the processes), while `ready()`.
    """
    while True:
        timeout = interval
        if (due := deadline()) is not None:
            timeout = min(timeout, max(0.0, due - time.monotonic()))
        with contextlib.suppress(TimeoutError):
            # at least a moment: a deadline that is due must not keep the others from their turn
            await asyncio.wait_for(wake.wait(), max(timeout, 0.001))
        if wake.is_set():
            await asyncio.sleep(batch)
            wake.clear()
        if ready():
            step()
