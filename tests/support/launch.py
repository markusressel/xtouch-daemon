"""
Starting applications in the tests: a launcher that records them.
"""

from xtouch_daemon.system.launch import Launcher


class FakeLauncher(Launcher):
    """Records the commands it launches instead of starting them; `missing` programs are not there."""

    def __init__(self, user_manager: bool = True) -> None:
        self.spawned: list[list[str]] = []
        self.missing: set[str] = set()
        super().__init__(self.spawned.append, self.which, lambda: user_manager)

    def which(self, program: str) -> str | None:
        return None if program in self.missing else f"/usr/bin/{program}"
