"""Waiting in a test for something that happens on the event loop."""

import asyncio
from collections.abc import Callable

STEP = 0.002
"""How often the condition is checked."""


async def until(condition: Callable[[], object], seconds: float = 2.0) -> None:
    """Waits until `condition` holds; AssertionError if it doesn't within `seconds`."""
    for _ in range(round(seconds / STEP)):
        if condition():
            return
        await asyncio.sleep(STEP)
    raise AssertionError("waited in vain")
