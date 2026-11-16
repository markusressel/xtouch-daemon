"""
Which strip of the configuration each strip of the device shows: the strips are a flow in the order of the
configuration, and the device shows the first 8 of them that take a place. A strip with `collapse` takes none while it
has nothing to control (after `behavior.collapse_hold`), so the strips after it move one place to the left.
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.strip import Strip, VirtualStrip

_LOGGER = logging.getLogger(__name__)

type Placement = tuple[int | None, ...]
"""
For each strip of the device, the strip of the configuration it shows (its index in `Config.all_strips()`), None for
none.
"""


def place(collapse: Sequence[bool], absent: Sequence[bool], count: int = protocol.STRIPS) -> Placement:
    """
    The first `count` strips of the flow that take a place: all but those that collapse and are absent. The strips of
    the device that are left over show none.
    """
    shown = [index for index, (folds, gone) in enumerate(zip(collapse, absent, strict=True)) if not (folds and gone)]
    shown = shown[:count]
    return (*shown, *[None] * (count - len(shown)))


@dataclass
class _Absence:
    """Whether a strip has had nothing to control, since when, and whether it collapsed for that."""

    since: float | None = None
    """When it became absent (`time.monotonic()`), None while it is present."""
    collapsed: bool = False
    """Whether its hold time is over (or it was absent when the strips were placed from scratch)."""


class Flow:
    """
    Puts the strips of the configuration (`strips`, each drawing on its `VirtualStrip`) on the strips of the device.
    `update()` is given which of them are absent after every change; a strip collapses once it has been absent for
    `hold` seconds and comes back at once. Nothing moves while `update()` is told that the device is busy (a finger on
    a fader, a button held): the move waits until it is let go.
    """

    def __init__(
        self,
        strips: Sequence[VirtualStrip],
        device: Sequence[Strip],
        collapse: Sequence[bool],
        titles: Callable[[int], str],
        hold: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        """`titles` names a strip of the configuration for the log."""
        self.strips = list(strips)
        self.device = list(device)
        self.collapse = tuple(collapse)
        self.titles = titles
        self.hold = hold
        self.clock = clock
        self.placement: Placement = place(self.collapse, [False] * len(self.strips), len(self.device))
        """What the device shows; until the first `update()` every strip takes a place."""
        for device_index, index in enumerate(self.placement):
            if index is not None:
                # what the strips draw before the first update (e.g. from Home Assistant) goes to the device as it
                # did before them; the device keeps what it shows until then (another mixer's), nothing is reset
                self.strips[index].target = self.device[device_index]
        self._absences = [_Absence() for _ in self.strips]
        self._bound = False
        self._fresh = True
        """Whether the next update places from scratch: the strips that are absent collapse without `hold`."""

    def position(self, index: int) -> int | None:
        """The strip of the device (from 0) the strip `index` of the configuration is on, None for none."""
        return self.placement.index(index) if index in self.placement else None

    def strip_at(self, device_index: int) -> int | None:
        """The strip of the configuration (its index) the strip of the device shows, None for none."""
        return self.placement[device_index]

    def update(self, absent: Sequence[bool] | None, busy: bool = False) -> bool:
        """
        Places the strips: `absent` tells which of them have nothing to control (None while that is not known, e.g.
        without a sound server: nothing moves then). True if the placement changed.
        """
        now = self.clock()
        if absent is not None:
            for absence, gone in zip(self._absences, absent, strict=True):
                if not gone:
                    absence.since = None
                    absence.collapsed = False
                elif absence.since is None:
                    absence.since = now
        if not self._bound:
            # the first time: the strips get onto the device, whatever it does
            self._bound = True
            self._apply(self._wanted(now) if absent is not None else self.placement, initial=True)
            return True
        if absent is None or busy:
            return False
        wanted = self._wanted(now)
        if wanted == self.placement:
            return False
        self._apply(wanted)
        return True

    def _wanted(self, now: float) -> Placement:
        fresh, self._fresh = self._fresh, False
        for absence in self._absences:
            if absence.since is not None and (fresh or now - absence.since >= self.hold):
                absence.collapsed = True
        return place(self.collapse, [absence.collapsed for absence in self._absences], len(self.device))

    def _apply(self, placement: Placement, initial: bool = False) -> None:
        before = self.placement
        self.placement = placement
        for strip in self.strips:
            strip.target = None
        for device_index, index in enumerate(placement):
            if index is None:
                self.device[device_index].reset()
            else:
                self.strips[index].bind(self.device[device_index])
        if not initial:
            self._log(before)

    def _log(self, before: Placement) -> None:
        changes: list[str] = []
        for index in range(len(self.strips)):
            old = before.index(index) if index in before else None
            new = self.position(index)
            if old == new:
                continue
            title = self.titles(index)
            if new is None:
                gone = self._absences[index].collapsed and self.collapse[index]
                changes.append(f"{title} {'collapses' if gone else 'waits'}")
            elif old is None:
                changes.append(f"{title} appears at {new + 1}")
            else:
                changes.append(f"{title} moves to {new + 1}")
        _LOGGER.info(f"Strips: {', '.join(changes)}")
