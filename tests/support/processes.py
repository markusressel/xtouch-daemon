"""
The processes the tests started.
"""

import contextlib
from pathlib import Path


def child_processes() -> set[int]:
    """The processes this one started that are not waited for yet: running, or ended (zombies)."""
    children: set[int] = set()
    for thread in Path("/proc/self/task").iterdir():
        # a thread may end meanwhile
        with contextlib.suppress(FileNotFoundError):
            children.update(int(pid) for pid in (thread / "children").read_text().split())
    return children
