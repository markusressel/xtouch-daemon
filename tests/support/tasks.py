"""
The tasks of the event loop of a test.
"""

import asyncio


async def finish_tasks() -> None:
    """
    Cancels the tasks a test left and waits for them, like `asyncio.run()` does at its end: meter captures still have
    to end their process.
    """
    current = asyncio.current_task()
    tasks = [task for task in asyncio.all_tasks() if task is not current]
    for task in tasks:
        task.cancel()
    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)


async def settle() -> None:
    """Lets the tasks the strips started run (commands, the fader motors)."""
    for _ in range(5):
        await asyncio.sleep(0)
