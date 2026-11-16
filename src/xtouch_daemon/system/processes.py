"""
The processes that run, by name, for the layout rules (`processes`) and the strips that start an application
(`launch_when_running`).
"""

from collections.abc import Collection
from pathlib import Path

PROC = Path("/proc")


def running_processes(proc: Path | None = None) -> frozenset[str]:
    """
    The names of the processes that run, in lower case: the name the kernel keeps (`comm`, at most 15 characters)
    and the file name of the program they were started as. `proc` is PROC by default. Kernel threads (no command
    line) are left out: their names would match rules by accident, e.g. "oom_reaper" for "reaper" (Steam's).
    """
    names: set[str] = set()
    for entry in (proc or PROC).iterdir():
        if not entry.name.isdigit():
            continue
        try:
            program = (entry / "cmdline").read_bytes().split(b"\0", 1)[0]
            if not program:
                # a kernel thread, or a process that is ending
                continue
            names.add((entry / "comm").read_text(encoding="utf-8", errors="replace").strip().lower())
        except OSError:
            # it ended in the meantime, or belongs to someone else
            continue
        names.add(Path(program.decode(errors="replace")).name.lower())
    names.discard("")
    return frozenset(names)


def process_matching(patterns: Collection[str], processes: Collection[str]) -> str | None:
    """A process whose name contains one of the patterns (tried in order, ignoring case); None for none."""
    for pattern in patterns:
        process = next((name for name in sorted(processes) if pattern.lower() in name), None)
        if process is not None:
            return process
    return None
