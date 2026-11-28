"""
What the list of the page Channels and its menu Add show, as plain data for QML: the channels and the pools in two
groups, each with its icon, the lines under its name and whether it has a problem, and the entries of the menu.
No Qt here: `ChannelsPage` puts the rows into a model.
"""

import re
from collections.abc import Mapping
from typing import Any

from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.gui.domain.channels import BUILT_IN_POOLS, CHANNEL_TYPES, uses
from xtouch_daemon.gui.domain.slots_document import OptionPath, Validation
from xtouch_daemon.gui.quick.pages.slots_data import rich
from xtouch_daemon.gui.quick.pages.sound import sound_of
from xtouch_daemon.slots.model import BUILT_IN

APPS = ("pool", "apps")
PEOPLE = ("pool", "people")
AUTO = ("pool", "auto")
POOLS = tuple(("pool", name) for name, *_ in BUILT_IN_POOLS)
"""The built-in pools: their options and look, no id of their own."""
CUSTOM_POOL = "pool.custom"
"""The key of the form of a pool of your own: a list of channels. Pools of applications and of people add their kind."""
CUSTOM_APPS_POOL = f"{CUSTOM_POOL}.apps"
CUSTOM_PEOPLE_POOL = f"{CUSTOM_POOL}.people"
DIRECTIONS = (Direction.OUTPUT, Direction.INPUT)
ADD_POOLS = (
    (None, "Pool of channels", "Each slot of the pool shows the next channel of a list that is present."),
    ("apps", "Pool of applications", "Each application of a group that plays gets a strip of its own."),
    ("people", "Pool of people", "Each of the people you list gets a strip of their own while in the voice chat."),
)
"""The pools the menu Add offers: the kind (None for one of channels), title and what it does."""
POOL_KINDS = {
    CUSTOM_POOL: "A pool of channels: it hands the first of its channels that is there to the first slot that names "
    "it, the next one to the next slot.",
    CUSTOM_APPS_POOL: "A pool of applications: each application of the group that plays gets a slot of its own, while "
    "a slot names the pool.",
    CUSTOM_PEOPLE_POOL: "A pool of people: each of the listed people of the voice chat gets a slot of its own, while "
    "a slot names the pool.",
}
"""What a pool of your own is, by the key of its form."""
START = (
    "No channel in the file yet: every slot shows `auto`, the next application that plays. "
    "Add makes a channel: an output, an input, applications, a person or Home Assistant; "
    '"from the sound server" picks one of the devices there are now. A slot shows a channel once you name it on the '
    "page Slots."
)
NOT_USED = "Not used by a slot, pool or state yet."
_BREAKS = re.compile(r"([._:-])")

Row = tuple[str, dict[str, Any]]


def breakable(name: str) -> str:
    """A name of a device that breaks after its dots and dashes, where it does not fit on a line."""
    return _BREAKS.sub("\\1\u200b", name)


def key_of(path: OptionPath) -> str:
    """The key of an entry of the list: `channel:out`, `pool:apps`."""
    return f"{path[0]}:{path[1]}"


def path_of(key: str) -> OptionPath:
    kind, _, name = key.partition(":")
    return (kind, name)


def pool_kind_key(kind: object) -> str:
    """The key of the form of a pool of your own by its `kind`."""
    return {"apps": CUSTOM_APPS_POOL, "people": CUSTOM_PEOPLE_POOL}.get(str(kind), CUSTOM_POOL)


def custom_pools(values: Mapping[str, Any]) -> dict[str, Any]:
    """The pools of channels of the file (`[pool.<id>]` that is no built-in one)."""
    return {name: pool for name, pool in values.get("pool", {}).items() if name not in BUILT_IN}


def _header(name: str, title: str) -> Row:
    return f"header:{name}", {
        "kind": "header",
        "title": title,
        "name": "",
        "tags": "",
        "below": "",
        "icon": "",
        "tip": "",
        "problem": False,
        "sound": "",
        "soundKind": "",
    }


def _entry(path: OptionPath, **values: Any) -> Row:
    return key_of(path), {
        "kind": path[0],
        "name": str(path[1]),
        "tags": "",
        "tip": "",
        "sound": "",
        "soundKind": "",
        **values,
    }


def list_rows(values: Mapping[str, Any], validation: Validation) -> list[Row]:
    """A group of the channels, then one of the pools (the built-in ones, then yours), with their problems marked."""
    rows: list[Row] = [_header("channels", "Channels: one strip each")]
    for name, channel in values.get("channel", {}).items():
        kind = CHANNEL_TYPES.get(str(channel.get("type")))
        sound = sound_of(channel.get("type"))
        tags = ", ".join(channel.get("tags", ()))
        rows.append(
            _entry(
                ("channel", name),
                title=f"{channel['label']}  ·  {name}" if channel.get("label") else name,
                tags=f"[{tags}]" if tags else "",
                below=rich(", ".join(uses(values, name)) or "not used"),
                icon=kind.icon if kind else "help",
                tip=kind.title if kind else "?",
                problem=bool(validation.at("channel", name)),
                sound=name if sound is not None else "",
                soundKind=sound.value if sound is not None else "",
            )
        )
    rows.append(_header("pools", "Pools: a member for each slot that names them"))
    for pool, title, icon_name, what in BUILT_IN_POOLS:
        rows.append(
            _entry(
                ("pool", pool),
                title=title,
                below=rich(what),
                icon=icon_name,
                tip=f"[pool.{pool}]",
                problem=bool(validation.at("pool", pool)),
            )
        )
    for name, pool in custom_pools(values).items():
        kind = pool.get("kind")
        members = pool.get("match" if kind == "apps" else "people" if kind == "people" else "channels", ())
        if isinstance(members, str):
            members = (members,)
        what = ", ".join(str(member) for member in members) or "nothing yet"
        what = f"applications: {what}" if kind == "apps" else f"people: {what}" if kind == "people" else what
        rows.append(
            _entry(
                ("pool", name),
                title=name,
                below=rich(what),
                icon="format-list-bulleted",
                tip=f"[pool.{name}]",
                problem=bool(validation.at("pool", name)),
            )
        )
    return rows


def add_menu(audio: AudioState) -> list[dict[str, Any]]:
    """
    What Add offers: a channel of each type, one for each output and input the sound server has now, and the pools.
    An entry has its `action` (`type:output`, `device:input:mic`, `pool:apps`), its `text`, `icon`, `detail` as rich
    text, whether it is `enabled`, and `children` (the devices) that open under it.
    """
    types = [
        {"action": f"type:{kind.name}", "text": kind.title, "icon": kind.icon, "detail": rich(kind.help)}
        for kind in CHANNEL_TYPES.values()
    ]
    devices: list[dict[str, Any]] = []
    for direction in DIRECTIONS:
        kind = CHANNEL_TYPES[direction.value]
        found = audio.devices(direction)
        plural = f"{direction.value}s"
        detail = (
            f"A channel for one of the {len(found)} {plural} there are now."
            if len(found) > 1
            else f"A channel for the {direction.value} there is now."
            if found
            else f"The sound server has no {plural} now, or is not reachable."
        )
        devices.append(
            {
                "action": "",
                "text": f"{kind.title}s",
                "icon": kind.icon,
                "detail": rich(detail),
                "enabled": bool(found),
                "children": [
                    {
                        "action": f"device:{direction.value}:{device.name}",
                        "text": device.description,
                        "icon": kind.icon,
                        "detail": rich(f"`{breakable(device.name)}`"),
                    }
                    for device in found
                ],
            }
        )
    pools = [
        {"action": f"pool:{kind or ''}", "text": title, "icon": "format-list-bulleted", "detail": rich(tip)}
        for kind, title, tip in ADD_POOLS
    ]
    return [
        {"title": "Channel types", "items": types},
        {"title": "From the sound server", "items": devices},
        {"title": "Pools", "items": pools},
    ]
