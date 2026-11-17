"""
A configuration of channels, states and slots (the prototype of docs/design/channels-states-slots.md) on the
device: the strips each slot can show, built from the channels, pools and the options of the candidates as strips of
today's types and checked when the file is loaded (see `runtime.binder` for how they show).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.presets import Kind, expand
from xtouch_daemon.config.sections import VoipConfig
from xtouch_daemon.config.strips import StripConfig
from xtouch_daemon.slots.model import AUTO, PEOPLE, Scene
from xtouch_daemon.slots.resolver import SLOTS

SECTIONS = ("channel", "pool", "people", "state", "slots", "controls")
"""The sections of the format of channels, states and slots; a file with one of them is in that format."""
CHANNEL_ONLY = frozenset({"tags", "in_auto", "absent_after"})
"""Options of a channel that are about slots, not about its strip."""
POOL_ONLY = frozenset({"channels", "exclude", "hold"})
"""Options of a pool that are about its members, not about its strips."""
PEOPLE_ONLY = frozenset({"order"})
"""Options of `[people]` that are not about their strips."""
EMPTY = "-"

_STRIP = TypeAdapter[StripConfig](StripConfig)


@dataclass(frozen=True)
class SlotsSetup:
    """The scene of a file, and the strip of every candidate it can show (and of every member of its pools)."""

    scene: Scene
    data: Mapping[str, Any]
    """The sections of the format, as in the file."""
    strips: Mapping[tuple[int, int, str | None], StripConfig]
    """By slot, candidate and channel (None for a pool of applications, and for `-`)."""
    people: Mapping[str, Any] = field(default_factory=dict)
    """The look of the strips of people (the options of `[people]`)."""
    channels: Mapping[str, StripConfig] = field(default_factory=dict)
    """The strip of each channel on its own (its look where a candidate adds none)."""

    def person(self, name: str) -> StripConfig:
        """The strip of a person without a channel (checked with a made-up name when the file is loaded)."""
        return _STRIP.validate_python({"type": "voip"} | dict(self.people) | {"person": name})

    def ignored(self) -> tuple[str, ...]:
        """
        What the `auto` strips never take one by one: `exclude`, and the applications of every `apps` channel (one
        that has no slot goes into `auto` as a whole, as the strip of the channel).
        """
        parts = [*self.scene.pools[AUTO].exclude]
        parts += [part for channel in self.scene.channels.values() if channel.type == "apps" for part in channel.match]
        return expand(tuple(parts), Kind.STREAMS)


def split(data: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The sections of today's format, and those of channels, states and slots (None for a file without them)."""
    rest = {key: value for key, value in data.items() if key not in SECTIONS}
    slots = {key: value for key, value in data.items() if key in SECTIONS}
    return rest, slots or None


def setup(config: Config, data: Mapping[str, Any]) -> Config:
    """
    `config` (today's sections of the file) with the slots of `data`; ConfigError for every problem, also of the
    strips the candidates make.
    """
    if config.strips or config.layouts:
        raise ConfigError("[slots] replaces [[strip]] and [[layout]]: a file has either")
    scene = Scene.of(data)
    problems: list[str] = []
    strips: dict[tuple[int, int, str | None], StripConfig] = {}
    channels: Mapping[str, Mapping[str, Any]] = data.get("channel", {})
    pools: Mapping[str, Mapping[str, Any]] = data.get("pool", {})

    def check(where: str, options: Mapping[str, Any]) -> StripConfig | None:
        try:
            return _STRIP.validate_python(dict(options))
        except ValidationError as e:
            for error in e.errors():
                path = ".".join(str(part) for part in error["loc"][1:])
                problems.append(f"{where}: {path + ': ' if path else ''}{error['msg'].removeprefix('Value error, ')}")
            return None

    def add(key: tuple[int, int, str | None], where: str, options: Mapping[str, Any]) -> None:
        if key[2] is not None and key[2] in broken:
            # its problems are those of the channel
            return
        strip = check(where, options)
        if strip is not None:
            strips[key] = strip

    def channel_strip(name: str) -> dict[str, Any]:
        options = {key: value for key, value in channels[name].items() if key not in CHANNEL_ONLY}
        if options["type"] == "person":
            options["type"] = "voip"
        return options

    # each channel on its own first: its problems once, not on every slot
    own_strips = {name: check(f"channel.{name}", channel_strip(name)) for name in scene.channels}
    broken = {name for name, strip in own_strips.items() if strip is None}
    for slot in SLOTS:
        add((slot, -1, None), f"slots.{slot}", {"type": "empty"})
        for index, candidate in enumerate(scene.stacks[slot]):
            where = f"slots.{slot}[{index}]"
            own = dict(candidate.options)
            if candidate.show is None:
                add((slot, index, None), where, {"type": "empty"})
            elif candidate.show in scene.channels:
                add((slot, index, candidate.show), where, channel_strip(candidate.show) | own)
            else:
                look = {key: value for key, value in pools.get(candidate.show, {}).items() if key not in POOL_ONLY}
                if candidate.show == AUTO:
                    add((slot, index, None), where, {"type": "auto"} | look | own)
                else:
                    add((slot, index, None), where, {"type": "empty"})
                # a pool hands out channels: `auto` the apps channels without a slot, the others their own; a channel
                # looks and works as the channel, the pool's look only fills in what the channel leaves open (the
                # options of the place are for applications without a channel)
                members = (
                    [name for name, channel in scene.channels.items() if channel.type == "apps"]
                    if candidate.show == AUTO
                    else scene.members_of(scene.pools[candidate.show].channels)
                )
                for member in members:
                    add((slot, index, member), f"{where} ({member})", look | channel_strip(member))
                if candidate.show == AUTO:
                    # the person channels that share its slots, as themselves
                    for member in (name for name, channel in scene.channels.items() if channel.type == "person"):
                        add((slot, index, member), f"{where} ({member})", channel_strip(member))
    people = {key: value for key, value in data.get(PEOPLE, {}).items() if key not in PEOPLE_ONLY}
    check("people", {"type": "voip"} | people | {"person": "someone"})
    for slot in config.switching.chord:
        if any(controls.solo is not None for controls in scene.controls.get(slot, ())):
            problems.append(f"controls.{slot}.solo: the Solo buttons of the chord can't be claimed (switching.chord)")
    if problems:
        raise ConfigError("\n".join(dict.fromkeys(problems)))
    # people share the slots of auto in every configuration: the section has defaults for everything
    voip = config.voip or VoipConfig()
    behavior = config.behavior.model_copy(
        update={
            "auto_hold": scene.pools[AUTO].hold,
            "ignore": (*config.behavior.ignore, *SlotsSetup(scene, data, strips, people).ignored()),
        }
    )
    result = config.model_copy(update={"voip": voip, "behavior": behavior})
    channel_strips = {name: strip for name, strip in own_strips.items() if strip is not None}
    result._slots = SlotsSetup(scene, data, strips, people, channel_strips)
    return result
