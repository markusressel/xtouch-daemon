"""
A running daemon for the tests, which records its reloads.
"""

from dataclasses import dataclass, field

from xtouch_daemon.system.instance import Instance


@dataclass(frozen=True)
class RecordingInstance(Instance):
    """A daemon that records its reloads instead of getting a signal (or fails like one that ended a moment ago)."""

    reloads: list[int] = field(default_factory=list, compare=False)
    gone: bool = False

    def reload(self) -> None:
        if self.gone:
            raise ProcessLookupError(3, "No such process")
        self.reloads.append(self.pid)
