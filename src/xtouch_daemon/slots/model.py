"""
The configuration of channels, pools, states, slots and controls, and its checks: `Scene.of()` reads the sections
`[channel.*]`, `[pool.*]`, `[state.*]`, `[slots]` and `[controls]` of a file (other sections are not its business).
"""

import difflib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from xtouch_daemon.config.base import ConfigError, Meanings
from xtouch_daemon.config.names import Presets
from xtouch_daemon.config.presets import Kind, expand
from xtouch_daemon.hardware import protocol
from xtouch_daemon.slots.expressions import RESERVED, Condition, ExpressionError, parse

AUTO = "auto"
"""The built-in pool of the applications and the people, who share its slots."""
APPS = "apps"
"""The built-in pool of the applications that play and have no slot (and `apps` channels without one)."""
PEOPLE = "people"
"""The built-in pool of the people in the voice chat without a slot of their own."""
DEVICES = "devices"
"""The built-in pool of the outputs and inputs that no channel has (a USB headset, Bluetooth speakers)."""
DEFAULT = "default"
BUILT_IN = (AUTO, APPS, PEOPLE, DEVICES)
AUTO_EXCLUDE = ("speech-dispatcher",)
"""What `apps` and `auto` never take unless `[pool.apps] exclude` says otherwise: the voice of screen readers."""
MEMBER_OPTIONS = frozenset({"channels", "exclude", "hold", "from", "order"})
"""Options of pools that are about their members and their slots, not about the look of their strips."""

STATE_DELAY_OFF = 3.0
"""Seconds a state stays on after its sources stopped, without `delay_off`."""
MODE_DELAY_OFF = 10.0
"""The same for modes (today's `switching.hold`)."""
ABSENT_AFTER = 3.0
"""Seconds a channel stays present after it had nothing to control any more, without `absent_after`."""

LOOK_OPTIONS = frozenset({"label", "color", "lit_when_idle", "rec", "solo", "meter", "meter_point"})
"""Options of a place that change only how a candidate looks there."""
PEOPLE_LOOK_OPTIONS = frozenset({"color", "meter", "meter_point"})
"""The options of a place of `people`: the strips of people show their names and have no Rec or Solo of their own."""
PEOPLE_POOL_OPTIONS = PEOPLE_LOOK_OPTIONS | {"talking_color", "max_volume"}
"""The look of the strips of people in `[pool.people]`: that of a place, and how they look talking and how loud."""
APP_OPTIONS = frozenset({"encoder", "min_volume", "max_volume"})
"""
Options of an `apps` or `auto` place for the applications without a channel it shows (an `encoder` that acts on the
application: `pick`, `media`, `volume`, `balance`); a channel's controls belong to the channel, the controls that
belong to the slot whatever it shows are in `[controls]`.
"""
DEVICE_OPTIONS = frozenset({"encoder", "min_volume", "max_volume", "select"})
"""Options of a `devices` place for the devices it shows (`encoder`: `volume` or `balance`; `select`)."""
CONTROLS = ("fader", "encoder", "select", "rec", "solo")
"""What `[controls]` can claim of a slot (not Mute: it stays with what the slot shows)."""
CONTROL_ACTIONS = re.compile(r"homeassistant|cycle_modes|mode:[a-z0-9_]+|toggle:[a-z0-9_]+")
"""The actions of a claimed button that are text; a launch is a table."""

_ID = re.compile(r"[a-z0-9_]+")


class _Section(BaseModel):
    # the docstrings of the fields are their descriptions, which the GUI shows as help
    model_config = ConfigDict(extra="forbid", frozen=True, use_attribute_docstrings=True)


class _Open(BaseModel):
    # the options of the strip that shows it (color, label, ...) are checked as those of a strip
    model_config = ConfigDict(extra="allow", frozen=True, use_attribute_docstrings=True)


def _presets_of(kind: Kind) -> AfterValidator:
    """Checks the presets of a list (unknown ones, or ones for another kind of list, are errors); keeps the list."""

    def check(value: tuple[str, ...]) -> tuple[str, ...]:
        expand(value, kind)
        return value

    return AfterValidator(check)


Streams = Annotated[tuple[str, ...], Presets(Kind.STREAMS), _presets_of(Kind.STREAMS)]
"""Parts of names of applications, and presets of them (`@browsers`)."""
Processes = Annotated[tuple[str, ...], Presets(Kind.PROCESSES), _presets_of(Kind.PROCESSES)]
"""Parts of names of processes, and presets of them (`@steam-games`)."""


class ChannelConfig(_Open):
    type: Literal["output", "input", "apps", "homeassistant", "person"]
    tags: tuple[str, ...] = ()
    """Words that group channels, for the conditions of slots (`present`) and the pools that take them."""
    in_pool: bool = True
    """
    While no slot shows the channel, its pool hands it out: an `apps` channel like an application (`apps`, `auto`),
    a `person` channel as one of the people (`people`, `auto`).
    """
    match: Streams = ()
    device: str | tuple[str, ...] | None = None
    choices: tuple[dict[str, Any], ...] = ()
    person: str | tuple[str, ...] | None = None
    absent_after: float | None = None
    """Seconds the channel stays present after it had nothing to control any more; by default 3."""

    @model_validator(mode="before")
    @classmethod
    def _old_spellings(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and "in_auto" in data:
            raise ValueError("in_auto is in_pool now")
        return data

    @model_validator(mode="after")
    def _of_its_type(self) -> ChannelConfig:
        if self.type == "apps" and not self.match:
            raise ValueError("an apps channel needs match")
        if self.type == "person" and not self.person:
            raise ValueError("a person channel needs person")
        return self

    @property
    def streams(self) -> tuple[str, ...]:
        """The parts of application names it takes (presets expanded)."""
        return expand(self.match, Kind.STREAMS)

    @property
    def devices(self) -> tuple[str, ...]:
        """The device names and patterns of an output or input: `device`, or those of its choices; () for any."""
        if self.choices:
            return tuple(str(choice["device"]) for choice in self.choices)
        if self.device is None:
            return ()
        return (self.device,) if isinstance(self.device, str) else self.device

    @property
    def people(self) -> tuple[str, ...]:
        if self.person is None:
            return ()
        return (self.person,) if isinstance(self.person, str) else self.person


Side = Literal["left", "right"]
"""The side a pool fills its slots from."""
SIDES = Meanings({"left": "Slot 1 first.", "right": "Slot 8 first."})


class PoolConfig(_Open):
    """`[pool.<id>]`: a pool of channels."""

    channels: tuple[str, ...] = ()
    """The channels the pool hands out, by id or tag, in this order."""
    from_: Annotated[Side, SIDES] = Field("left", alias="from")
    """The side the pool fills its slots from."""

    @model_validator(mode="before")
    @classmethod
    def _of_channels(cls, data: Any) -> Any:
        _refuse(data, {"exclude": "an option of [pool.apps]", "hold": "an option of [pool.apps]"})
        _refuse(data, {"order": "an option of [pool.people]"})
        return data


class AppsConfig(_Open):
    """`[pool.apps]`: the applications that play and have no slot, and the look of their strips."""

    from_: Annotated[Side, SIDES] = Field("left", alias="from")
    """The side the applications fill their slots from, in `apps` and in `auto`."""
    exclude: Streams = AUTO_EXCLUDE
    """Applications that never get a slot of `apps` or `auto`."""
    hold: float = 5.0
    """Seconds a slot keeps an application after it stopped playing."""

    @model_validator(mode="before")
    @classmethod
    def _of_apps(cls, data: Any) -> Any:
        _refuse(
            data, {"channels": "apps takes the applications without a channel", "order": "an option of [pool.people]"}
        )
        return data


class PeopleConfig(_Open):
    """`[pool.people]`: the people of the voice chat, their order and the look of their strips."""

    from_: Annotated[Side, SIDES] = Field("right", alias="from")
    """The side the people fill their slots from, in `people` and in `auto`."""
    order: tuple[str, ...] = ()
    """
    The people by name or `person` channel, before the others. Those sit in the order they were first seen.
    """

    @model_validator(mode="before")
    @classmethod
    def _of_people(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and ("launch" in data or "launch_when_running" in data):
            raise ValueError("launch: the strips of people have none; a launch is a control of a slot ([controls])")
        if isinstance(data, Mapping) and "label" in data:
            raise ValueError("label: only on a person channel; the strips of people show their names")
        _refuse(
            data,
            {
                "channels": "people takes the people of the voice chat",
                "exclude": "an option of [pool.apps]",
                "hold": "people stay absent_after seconds after they left",
            },
        )
        return data


class AutoConfig(_Open):
    """
    `[pool.auto]`: the look of the strips of the applications on its slots. The people on them look as
    `[pool.people]` says.
    """

    @model_validator(mode="before")
    @classmethod
    def _of_auto(cls, data: Any) -> Any:
        _refuse(
            data,
            {
                "exclude": "an option of [pool.apps] now",
                "hold": "an option of [pool.apps] now",
                "from": "auto fills from the sides of [pool.apps] and [pool.people]",
                "order": "an option of [pool.people]",
                "channels": "auto takes the applications and the people",
            },
        )
        return data


class DevicesConfig(_Open):
    """`[pool.devices]`: the outputs and inputs that no channel has, and the look of their strips."""

    from_: Annotated[Side, SIDES] = Field("left", alias="from")
    """The side the devices fill their slots from."""
    exclude: tuple[str, ...] = ()
    """Devices that never get a slot of `devices`, by node name or description; `*` and `?` are wildcards."""
    hold: float = 5.0
    """Seconds a slot keeps a device after it went, e.g. while Bluetooth headphones reconnect."""

    @field_validator("exclude", mode="before")
    @classmethod
    def _one_or_several(cls, value: object) -> object:
        return (value,) if isinstance(value, str) else value

    @model_validator(mode="before")
    @classmethod
    def _of_devices(cls, data: Any) -> Any:
        _refuse(
            data,
            {
                "channels": "devices takes the outputs and inputs without a channel",
                "order": "an option of [pool.people]",
            },
        )
        return data


type Pool = PoolConfig | AppsConfig | PeopleConfig | AutoConfig | DevicesConfig


def _refuse(data: Any, options: Mapping[str, str]) -> None:
    """Refuses the options of `options` with their reasons, e.g. `hold` in `[pool.people]`."""
    if not isinstance(data, Mapping):
        return
    for name, reason in options.items():
        if name in data:
            raise ValueError(f"{name}: {reason}")


class Launch(_Section):
    launch: Annotated[tuple[str, ...], Field(min_length=1)]
    launch_when_running: bool = False


class ControlsConfig(_Section):
    """
    Controls of a slot that act whatever it shows (`[controls]`), while `when` holds; of a list of them per slot the
    first whose `when` holds.
    """

    fader: Literal["homeassistant"] | None = None
    encoder: Literal["homeassistant"] | None = None
    select: str | Launch | None = None
    rec: str | Launch | None = None
    solo: str | Launch | None = None
    when: str | None = None
    id: str | None = None
    """Names the Home Assistant entities of the slot's controls; by default `slot_<n>`."""

    @property
    def claimed(self) -> tuple[str, ...]:
        return tuple(name for name in CONTROLS if getattr(self, name) is not None)


class StateConfig(_Section):
    mode: bool = False
    """It is a mode: one mode is on at a time, the one with the highest `priority` whose sources are on."""
    label: str | None = None
    """What the LCDs show across the strips when the mode comes; by default its name."""
    priority: int = 0
    """Of several modes whose sources are on, the one with the highest priority is on."""
    apps: Streams = ()
    """On while one of these applications plays."""
    recording: Streams = ()
    """On while one of these applications records, e.g. with an open microphone."""
    voice_chat: bool = False
    """On while you are in a channel of the voice chat."""
    processes: Processes = ()
    """On while a process of one of these names runs."""
    devices: tuple[str, ...] = ()
    """On while one of these devices (outputs or inputs) is there."""
    channels: tuple[str, ...] = ()
    """On while one of these channels is present."""
    homeassistant: bool = False
    """On while its switch in Home Assistant is on. Needs `[mqtt]`."""
    when: str | None = None
    """On while this condition of other states holds, e.g. `call and not gaming`. Instead of sources."""
    delay_on: float = 0.0
    """Seconds its sources must be on before the state is."""
    delay_off: float | None = None
    """Seconds the state stays on after its sources went off; by default 3, for modes 10."""
    persist: bool = False
    """An override lasts until you set it back, not only until the sources change."""

    @model_validator(mode="after")
    def _composed_or_sourced(self) -> StateConfig:
        if self.when is not None and self.has_sources:
            raise ValueError("when is not together with other sources: a state is either composed or has sources")
        return self

    @property
    def has_sources(self) -> bool:
        return bool(
            self.apps
            or self.recording
            or self.voice_chat
            or self.processes
            or self.devices
            or self.channels
            or self.homeassistant
        )


class _File(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    channel: dict[str, ChannelConfig] = {}
    pool: dict[str, dict[str, Any]] = {}
    """Checked by `_parse_pools()`: each built-in pool has options of its own."""
    people: dict[str, Any] | None = None
    """Today's `[pool.people]`, refused with a pointer to it."""
    state: dict[str, StateConfig] = {}
    slots: dict[str, str | list[str | dict[str, Any]]] = {}
    controls: dict[str, dict[str, Any] | list[dict[str, Any]]] = {}
    """Checked by `_parse_controls()`, so that problems name their place (`controls.4`, `controls.4[1]`)."""


@dataclass(frozen=True)
class Candidate:
    """One entry of a stack: a channel or pool (None: `"-"`, nothing), maybe with a condition and options."""

    show: str | None
    when: Condition | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        shown = "-" if self.show is None else self.show
        return shown if self.when is None else f"{shown} if {self.when.text}"


@dataclass(frozen=True)
class Scene:
    """The checked configuration: channels, pools and states by id, and a stack per slot (1..8)."""

    channels: Mapping[str, ChannelConfig]
    pools: Mapping[str, Pool]
    """Every pool by id: the built-in ones (`auto`, `apps`, `people`) and the pools of channels."""
    states: Mapping[str, StateConfig]
    stacks: Mapping[int, tuple[Candidate, ...]]
    conditions: Mapping[str, Condition]
    """The conditions of composed states (`when`), by state."""
    controls: Mapping[int, tuple[ControlsConfig, ...]] = field(default_factory=dict)
    """The claimed controls by slot (1..8), in their order: the first whose `when` holds acts."""
    control_conditions: Mapping[tuple[int, int], Condition] = field(default_factory=dict)
    """Their `when`, by slot and index."""

    @classmethod
    def of(cls, data: Mapping[str, Any], chord: tuple[tuple[int, ...], str] | None = None) -> Scene:
        """
        From the data of a file; ConfigError with every problem it has. `chord` is the one of `[switching]`, its
        strips (from 1) and action, checked against the modes, states and `[controls]`.
        """
        try:
            file = _File.model_validate(data)
        except ValidationError as e:
            raise ConfigError("\n".join(_message(error) for error in e.errors())) from e
        problems: list[str] = []
        if file.people is not None:
            problems.append(
                "people: the section is [pool.people] now; the people sit on the slots whose stack names people or auto"
            )
        pools = _parse_pools(file.pool, problems)
        _check_ids(file, problems)
        conditions = _parse_conditions(file.state, problems)
        stacks = _parse_stacks(file.slots, file.channel, pools, problems)
        _check_chains(stacks, pools, problems)
        controls, control_conditions = _parse_controls(file, stacks, problems)
        if chord is not None:
            strips, action = chord
            _check_action("switching.chord.action", action, file, problems, chord=True)
            for slot in strips:
                if any(entry.solo is not None for entry in controls.get(slot, ())):
                    problems.append(
                        f"controls.{slot}.solo: the Solo buttons of the chord can't be claimed (switching.chord)"
                    )
        scene = cls(file.channel, pools, file.state, stacks, conditions, controls, control_conditions)
        scene._check_references(problems)
        if not problems:
            _check_loops(conditions, problems)
        if problems:
            raise ConfigError("\n".join(problems))
        return scene

    @property
    def modes(self) -> tuple[str, ...]:
        """The modes in the order of the file, without `default`."""
        return tuple(name for name, state in self.states.items() if state.mode)

    @property
    def apps(self) -> AppsConfig:
        pool = self.pools[APPS]
        assert isinstance(pool, AppsConfig)
        return pool

    @property
    def people(self) -> PeopleConfig:
        pool = self.pools[PEOPLE]
        assert isinstance(pool, PeopleConfig)
        return pool

    @property
    def devices(self) -> DevicesConfig:
        pool = self.pools[DEVICES]
        assert isinstance(pool, DevicesConfig)
        return pool

    def channels_of(self, pool: str) -> tuple[str, ...]:
        """The channels of a pool of channels, in its order; none for the built-in pools."""
        config = self.pools[pool]
        return self.members_of(config.channels) if isinstance(config, PoolConfig) else ()

    def side(self, pool: str) -> Literal["left", "right"]:
        """The side a pool of channels, `apps` or `people` fills its slots from."""
        config = self.pools[pool]
        assert not isinstance(config, AutoConfig), "auto fills from the sides of apps and people"
        return config.from_

    def members_of(self, entries: Iterable[str]) -> tuple[str, ...]:
        """The channels of a list of ids and `#tags`, in its order (a tag's in the order of the file)."""
        result: dict[str, None] = {}
        for entry in entries:
            if entry.startswith("#"):
                result.update((name, None) for name, channel in self.channels.items() if entry[1:] in channel.tags)
            else:
                result[entry] = None
        return tuple(result)

    def _check_references(self, problems: list[str]) -> None:
        states = {*self.states, DEFAULT}
        known = {*self.channels, *self.pools}
        tags = {tag for channel in self.channels.values() for tag in channel.tags}
        uses: list[tuple[str, Condition]] = [
            (f"state.{name}.when", condition) for name, condition in self.conditions.items()
        ]
        uses += [
            (f"{_control_place(slot, index, len(self.controls[slot]))}.when", condition)
            for (slot, index), condition in self.control_conditions.items()
        ]
        uses += [
            (f"slots.{slot}[{index}]", candidate.when)
            for slot, stack in self.stacks.items()
            for index, candidate in enumerate(stack)
            if candidate.when is not None
        ]
        for where, condition in uses:
            for name in sorted(condition.states - states):
                problems.append(f'{where}: "{condition.text}": unknown state {name}{_did_you_mean(name, states)}')
            for target in sorted(t for t in condition.presence if t is not None and t not in known):
                problems.append(f'{where}: "{condition.text}": {target} is no channel or pool')
            if where.startswith("state.") and condition.presence:
                problems.append(
                    f'{where}: "{condition.text}": present is only for candidates of slots, a state '
                    "takes channels with its source channels"
                )
            if where.startswith("controls.") and condition.presence:
                problems.append(f'{where}: "{condition.text}": present is only for candidates of slots')
        lists = [
            (f"pool.{name}.channels", pool.channels)
            for name, pool in self.pools.items()
            if isinstance(pool, PoolConfig)
        ]
        lists += [(f"state.{name}.channels", state.channels) for name, state in self.states.items()]
        for where, entries in lists:
            for entry in entries:
                if entry.startswith("#") and entry[1:] not in tags:
                    problems.append(f"{where}: no channel has the tag {entry[1:]}")
                elif not entry.startswith("#") and entry not in self.channels:
                    problems.append(f"{where}: {entry} is no channel")
        owners: dict[str, str] = {}
        for name, channel in self.channels.items():
            for person in channel.people:
                other = owners.setdefault(person.lower(), name)
                if other != name:
                    problems.append(f"channel.{name}: {person} is also a person of channel {other}")


def _parse_pools(raw: Mapping[str, Mapping[str, Any]], problems: list[str]) -> dict[str, Pool]:
    """The pools of the file, the built-in ones with their defaults: each built-in pool has options of its own."""
    pools: dict[str, Pool] = {}
    models: dict[str, type[Pool]] = {AUTO: AutoConfig, APPS: AppsConfig, PEOPLE: PeopleConfig, DEVICES: DevicesConfig}
    for name in (*BUILT_IN, *(name for name in raw if name not in BUILT_IN)):
        model = models.get(name, PoolConfig)
        try:
            pools[name] = model.model_validate(raw.get(name, {}))
        except ValidationError as e:
            for error in e.errors():
                where = ".".join(("pool", name, *(str(part) for part in error["loc"])))
                problems.append(f"{where}: {error['msg'].removeprefix('Value error, ')}")
            # still a pool: the slots that show it have no problems of their own
            pools[name] = model.model_validate({})
            continue
        if name in BUILT_IN:
            # the rest is the look of its strips: what a place of it takes
            own = {field.alias or key for key, field in model.model_fields.items()}
            look = {key: value for key, value in raw.get(name, {}).items() if key not in own}
            allowed = PEOPLE_POOL_OPTIONS if name == PEOPLE else place_options(name)
            problems.extend(
                f"pool.{name}: {problem}" for problem in _look_problems(name, look, allowed, f"[pool.{name}]")
            )
    return pools


def _parse_conditions(states: Mapping[str, StateConfig], problems: list[str]) -> dict[str, Condition]:
    conditions: dict[str, Condition] = {}
    for name, state in states.items():
        if state.when is not None:
            condition = _condition(f"state.{name}.when", state.when, problems)
            if condition is not None:
                conditions[name] = condition
    return conditions


def _parse_stacks(
    slots: Mapping[str, str | list[str | dict[str, Any]]],
    channels: Mapping[str, ChannelConfig],
    pools: Mapping[str, Pool],
    problems: list[str],
) -> dict[int, tuple[Candidate, ...]]:
    stacks: dict[int, tuple[Candidate, ...]] = {}
    for key, value in slots.items():
        if not key.isdigit() or not 1 <= int(key) <= protocol.STRIPS:
            problems.append(f"slots.{key}: a slot is a number from 1 to {protocol.STRIPS}")
            continue
        entries = [value] if isinstance(value, str) else value
        candidates = [
            _candidate(f"slots.{key}[{index}]", entry, channels, pools, problems) for index, entry in enumerate(entries)
        ]
        stacks[int(key)] = tuple(candidate for candidate in candidates if candidate is not None)
    for slot in range(1, protocol.STRIPS + 1):
        stack = stacks.get(slot, ())
        # a stack that can run out (its last candidate has a condition, or is a channel another slot may get) ends
        # in auto; "-" at the end makes the slot dark instead
        last = stack[-1] if stack else None
        if last is None or last.when is not None or (last.show is not None and last.show not in pools):
            stack = (*stack, Candidate(AUTO))
        stacks[slot] = stack
    return stacks


def _candidate(
    where: str,
    entry: str | dict[str, Any],
    channels: Mapping[str, ChannelConfig],
    pools: Mapping[str, Pool],
    problems: list[str],
) -> Candidate | None:
    if isinstance(entry, str):
        show, _, when = entry.partition(" if ")
        options: dict[str, Any] = {}
    else:
        options = dict(entry)
        show = options.pop("show", None)
        when = str(options.pop("when", ""))
        if not isinstance(show, str):
            problems.append(f"{where}: a candidate in table form needs show")
            return None
    show = show.strip()
    condition = _condition(where, when, problems) if when.strip() else None
    if show == "-":
        if options:
            problems.append(f"{where}: - (nothing) takes no options")
        if condition is not None and None in condition.presence:
            problems.append(f'{where}: "{condition.text}": present of - (nothing) means nothing')
        return Candidate(None, condition)
    if show not in channels and show not in pools:
        problems.append(f"{where}: {show} is no channel or pool")
        return None
    problems.extend(
        f"{where}: {problem}" for problem in _look_problems(show, options, place_options(show), f"a place for {show}")
    )
    return Candidate(show, condition, options)


def _look_problems(show: str, options: Mapping[str, Any], allowed: frozenset[str], what: str) -> list[str]:
    """
    What is wrong with the options of a place of `show`, or of the built-in pool `show` (`what` says which): the
    `allowed` ones only, and no control of Home Assistant, which belongs to the slot.
    """
    problems: list[str] = []
    for option in sorted(set(options) - allowed):
        if show == PEOPLE and option == "label":
            why = " (only on a person channel; the strips of people show their names)"
        elif show == DEVICES and option == "label":
            why = " (its strips show the names of their devices)"
        elif option == "label":
            why = " (its strips show the names of their applications; [aliases] renames them)"
        elif show == PEOPLE and option in LOOK_OPTIONS | APP_OPTIONS:
            why = " (the strips of people show their names; people have no Rec, Solo or encoder of a place)"
        elif option in APP_OPTIONS:
            why = " (it belongs to the channel)"
        elif option in {*CONTROLS, "launch", "launch_when_running", "id"}:
            why = " (a control of the slot: [controls])"
        else:
            why = ""
        problems.append(f"{option} is no option of {what}{why}")
    if options.get("encoder") == "homeassistant":
        problems.append('encoder = "homeassistant" is a control of the slot: [controls]')
    return problems


def place_options(show: str) -> frozenset[str]:
    """
    The options a place takes for what it shows: its look, and for `apps`, `auto` and `devices` how it acts on what it
    shows (the encoder, the volume range).
    """
    if show == PEOPLE:
        return PEOPLE_LOOK_OPTIONS
    if show == DEVICES:
        return (LOOK_OPTIONS - {"label"}) | DEVICE_OPTIONS
    if show in (APPS, AUTO):
        return (LOOK_OPTIONS - {"label"}) | APP_OPTIONS
    return LOOK_OPTIONS


def _check_chains(stacks: Mapping[int, tuple[Candidate, ...]], pools: Mapping[str, Pool], problems: list[str]) -> None:
    """
    A pool hands a slot it has no member for to the pool right below it: a pool of channels comes before the
    built-in pools there, since those take the channels that no pool of channels gives a slot.
    """
    for slot, stack in stacks.items():
        built_in: str | None = None
        for index, candidate in enumerate(stack):
            if candidate.show is None or candidate.show not in pools:
                built_in = None
            elif candidate.show in BUILT_IN:
                built_in = built_in or candidate.show
            elif built_in is not None:
                problems.append(
                    f"slots.{slot}[{index}]: {candidate.show} below {built_in}: a pool of channels goes above the "
                    "pools auto, apps, people and devices"
                )


def _check_ids(file: _File, problems: list[str]) -> None:
    seen: dict[str, str] = {}
    sections = (("channel", file.channel), ("pool", file.pool), ("state", file.state))
    for section, names in sections:
        for name in names:
            where = f"{section}.{name}"
            if not _ID.fullmatch(name):
                problems.append(f"{where}: an id is lower case letters, digits and _")
            elif name in RESERVED or name == DEFAULT or name.startswith(("state_", "slot_")):
                problems.append(f"{where}: {name} is reserved")
            elif section != "pool" and name in BUILT_IN:
                problems.append(f"{where}: {name} is a built-in pool")
            other = seen.setdefault(name, section)
            if other != section:
                problems.append(f"{where}: {name} is also a {other}; channels, pools and states share their ids")


def _control_place(slot: int, index: int, count: int) -> str:
    """Where a control is in the file: `controls.4`, or `controls.4[1]` in a list."""
    return f"controls.{slot}" if count == 1 else f"controls.{slot}[{index}]"


def _check_action(where: str, action: str, file: _File, problems: list[str], chord: bool = False) -> None:
    """An action of a button: of `[controls]`, or of the chord (no `homeassistant` there)."""
    modes = {name for name, state in file.state.items() if state.mode} | {DEFAULT}
    if not CONTROL_ACTIONS.fullmatch(action) or (chord and action == "homeassistant"):
        actions = "cycle_modes, mode:<id>, toggle:<state or mode>"
        problems.append(
            f"{where}: {action} is no action ({actions})"
            if chord
            else f"{where}: {action} is no action (homeassistant, {actions}, or {{ launch = [...] }})"
        )
    elif action.startswith("mode:") and action[5:] not in modes:
        problems.append(f"{where}: {action}: no mode {action[5:]}")
    elif action.startswith("toggle:") and action[7:] not in file.state:
        problems.append(f"{where}: {action}: no state or mode {action[7:]}")


def _parse_controls(
    file: _File, stacks: Mapping[int, tuple[Candidate, ...]], problems: list[str]
) -> tuple[dict[int, tuple[ControlsConfig, ...]], dict[tuple[int, int], Condition]]:
    """
    `[controls]` by slot, with their conditions. Their `id`s name entities like channel ids: in the same namespace,
    each on one slot only (the controls of a slot may share one); a candidate of a slot can't set the LED of a button
    one of the slot's controls claims.
    """
    controls: dict[int, tuple[ControlsConfig, ...]] = {}
    conditions: dict[tuple[int, int], Condition] = {}
    seen: dict[str, int] = {}
    taken = {*file.channel, *file.pool, *file.state, *BUILT_IN, DEFAULT}
    for key, value in file.controls.items():
        if not key.isdigit() or not 1 <= int(key) <= protocol.STRIPS:
            problems.append(f"controls.{key}: a slot is a number from 1 to {protocol.STRIPS}")
            continue
        slot = int(key)
        raw = value if isinstance(value, list) else [value]
        entries: list[ControlsConfig] = []
        for index, data in enumerate(raw):
            where = _control_place(slot, index, len(raw))
            try:
                config = ControlsConfig.model_validate(data)
            except ValidationError as e:
                problems.extend(f"{where}.{_message(error)}".replace(f"{where}.:", f"{where}:") for error in e.errors())
                continue
            entries.append(config)
            if not config.claimed:
                problems.append(f"{where}: claims nothing (fader, encoder, select, rec, solo)")
            for name in ("select", "rec", "solo"):
                action = getattr(config, name)
                if isinstance(action, str):
                    _check_action(f"{where}.{name}", action, file, problems)
            if config.when is not None:
                condition = _condition(f"{where}.when", config.when, problems)
                if condition is not None:
                    conditions[(slot, index)] = condition
            if config.id is not None:
                _check_control_id(where, slot, config, taken, seen, problems)
            for position, candidate in enumerate(stacks.get(slot, ())):
                for button in ("rec", "solo"):
                    if button in candidate.options and getattr(config, button) is not None:
                        problems.append(
                            f"slots.{slot}[{position}]: {button}: the slot's controls claim it ([controls])"
                        )
        controls[slot] = tuple(entries)
    return controls, conditions


def _check_control_id(
    where: str, slot: int, config: ControlsConfig, taken: set[str], seen: dict[str, int], problems: list[str]
) -> None:
    name = config.id
    assert name is not None
    if "homeassistant" not in (getattr(config, control) for control in CONTROLS):
        problems.append(f"{where}.id: names Home Assistant entities, but no control is for Home Assistant")
    if not _ID.fullmatch(name):
        problems.append(f"{where}.id: {name}: an id is lower case letters, digits and _")
    elif name in RESERVED or name.startswith(("state_", "slot_")):
        problems.append(f"{where}.id: {name} is reserved")
    elif name in taken:
        problems.append(f"{where}.id: {name} is also a channel, pool or state; they share their ids")
    other = seen.setdefault(name, slot)
    if other != slot:
        problems.append(f"{where}.id: {name} is also the id of controls of slot {other}")


def _check_loops(conditions: Mapping[str, Condition], problems: list[str]) -> None:
    done: set[str] = set()

    def visit(name: str, path: tuple[str, ...]) -> None:
        if name in path:
            loop = path[path.index(name) :]
            problems.append(f"states that refer to each other: {' -> '.join((*loop, name))}")
            return
        if name in done or name not in conditions:
            return
        for other in sorted(conditions[name].states):
            visit(other, (*path, name))
        done.add(name)

    for name in conditions:
        visit(name, ())


def _condition(where: str, text: str, problems: list[str]) -> Condition | None:
    try:
        return parse(text.strip())
    except ExpressionError as e:
        problems.append(f"{where}: {e} (at {e.position + 1})")
        return None


def _did_you_mean(name: str, known: Iterable[str]) -> str:
    close = difflib.get_close_matches(name, sorted(known), n=1)
    return f" (did you mean {close[0]}?)" if close else ""


def _message(error: Any) -> str:
    where = ".".join(str(part) for part in error["loc"])
    # pydantic puts "Value error, " before the messages of the validators
    return f"{where}: {error['msg'].removeprefix('Value error, ')}"
