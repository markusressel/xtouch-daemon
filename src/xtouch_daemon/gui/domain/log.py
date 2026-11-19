"""
The log of the daemon in the window Log: the records it sent (see `live.WatchLog`), which of them show at a level, and
where a search matches.
"""

import logging
from collections import deque
from datetime import datetime

from xtouch_daemon.live.messages import LogEntry, LogLines

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
"""The levels the window filters by: it shows the records of the level picked and above."""

MAX_ENTRIES = 5000
"""How many records the window keeps; older ones go."""

MAX_MATCHES = 1000
"""How many matches of a search are marked: more are counted, but not drawn."""


def severity(level: str) -> int:
    """The number of a level (`logging.INFO`, ...); a level of its own counts as INFO."""
    number = logging.getLevelNamesMapping().get(level)
    return number if number is not None else logging.INFO


def shown(entry: LogEntry, level: str) -> bool:
    """Whether the window shows `entry` with `level` picked: it is of that level or above."""
    return severity(entry.level) >= severity(level)


def line(entry: LogEntry) -> str:
    """A record as the window shows it, like the terminal does: `12:30:01 WARNING xtouch_daemon.mqtt: ...`."""
    time = datetime.fromtimestamp(entry.time).strftime("%H:%M:%S")
    return f"{time} {entry.level:<7} {entry.logger}: {entry.message}"


def matches(text: str, search: str) -> list[tuple[int, int]]:
    """Where `search` is in `text` (start and length), ignoring case; none for an empty search."""
    if not search:
        return []
    haystack, needle = text.casefold(), search.casefold()
    found: list[tuple[int, int]] = []
    start = haystack.find(needle)
    while start >= 0:
        found.append((start, len(needle)))
        start = haystack.find(needle, start + len(needle))
    return found


class LogHistory:
    """The records the window got from the daemon, the latest `MAX_ENTRIES`."""

    def __init__(self, size: int = MAX_ENTRIES):
        self.entries: deque[LogEntry] = deque(maxlen=size)

    def take(self, lines: LogLines) -> None:
        """
        Takes the records of `lines`. A backlog starts over: the daemon sends what it kept to a new watch, also after a
        restart, which counts its records from 1 again.
        """
        if lines.backlog:
            self.entries.clear()
        self.entries.extend(lines.entries)

    def shown(self, level: str) -> list[LogEntry]:
        """The records the window shows with `level` picked, oldest first."""
        return [entry for entry in self.entries if shown(entry, level)]
