"""
A layout (`[[layout]]`): another set of strips, and the rules that switch to it.
"""

from typing import Annotated

from pydantic import Field

from xtouch_daemon.config.legacy.strips import LegacyStripConfig
from xtouch_daemon.config.names import ProcessNames, StreamNames, WithPresets
from xtouch_daemon.config.values import MAX_STRIPS, METER_POINTS, LayoutLabel, MeterPoint, Slug


class LayoutConfig(WithPresets):
    """A set of strips to switch to, e.g. for games: by hand, from Home Assistant, or when an application runs."""

    name: Slug
    """
    What Home Assistant and `xtouch-daemon layout` call it: lower case letters, digits and underscores, e.g.
    "gaming".
    """
    label: LayoutLabel = ""
    """What the LCDs show when the layout comes, across the strips; by default the name."""
    apps: StreamNames = ()
    """
    Switch to the layout while one of these applications has a stream (playing or paused): parts of the names or
    binaries, ignoring case, as `match` of `apps` strips, or presets, e.g. `@games`.
    """
    processes: ProcessNames = ()
    """
    Switch to the layout while a process of one of these names runs (parts of the name, ignoring case), e.g.
    "mumble" for the voice chat even while nobody talks, or presets, e.g. `@steam-games` while a game from Steam runs.
    """
    priority: int = 0
    """Of several layouts whose rules match, the one with the highest priority comes, then the first in the file."""
    meter_point: Annotated[MeterPoint, METER_POINTS] | None = None
    """
    Where the meters of the layout's strips take the level, unless a strip has its own `meter_point`; by default
    `behavior.meter_point`.
    """
    strips: Annotated[tuple[LegacyStripConfig, ...], Field(alias="strip", max_length=MAX_STRIPS)] = ()
    """Up to 8 strips from the left (more with `collapse`), as the top-level ones; missing ones are `auto`."""

    @property
    def title(self) -> str:
        """The label, or else the name."""
        return self.label or self.name

    @property
    def has_rules(self) -> bool:
        return bool(self.apps or self.processes)
