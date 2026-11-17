"""
`migrate-config`: a file with strips and layouts written as channels, states and slots (see "Migration" in
docs/design/channels-states-slots.md), with a report of what changed. The sections that stay (`[device]`, `[mqtt]`,
...) keep their comments; the strips and layouts become `[channel.*]`, `[state.*]`, `[slots]`, `[controls]`,
`[pool.auto]` and `[people]`.
"""

import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import tomlkit
from tomlkit.items import InlineTable, Table

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.inheritance import Inheritance
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.values import DEFAULT_LAYOUT
from xtouch_daemon.hardware import protocol
from xtouch_daemon.slots.expressions import RESERVED
from xtouch_daemon.slots.model import ABSENT_AFTER, AUTO, LOOK_OPTIONS, MODE_DELAY_OFF, PEOPLE

APP_LOOK = LOOK_OPTIONS | {"encoder", "min_volume", "max_volume"}
"""What an `auto` strip has that becomes an option of its place."""
PEOPLE_LOOK = ("color", "talking_color", "meter", "meter_point", "max_volume")
"""What a `voip` strip of the group has that becomes an option of `[people]`."""
_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Migration:
    text: str
    """The new file."""
    notes: tuple[str, ...]
    """What changed that people should know: ids, strips that moved, entities that were renamed, ..."""


type Show = str | None
"""What a strip becomes on its slot: a channel id, `auto`, or None for nothing (`-`)."""


@dataclass(frozen=True)
class _Place:
    """A strip of a layout at a place, as it will be a candidate (with the options of the place) and controls."""

    show: Show
    options: Mapping[str, Any] = field(default_factory=dict)
    controls: Mapping[str, Any] | None = None
    present: bool = False
    """Whether it collapsed: it shows only while present."""

    def key(self) -> str:
        return json.dumps([self.show, self.options, self.present], sort_keys=True)


class _Migrator:
    def __init__(self, data: Mapping[str, Any], config: Config):
        self.data = data
        self.config = config
        self.notes: list[str] = []
        self.channels: dict[str, dict[str, Any]] = {}
        self.taken: set[str] = {layout.name for layout in config.layouts}
        self.people: dict[str, Any] = {}
        self.collapsing: set[str] = set()
        """The channels of strips with `collapse`: `behavior.collapse_hold` becomes their `absent_after`."""

    # -- ids --------------------------------------------------------------------------------------------------------

    def _free(self, wanted: str) -> str:
        name = wanted
        number = 2
        while name in self.taken or name in RESERVED or name in (AUTO, PEOPLE, DEFAULT_LAYOUT):
            name = f"{wanted}_{number}"
            number += 1
        self.taken.add(name)
        return name

    def channel(self, strip: Mapping[str, Any], number: int, where: str) -> str:
        """The id of the channel of a strip: the one with the same options, or a new one."""
        options = {key: value for key, value in strip.items() if key not in ("id", "collapse")}
        if options["type"] == "voip":
            options["type"] = "person"
            options.pop("launch", None)
            options.pop("launch_when_running", None)
            if isinstance(options["person"], list) and len(options["person"]) == 1:
                options["person"] = options["person"][0]
        for name, existing in self.channels.items():
            if existing == options:
                return name
        entities = options["type"] == "homeassistant" or "homeassistant" in (
            options.get("fader"),
            options.get("encoder"),
        )
        entities = entities or (bool(options.get("choices")) and self.config.mqtt is not None)
        if "id" in strip:
            wanted = str(strip["id"])
        elif entities:
            wanted = f"strip_{number}"
        else:
            person = options.get("person", "")
            label = str(options.get("label") or (person[0] if isinstance(person, list) else person))
            slug = _SLUG.sub("_", label.lower()).strip("_")
            wanted = slug if slug and slug[0].isalpha() else f"{options['type']}_{number}"
        name = self._free(wanted)
        if name != wanted and entities:
            self.notes.append(
                f"{where}: its entities in Home Assistant are now *_{name}_* (another strip had *_{wanted}_*); "
                "change automations that use them"
            )
        elif entities and "id" not in strip:
            self.notes.append(
                f"{where}: channel {name}, named after its entities; rename it to something that says what it is"
            )
        self.channels[name] = options
        return name

    # -- strips -----------------------------------------------------------------------------------------------------

    def place(self, strip: Mapping[str, Any], number: int, where: str) -> _Place:
        """What a strip (an `inherit` one resolved already) becomes at its place."""
        kind = strip["type"]
        collapse = bool(strip.get("collapse"))
        if kind == "empty":
            return _Place(None)
        if kind == "auto":
            options = {key: value for key, value in strip.items() if key in APP_LOOK}
            controls: dict[str, Any] = {}
            if options.get("encoder") == "homeassistant":
                controls["encoder"] = options.pop("encoder")
            if strip.get("fader") == "homeassistant":
                controls["fader"] = "homeassistant"
            if strip.get("launch") is not None:
                controls["select"] = self._launch(strip)
            if "fader" in controls or "encoder" in controls:
                controls["id"] = str(strip.get("id") or f"strip_{number}")
            if collapse:
                self.notes.append(f"{where}: collapse is gone for auto: the slot shows auto, nothing shifts")
            return _Place(AUTO, options, controls or None)
        if kind == "voip" and not strip.get("person"):
            for option in PEOPLE_LOOK:
                if option in strip:
                    if option in self.people and self.people[option] != strip[option]:
                        self.notes.append(f"{where}: {option} differs from the other voip strips: [people] has one")
                    self.people.setdefault(option, strip[option])
            launch = {"select": self._launch(strip)} if strip.get("launch") is not None else None
            return _Place(AUTO, {}, launch)
        name = self.channel(strip, number, where)
        launch = {"select": self._launch(strip)} if kind == "voip" and strip.get("launch") is not None else None
        if collapse:
            self.notes.append(
                f"{where}: collapse: {name} stays on its slot while present, auto otherwise (nothing shifts; a pool "
                "of channels fills slots in order)"
            )
            self.collapsing.add(name)
        return _Place(name, {}, launch, collapse)

    @staticmethod
    def _launch(strip: Mapping[str, Any]) -> dict[str, Any]:
        launch: dict[str, Any] = {"launch": list(strip["launch"])}
        if strip.get("launch_when_running"):
            launch["launch_when_running"] = True
        return launch


def migrate(text: str, source: str = "config") -> Migration:
    """The file in the format of channels, states and slots; ConfigError for a file that is no valid old one."""
    from xtouch_daemon.config.files import parse_config

    config = parse_config(text, source)
    if config.slots is not None:
        raise ConfigError(f"{source} has channels, states and slots already")
    data = tomllib.loads(text)
    migrator = _Migrator(data, config)
    layouts = config.layout_list()
    raw = [list(data.get("strip", ())), *(list(layout.get("strip", ())) for layout in data.get("layout", ()))]
    inheritance = Inheritance(layouts)

    places: list[list[_Place]] = []
    for index, layout in enumerate(layouts):
        row: list[_Place] = []
        count = max(protocol.STRIPS, len(layout.strips))
        for position in range(count):
            number = position + 1
            where = f"strip {number}" + ("" if index == 0 else f" of layout {layout.name}")
            strip: Mapping[str, Any] = raw[index][position] if position < len(raw[index]) else {"type": "auto"}
            if strip["type"] == "inherit":
                origin = inheritance.origin((index, position))
                strip = raw[origin[0]][origin[1]] if origin is not None else {"type": "auto"}
                if origin is not None and origin != (0, position):
                    from_where = f"strip {origin[1] + 1}" + (
                        "" if origin[0] == 0 else f" of layout {layouts[origin[0]].name}"
                    )
                    migrator.notes.append(f"{where}: inherit: {from_where}")
            place = migrator.place(strip, number, where)
            if position >= protocol.STRIPS:
                if place.show not in (None, AUTO):
                    migrator.notes.append(
                        f"{where}: no slot (the device has {protocol.STRIPS}): channel {place.show} is not shown; "
                        "put it on a slot or in a pool"
                    )
                continue
            row.append(place)
        places.append(row)

    modes = sorted(
        range(1, len(layouts)), key=lambda index: -layouts[index].priority
    )  # the order in which modes win, as layouts did
    slots: dict[str, Any] = {}
    controls: dict[str, Any] = {}
    for position in range(protocol.STRIPS):
        default = places[0][position]
        stack: list[str | InlineTable] = []
        for index in modes:
            place = places[index][position]
            if place.key() != default.key():
                stack.append(_candidate(_metered(place, layouts[index].meter_point, migrator), layouts[index].name))
        stack.append(_candidate(default, None))
        if default.present:
            stack.append(AUTO)
        if stack[-1] == AUTO and len(stack) > 1 and not default.present:
            stack.pop()
        if stack != [AUTO]:
            slots[str(position + 1)] = stack[0] if len(stack) == 1 and isinstance(stack[0], str) else stack
        entries = _controls(places, modes, layouts, position)
        if entries:
            controls[str(position + 1)] = entries[0] if len(entries) == 1 else entries
    return Migration(_render(text, data, config, migrator, slots, controls), tuple(migrator.notes))


def _metered(place: _Place, meter_point: str | None, migrator: _Migrator) -> _Place:
    """The candidate of a strip of a layout with `meter_point`: the layout's, unless the strip has its own."""
    if meter_point is None or "meter_point" in place.options:
        return place
    if place.show is None or migrator.channels.get(place.show, {}).get("type") == "homeassistant":
        return place
    if place.show in migrator.channels and "meter_point" in migrator.channels[place.show]:
        return place
    return _Place(place.show, {**place.options, "meter_point": meter_point}, place.controls, place.present)


def _candidate(place: _Place, mode: str | None) -> str | InlineTable:
    show = "-" if place.show is None else place.show
    when = " and ".join(part for part in (mode, "present" if place.present else None) if part)
    if not place.options:
        return f"{show} if {when}" if when else show
    table = tomlkit.inline_table()
    table["show"] = show
    if when:
        table["when"] = when
    table.update(place.options)
    return table


def _controls(
    places: list[list[_Place]], modes: list[int], layouts: tuple[Any, ...], position: int
) -> list[InlineTable]:
    default = places[0][position].controls
    entries: list[InlineTable] = []
    others: list[str] = []
    for index in modes:
        own = places[index][position].controls
        if own == default:
            continue
        others.append(layouts[index].name)
        if own is not None:
            entries.append(_inline(own, layouts[index].name))
    if default is not None:
        entries.append(_inline(default, " and ".join(f"not {name}" for name in others) or None))
    return entries


def _inline(controls: Mapping[str, Any], when: str | None) -> InlineTable:
    table = tomlkit.inline_table()
    for key, value in controls.items():
        if isinstance(value, Mapping):
            inner = tomlkit.inline_table()
            inner.update(value)
            table[key] = inner
        else:
            table[key] = value
    if when:
        table["when"] = when
    return table


def _render(
    text: str,
    data: Mapping[str, Any],
    config: Config,
    migrator: _Migrator,
    slots: Mapping[str, Any],
    controls: Mapping[str, Any],
) -> str:
    document = tomlkit.parse(text)
    for key in ("strip", "layout"):
        if key in document:
            del document[key]
    behavior = data.get("behavior", {})
    pool: dict[str, Any] = {}
    if "auto_hold" in behavior:
        pool["hold"] = behavior["auto_hold"]
    if "ignore" in behavior:
        pool["exclude"] = list(behavior["ignore"])
    absent_after = behavior.get("collapse_hold")
    if "behavior" in document:
        section = document["behavior"]
        assert isinstance(section, Table)
        for key in ("auto_hold", "ignore", "collapse_hold"):
            if key in section:
                del section[key]
        if not section:
            del document["behavior"]
    hold = data.get("switching", {}).get("hold")
    if "switching" in document:
        section = document["switching"]
        assert isinstance(section, Table)
        if "hold" in section:
            del section["hold"]
            migrator.notes.append("switching.hold: now delay_off of each mode")

    channels = tomlkit.table(is_super_table=True)
    for name, options in migrator.channels.items():
        table = tomlkit.table()
        table.update(options)
        if absent_after is not None and absent_after != ABSENT_AFTER and name in migrator.collapsing:
            table["absent_after"] = absent_after
        channels[name] = table
    if migrator.channels:
        document["channel"] = channels
    if pool:
        pools = tomlkit.table(is_super_table=True)
        auto = tomlkit.table()
        auto.update(pool)
        pools[AUTO] = auto
        document["pool"] = pools
    if migrator.people:
        people = tomlkit.table()
        people.update(migrator.people)
        document[PEOPLE] = people
    if config.layouts:
        states = tomlkit.table(is_super_table=True)
        for layout in config.layouts:
            state = tomlkit.table()
            state["mode"] = True
            if layout.label:
                state["label"] = layout.label
            if layout.apps:
                state["apps"] = list(layout.written("apps"))
            if layout.processes:
                state["processes"] = list(layout.written("processes"))
            if layout.priority:
                state["priority"] = layout.priority
            if hold is not None and hold != MODE_DELAY_OFF:
                state["delay_off"] = hold
            states[layout.name] = state
        document["state"] = states
        migrator.notes.append(
            "The layouts are modes: select.<namespace>_mode replaces select.<namespace>_layout in Home Assistant "
            "(change automations that use it); the layout kept for the next start is not carried over"
        )
    slot_table = tomlkit.table()
    for key, value in slots.items():
        if isinstance(value, list):
            array = tomlkit.array()
            array.extend(value)
            slot_table[key] = array
        else:
            slot_table[key] = value
    document["slots"] = slot_table
    if controls:
        control_table = tomlkit.table()
        control_table.update(controls)
        document["controls"] = control_table
    if any(strip.get("type") == "voip" and not strip.get("person") for strip in _all_raw(data)):
        migrator.notes.append(
            "voip strips: the people share the slots of auto now, from the right; their look is in [people]"
        )
    if re.search(r"^\s*#.*\[\[(strip|layout)", text, re.MULTILINE):
        migrator.notes.append("Comments about strips and layouts are still in the file: delete or rewrite them")
    return tomlkit.dumps(document)


def _all_raw(data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [*data.get("strip", ()), *(strip for layout in data.get("layout", ()) for strip in layout.get("strip", ()))]
