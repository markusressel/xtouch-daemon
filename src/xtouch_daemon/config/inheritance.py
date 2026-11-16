"""
Resolving the `inherit` strips of layouts: which strip of which layout each one stands for.
"""

from xtouch_daemon import protocol
from xtouch_daemon.config.audio_strips import AutoStripConfig
from xtouch_daemon.config.layout import LayoutConfig
from xtouch_daemon.config.layout_strips import InheritStripConfig
from xtouch_daemon.config.strip import BaseStripConfig
from xtouch_daemon.config.strips import HomeAssistantStripConfig, StripConfig

INHERIT_LIMIT = 8
"""How many `inherit` strips may refer to one another in a row."""

type _Entry = tuple[int, int]
"""A strip in the list of a layout: the index of the layout in `Config.layout_list()` and the position, from 0."""


class Inheritance:
    """Resolves `inherit` strips into the strips they refer to; ValueError for a reference that can't be resolved."""

    def __init__(self, layouts: tuple[LayoutConfig, ...]):
        self.layouts = layouts
        self.names = [layout.name for layout in layouts]

    def where(self, entry: _Entry) -> str:
        layout, position = entry
        return (f"layout[{layout}].strip" if layout else "strip") + f"[{position + 1}]"

    def _strip(self, entry: _Entry) -> StripConfig:
        return self.layouts[entry[0]].strips[entry[1]]

    def _enter(self, entry: _Entry, chain: tuple[_Entry, ...]) -> tuple[_Entry, ...]:
        if entry in chain:
            cycle = [*chain[chain.index(entry) :], entry]
            raise ValueError(f"inherit strips that refer to each other: {' -> '.join(map(self.where, cycle))}")
        if len(chain) >= INHERIT_LIMIT:
            raise ValueError(f"{self.where(chain[0])}: more than {INHERIT_LIMIT} inherit strips refer to one another")
        return (*chain, entry)

    def _target(self, entry: _Entry) -> _Entry | None:
        """
        The strip an `inherit` strip refers to (without `strip`: the one at its own place). None: an `auto` strip after
        the configured strips of a layout.
        """
        strip = self._strip(entry)
        place = entry[1]
        assert isinstance(strip, InheritStripConfig)
        where = self.where(entry)
        if strip.layout is not None and strip.layout not in self.names:
            raise ValueError(f"{where}: inherit from the layout {strip.layout}, which is not there")
        layout = self.names.index(strip.layout) if strip.layout is not None else 0
        name = f"the layout {strip.layout}" if layout else "the default layout"
        strips = self.layouts[layout].strips
        if strip.strip is None:
            if place < len(strips):
                return layout, place
            if place < protocol.STRIPS:
                return None
            raise ValueError(f"{where}: inherit, but {name} has only {max(len(strips), protocol.STRIPS)} strips")
        if isinstance(strip.strip, int):
            if strip.strip > len(strips):
                raise ValueError(f"{where}: inherit strip {strip.strip}, but {name} has {len(strips)} strips")
            return layout, strip.strip - 1
        found = [position for position, other in enumerate(strips) if getattr(other, "id", None) == strip.strip]
        if not found:
            raise ValueError(f"{where}: inherit strip {strip.strip}, but {name} has no strip with that id")
        if len(found) > 1:
            raise ValueError(f"{where}: inherit strip {strip.strip}, but {name} has {len(found)} strips with that id")
        return layout, found[0]

    def origin(self, entry: _Entry) -> _Entry | None:
        """The strip an `inherit` strip is in the end (itself for another one), None for an `auto` strip of none."""
        chain: tuple[_Entry, ...] = ()
        current: _Entry | None = entry
        while current is not None and isinstance(self._strip(current), InheritStripConfig):
            chain = self._enter(current, chain)
            current = self._target(current)
        return current

    def resolve(self, entry: _Entry, chain: tuple[_Entry, ...] = (), lands: int | None = None) -> StripConfig:
        """The strip of the entry, with the strips `inherit` ones refer to; `lands` is the place it lands on."""
        strip = self._strip(entry)
        _, position = entry
        if lands is None:
            lands = position
        if not isinstance(strip, InheritStripConfig):
            if isinstance(strip, BaseStripConfig | HomeAssistantStripConfig) and strip.id is None and lands != position:
                # on another place: its entities in Home Assistant are still those of its own place
                strip = strip.model_copy(update={"id": f"strip_{position + 1}"})
            return strip
        chain = self._enter(entry, chain)
        target = self._target(entry)
        if target is None:
            return AutoStripConfig(type="auto")
        return self.resolve(target, chain, lands)
