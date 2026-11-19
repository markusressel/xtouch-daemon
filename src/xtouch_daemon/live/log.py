"""
The log of the daemon for the GUI (see `WatchLog`): the latest records in memory, whether the daemon runs as a
service or in a terminal, and a signal for every new one while a client watches. Nobody watching, a record costs its
message and a place in a deque.
"""

import logging
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from xtouch_daemon.live.messages import LogEntry

LOG_SIZE = 1000
"""How many records the daemon keeps for a client that starts to watch (about 150 KB)."""


class LogBuffer(logging.Handler):
    """
    The latest `size` records of the loggers it is attached to (see `attached()`): the same ones the terminal or the
    journal get, at the level the daemon runs with (`--log-level`).
    """

    def __init__(self, size: int = LOG_SIZE):
        super().__init__()
        self.setFormatter(logging.Formatter("%(message)s"))
        self.entries: deque[LogEntry] = deque(maxlen=size)
        self.last = 0
        """The `seq` of the latest record, 0 before the first."""
        self.on_entry: Callable[[], None] | None = None
        """
        Called after every record while a client watches (see `LiveServer`), in the thread that logged it: other
        threads log too (e.g. `system.launch`).
        """

    def emit(self, record: logging.LogRecord) -> None:
        # with the lock of the handler (`Handler.handle()`): one record at a time
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return
        self.last += 1
        self.entries.append(LogEntry(self.last, record.created, record.levelname, record.name, message))
        if (on_entry := self.on_entry) is not None:
            on_entry()

    def since(self, seq: int) -> tuple[LogEntry, ...]:
        """The records after `seq` that it still keeps, oldest first; all of them for 0."""
        with self._locked():
            return tuple(entry for entry in self.entries if entry.seq > seq)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        # the deque must not change while it is read: another thread may log meanwhile
        self.acquire()
        try:
            yield
        finally:
            self.release()

    @contextmanager
    def attached(self, logger: logging.Logger | None = None) -> Iterator[LogBuffer]:
        """Keeps the records of `logger` (the root logger: all of them) while in the block."""
        target = logger or logging.getLogger()
        target.addHandler(self)
        try:
            yield self
        finally:
            target.removeHandler(self)
