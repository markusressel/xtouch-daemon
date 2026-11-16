"""
The strips of a layout as a row (see `placement.py` of the daemon): which of them the device shows now, which
collapsed and which wait for a place, for the strip list of the editor, which reaches every strip, also those beyond
the 8 of the device. And whether another strip can be added.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from xtouch_daemon import protocol
from xtouch_daemon.config.values import MAX_STRIPS
from xtouch_daemon.live import Snapshot


class Where(StrEnum):
    DEVICE = "device"
    """On a strip of the device."""
    COLLAPSED = "collapsed"
    """Not on the device: it has nothing to control (`collapse`)."""
    WAITS = "waits"
    """Not on the device: 8 strips before it take the places."""


@dataclass(frozen=True)
class FlowRow:
    index: int
    """The strip in the list of the layout, from 0."""
    where: Where
    position: int | None
    """The strip of the device it is on (from 0), None for none."""

    @property
    def text(self) -> str:
        """E.g. "on 3", "collapsed", "waits"."""
        return f"on {self.position + 1}" if self.position is not None else self.where.value


def flow_rows(strips: list[dict[str, Any]], snapshot: Snapshot | None) -> tuple[FlowRow, ...]:
    """
    Where each strip of the list is: as the daemon tells it (`snapshot.placement`, the strips of the layout it
    shows), or else from the file with every strip there: the first 8 on the device, the rest waiting. Like the
    daemon, `auto` strips fill the row up to 8: they get rows after those of `strips`.
    """
    strips = [*strips, *[{"type": "auto"}] * max(0, protocol.STRIPS - len(strips))]
    placement = snapshot.placement if snapshot is not None else None
    if placement is None:
        placement = tuple(range(min(len(strips), protocol.STRIPS)))
    rows: list[FlowRow] = []
    for index, values in enumerate(strips):
        if index in placement:
            rows.append(FlowRow(index, Where.DEVICE, placement.index(index)))
        elif values.get("collapse") is True and snapshot is not None and snapshot.placement is not None:
            rows.append(FlowRow(index, Where.COLLAPSED, None))
        else:
            rows.append(FlowRow(index, Where.WAITS, None))
    return tuple(rows)


def why_not_add(strips: list[dict[str, Any]]) -> str | None:
    """Why another (`auto`) strip can't be added at the end, None if it can."""
    if len(strips) >= MAX_STRIPS:
        return f"A layout has at most {MAX_STRIPS} strips."
    steady = sum(1 for values in strips if values.get("collapse") is not True)
    if len(strips) >= protocol.STRIPS and steady >= protocol.STRIPS:
        return (
            f"{protocol.STRIPS} strips without collapse come first: a strip after them could never show. Turn on "
            "collapse for one of them first."
        )
    return None
