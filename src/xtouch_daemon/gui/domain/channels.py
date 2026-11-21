"""
The channels of a file as the page Channels shows them: their types, the options of each type (those of its strip),
the options of the built-in pools (`[pool.apps]`, `[pool.people]`, `[pool.auto]`), and where each channel is used.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from xtouch_daemon.config.slots import CHANNEL_ONLY
from xtouch_daemon.gui.domain.schema import Option, look_options, option, options, strip_options
from xtouch_daemon.slots.model import (
    APPS,
    AUTO,
    DEVICES,
    PEOPLE,
    PEOPLE_POOL_OPTIONS,
    AppsConfig,
    AutoConfig,
    ChannelConfig,
    DevicesConfig,
    PeopleConfig,
    place_options,
)


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
    """What its strip does on the device, in a sentence or two (the menu Add says it under the title)."""


CHANNEL_TYPES = {
    kind.name: kind
    for kind in (
        ChannelType(
            "output", "Output", "volume-high", "output", "The fader sets the volume of speakers or headphones."
        ),
        ChannelType("input", "Input", "microphone", "input", "The fader sets the volume of a microphone."),
        ChannelType(
            "apps",
            "Applications",
            "apps",
            "apps",
            "The fader sets the volume of a group of applications, e.g. every browser.",
        ),
        ChannelType(
            "person",
            "Person",
            "account",
            "voip",
            "The fader sets the volume of someone in the voice chat. Mute mutes them for you.",
        ),
        ChannelType(
            "homeassistant",
            "Home Assistant",
            "home-assistant",
            "homeassistant",
            "The fader, encoder and buttons are entities in Home Assistant. Its automations use them.",
        ),
        ChannelType(
            "custom",
            "Custom",
            "console",
            "custom",
            "Each part does what you bind it to, e.g. a program that sets the brightness of a screen.",
        ),
    )
}
"""The types of channels, in the order the page offers them."""


def channel_options(channel_type: str) -> tuple[Option, ...]:
    """The options of a channel of the type: its strip's, then those about slots (`tags`, `in_pool`, ...)."""
    kind = CHANNEL_TYPES[channel_type]
    own = tuple(option(name, ChannelConfig.model_fields[name]) for name in sorted(CHANNEL_ONLY))
    return (*strip_options(kind.strip), *own)


def pool_options(pool: str) -> tuple[Option, ...]:
    """
    The options of a built-in pool: `[pool.apps]` which applications it takes, how long and from where, `[pool.people]`
    their order and side, `[pool.devices]` which devices it takes, and the look of the strips of each (`[pool.auto]`
    only that).
    """
    if pool == PEOPLE:
        return (*options(PeopleConfig), *look_options("voip", PEOPLE_POOL_OPTIONS))
    if pool == DEVICES:
        return (*options(DevicesConfig), *look_options("output", place_options(DEVICES)))
    return (*options(AppsConfig if pool == APPS else AutoConfig), *look_options("auto", place_options(pool)))


BUILT_IN_POOLS = (
    (APPS, "Applications", "apps", "the applications that play and have no slot"),
    (PEOPLE, "People", "account-group", "the people of the voice chat, their order and side"),
    (DEVICES, "Devices", "headphones", "the outputs and inputs that no channel has, e.g. a USB headset"),
    (AUTO, "Auto", "auto-fix", "the applications and the people, who share its slots"),
)
"""The built-in pools as the page Channels lists them: id, title, icon, what they are."""


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
    """
    Where a channel (or a pool) is used: `slot 2`, `pool games`, `state call`. The applications and the people are
    also on the slots of auto, which they share.
    """
    shows = {name, AUTO} if name in (APPS, PEOPLE) else {name}
    found: list[str] = []
    for slot, stack in values.get("slots", {}).items():
        if any(shown_by(entry) in shows for entry in stack_of(stack)):
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
