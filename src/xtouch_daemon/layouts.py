"""
Switching between the layouts of the configuration (`[[layout]]`): by hand (the command line, the GUI, Home Assistant,
a chord on the device) and by rules (an application has a stream, a process runs).

The rules are edge-triggered: they switch when the layout they want changes, so a layout chosen by hand stays until
something happens (an application starts or ends), as Stream Deck and Loupedeck do with the application in focus. A
layout whose rule stopped matching stays for `switching.hold` seconds.
"""

import logging
import time
from collections.abc import Callable, Collection
from pathlib import Path

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import DEFAULT_LAYOUT, Config, LayoutConfig

_LOGGER = logging.getLogger(__name__)

PROC = Path("/proc")

MANUAL = "manual"
"""The reason of a switch by hand (the command line, the GUI)."""

type SwitchHandler = Callable[[str, str], None]
"""Called with the name of the layout that comes, and why (e.g. "manual", or the application of a rule)."""


def running_processes(proc: Path | None = None) -> frozenset[str]:
    """
    The names of the processes that run, in lower case: the name the kernel keeps (`comm`, at most 15 characters)
    and the file name of the program they were started as. `proc` is PROC by default.
    """
    names: set[str] = set()
    for entry in (proc or PROC).iterdir():
        if not entry.name.isdigit():
            continue
        try:
            names.add((entry / "comm").read_text(encoding="utf-8", errors="replace").strip().lower())
            program = (entry / "cmdline").read_bytes().split(b"\0", 1)[0]
        except OSError:
            # it ended in the meantime, or belongs to someone else
            continue
        if program:
            names.add(Path(program.decode(errors="replace")).name.lower())
    names.discard("")
    return frozenset(names)


def remembered_layout(path: Path) -> str | None:
    """The layout kept by `remember_layout()`, None if there is none (or it can't be read)."""
    try:
        name = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as e:
        _LOGGER.warning(f"Can't read the layout of the last run from {path}: {e}")
        return None
    return name or None


def remember_layout(path: Path, name: str) -> None:
    """Keeps the name of a layout for the next start, in a file of its own. A file that can't be written is logged."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # whole or not at all: a daemon that is killed while it writes leaves the old one
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(f"{name}\n", encoding="utf-8")
        temporary.replace(path)
    except OSError as e:
        _LOGGER.warning(f"Can't keep the layout for the next start in {path}: {e}")


def process_matching(patterns: Collection[str], processes: Collection[str]) -> str | None:
    """A process whose name contains one of the patterns (tried in order, ignoring case); None for none."""
    for pattern in patterns:
        process = next((name for name in sorted(processes) if pattern.lower() in name), None)
        if process is not None:
            return process
    return None


def rule_match(layout: LayoutConfig, state: AudioState, processes: Collection[str]) -> str | None:
    """What makes the rules of the layout match (an application, a process), None while nothing does."""
    if layout.apps:
        stream = next(iter(state.streams_matching(layout.apps)), None)
        if stream is not None:
            return stream.app or stream.binary
    return process_matching(layout.processes, processes)


class LayoutSwitcher:
    """
    Which layout is active, and switching between them: `switch()` and `step()` by hand, `evaluate()` by the rules.
    `on_switch` carries a switch out.
    """

    def __init__(
        self,
        config: Config,
        on_switch: SwitchHandler,
        active: str = DEFAULT_LAYOUT,
        clock: Callable[[], float] = time.monotonic,
    ):
        """`active` is the layout the device shows already (e.g. before a reload); the default one if it is gone."""
        self.config = config
        self.on_switch = on_switch
        self.clock = clock
        self.active = active if active in config.layout_names else DEFAULT_LAYOUT
        self.wanted = DEFAULT_LAYOUT
        """The layout the rules want, the last time they were evaluated."""
        self._matched: dict[str, tuple[float, str]] = {}
        """When the rules of each layout matched last, and what matched."""
        self.by_rule = False
        """
        Whether a rule put the active layout there: not a choice by hand, nor the default layout the rules went back
        to when none matched anymore.
        """

    @property
    def names(self) -> tuple[str, ...]:
        return self.config.layout_names

    @property
    def has_rules(self) -> bool:
        return any(layout.has_rules for layout in self.config.layouts)

    @property
    def watches_processes(self) -> bool:
        return any(layout.processes for layout in self.config.layouts)

    def switch(self, name: str, reason: str = MANUAL, by_rule: bool = False) -> bool:
        """
        Switches to the layout (KeyError for one that is not there); False if it is the active one already. `by_rule`:
        a rule matched for it (see `by_rule`).
        """
        if name not in self.names:
            raise KeyError(name)
        if name == self.active:
            return False
        _LOGGER.info(f"Layout {name} ({reason})" if reason else f"Layout {name}")
        self.active = name
        self.by_rule = by_rule
        self.on_switch(name, reason)
        return True

    def step(self, by: int, reason: str = MANUAL) -> bool:
        """Switches to the next (`by` 1) or previous (-1) layout in the order of the file, wrapping around."""
        names = self.names
        return self.switch(names[(names.index(self.active) + by) % len(names)], reason)

    def evaluate(self, state: AudioState, processes: Collection[str] = ()) -> None:
        """Lets the rules switch if the layout they want changed."""
        now = self.clock()
        for layout in self.config.layouts:
            match = rule_match(layout, state, processes)
            if match is not None:
                self._matched[layout.name] = (now, match)
        hold = self.config.switching.hold
        candidates = [
            (layout.priority, -index, layout.name)
            for index, layout in enumerate(self.config.layouts)
            if layout.name in self._matched and now - self._matched[layout.name][0] <= hold
        ]
        wanted = max(candidates)[2] if candidates else DEFAULT_LAYOUT
        if wanted == self.wanted:
            return
        self.wanted = wanted
        self.switch(
            wanted, self._matched[wanted][1] if wanted in self._matched else "", by_rule=wanted in self._matched
        )
