"""
The channels of a file as the page Channels shows them: their types, the options of each type (those of its strip
without what belongs to a place or a layout), the options of `[pool.auto]` and `[people]`, and where each channel is
used.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from xtouch_daemon.config.slots import CHANNEL_ONLY
from xtouch_daemon.gui.domain.schema import Option, option, options, strip_options
from xtouch_daemon.slots.model import AUTO, ChannelConfig, PeopleConfig, PoolConfig


@dataclass(frozen=True)
class ChannelType:
    name: str
    """The value of `type`."""
    title: str
    icon: str
    """A Material Design icon (see `icon()`)."""
    strip: str
    """The type of the strip that shows it."""
    help: str


CHANNEL_TYPES = {
    kind.name: kind
    for kind in (
        ChannelType("output", "Output", "volume-high", "output", "A device that plays: speakers, headphones."),
        ChannelType("input", "Input", "microphone", "input", "A device that records: a microphone."),
        ChannelType("apps", "Applications", "apps", "apps", "The streams of a group of applications."),
        ChannelType("person", "Person", "account", "voip", "Someone of the voice chat."),
        ChannelType("homeassistant", "Home Assistant", "home-assistant", "homeassistant", "Its automations."),
    )
}
"""The types of channels, in the order the page offers them."""

NOT_ON_CHANNELS = frozenset({"collapse"})
"""Options of strips that channels don't take: a channel stays on its slot while `present` (see the stacks)."""
NOT_ON_PEOPLE = frozenset({"launch", "launch_when_running", "person"})
"""What the strips of people have no use for: a launch is a control of a slot, the person is who it is."""


def channel_options(channel_type: str) -> tuple[Option, ...]:
    """The options of a channel of the type: its strip's, then those about slots (`tags`, `in_auto`, ...)."""
    kind = CHANNEL_TYPES[channel_type]
    skip = NOT_ON_CHANNELS | (NOT_ON_PEOPLE - {"person"} if channel_type == "person" else frozenset())
    own = tuple(option(name, ChannelConfig.model_fields[name]) for name in sorted(CHANNEL_ONLY))
    return (*(each for each in strip_options(kind.strip) if each.name not in skip), *own)


def pool_options() -> tuple[Option, ...]:
    """The options of `[pool.auto]`: which applications it takes, how long, and the look of its strips."""
    look = tuple(each for each in strip_options("auto") if each.name not in NOT_ON_CHANNELS)
    return (*options(PoolConfig, skip=("channels",)), *look)


def people_options() -> tuple[Option, ...]:
    """The options of `[people]`: their order, and the look of their strips."""
    look = tuple(each for each in strip_options("voip") if each.name not in NOT_ON_CHANNELS | NOT_ON_PEOPLE)
    return (*options(PeopleConfig), *look)


def shown_by(entry: Any) -> str | None:
    """What a candidate of a stack shows (`"voip if call"` shows `voip`), None for a broken one."""
    if isinstance(entry, str):
        return entry.partition(" if ")[0].strip()
    if isinstance(entry, Mapping):
        show = entry.get("show")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        return show if isinstance(show, str) else None
    return None


def stack_of(value: Any) -> list[Any]:
    """The candidates of a slot: a string is one."""
    return [value] if isinstance(value, str) else list(value) if isinstance(value, list) else []


def uses(values: Mapping[str, Any], name: str) -> tuple[str, ...]:
    """Where a channel (or a pool) is used: `slot 2`, `pool games`, `state call`."""
    found: list[str] = []
    for slot, stack in values.get("slots", {}).items():
        if any(shown_by(entry) == name for entry in stack_of(stack)):
            found.append(f"slot {slot}")
    for section in ("pool", "state"):
        for key, table in values.get(section, {}).items():
            if isinstance(table, Mapping) and name in table.get("channels", ()):  # pyright: ignore[reportUnknownMemberType]
                found.append(f"{section} {key}")
    return tuple(found)


def free_id(taken: Mapping[str, Any] | set[str], base: str) -> str:
    """`base`, or `base_2`, `base_3`, ... while that is taken (ids are lowercase, with digits and `_`)."""
    if base not in taken and base != AUTO:
        return base
    number = 2
    while f"{base}_{number}" in taken:
        number += 1
    return f"{base}_{number}"
