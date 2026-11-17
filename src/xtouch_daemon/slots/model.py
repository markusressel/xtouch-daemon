"""
The configuration of channels, pools, people, states, slots and controls, and its checks: `Scene.of()` reads the
sections `[channel.*]`, `[pool.*]`, `[people]`, `[state.*]`, `[slots]` and `[controls]` of a file (other sections
are not its business).
"""

import difflib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.presets import Kind, expand
from xtouch_daemon.hardware import protocol
from xtouch_daemon.slots.expressions import RESERVED, Condition, ExpressionError, parse

AUTO = "auto"
PEOPLE = "people"
"""The people in the voice chat: no pool and no candidate, they share the slots of `auto`."""
DEFAULT = "default"
BUILT_IN = (AUTO, PEOPLE)
AUTO_EXCLUDE = ("speech-dispatcher",)
"""What `auto` never takes unless `[pool.auto] exclude` says otherwise: the voice of screen readers."""

STATE_DELAY_OFF = 3.0
"""Seconds a state stays on after its sources stopped (`behavior.state_delay_off`)."""
MODE_DELAY_OFF = 10.0
"""The same for modes (today's `switching.hold`)."""
ABSENT_AFTER = 3.0
"""Seconds a channel stays present after it had nothing to control any more (`behavior.absent_after`)."""

LOOK_OPTIONS = frozenset({"label", "color", "lit_when_idle", "rec", "solo", "meter", "meter_point"})
"""Options of a place that change only how a candidate looks there."""
APP_OPTIONS = frozenset({"encoder", "min_volume", "max_volume"})
"""
Options of an `auto` place for the applications without a channel it shows (an `encoder` that acts on the
application: `pick`, `media`, `volume`, `balance`); a channel's controls belong to the channel, the controls that
belong to the slot whatever it shows are in `[controls]`.
"""
CONTROLS = ("fader", "encoder", "select", "rec", "solo")
"""What `[controls]` can claim of a slot (not Mute: it stays with what the slot shows)."""
CONTROL_ACTIONS = re.compile(r"homeassistant|cycle_modes|mode:[a-z0-9_]+|toggle:[a-z0-9_]+")
"""The actions of a claimed button that are text; a launch is a table."""

_ID = re.compile(r"[a-z0-9_]+")


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Open(BaseModel):
    # the options the prototype doesn't use (color, label, ...) are those of today's strips
    model_config = ConfigDict(extra="allow", frozen=True)


class ChannelConfig(_Open):
    type: Literal["output", "input", "apps", "homeassistant", "person"]
    tags: tuple[str, ...] = ()
    in_auto: bool = True
    match: tuple[str, ...] = ()
    device: str | tuple[str, ...] | None = None
    choices: tuple[dict[str, Any], ...] = ()
    person: str | tuple[str, ...] | None = None
    absent_after: float | None = None

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


class PoolConfig(_Open):
    channels: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    hold: float = 5.0


class PeopleConfig(_Open):
    """`[people]`: the look of their strips (the options of today's `voip` strips) and their order."""

    @model_validator(mode="before")
    @classmethod
    def _no_launch(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and ("launch" in data or "launch_when_running" in data):
            raise ValueError("launch: the strips of people have none; a launch is a control of a slot ([controls])")
        return data

    order: tuple[str, ...] = ()
    """
    The order of the people from the right: names, or ids of `person` channels; before those learned (who was seen
    first).
    """


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
    label: str | None = None
    priority: int = 0
    apps: tuple[str, ...] = ()
    recording: tuple[str, ...] = ()
    voice_chat: bool = False
    processes: tuple[str, ...] = ()
    devices: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    homeassistant: bool = False
    when: str | None = None
    delay_on: float = 0.0
    delay_off: float | None = None
    persist: bool = False

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
    pool: dict[str, PoolConfig] = {}
    people: PeopleConfig = PeopleConfig()
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
    pools: Mapping[str, PoolConfig]
    people: PeopleConfig
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
        auto = file.pool.get(AUTO, PoolConfig())
        if "exclude" not in auto.model_fields_set:
            auto = auto.model_copy(update={"exclude": AUTO_EXCLUDE})
        pools = {**file.pool, AUTO: auto}
        problems: list[str] = []
        _check_ids(file, problems)
        conditions = _parse_conditions(file.state, problems)
        stacks = _parse_stacks(file.slots, file.channel, pools, problems)
        controls, control_conditions = _parse_controls(file, stacks, problems)
        if chord is not None:
            strips, action = chord
            _check_action("switching.chord.action", action, file, problems, chord=True)
            for slot in strips:
                if any(entry.solo is not None for entry in controls.get(slot, ())):
                    problems.append(
                        f"controls.{slot}.solo: the Solo buttons of the chord can't be claimed (switching.chord)"
                    )
        scene = cls(file.channel, pools, file.people, file.state, stacks, conditions, controls, control_conditions)
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
        lists = [(f"pool.{name}.channels", pool.channels) for name, pool in self.pools.items()]
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
    pools: Mapping[str, PoolConfig],
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
    pools: Mapping[str, PoolConfig],
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
    if show == PEOPLE:
        problems.append(f"{where}: people is no candidate: the people share the slots of auto (see [people])")
        return None
    if show not in channels and show not in pools:
        problems.append(f"{where}: {show} is no channel or pool")
        return None
    allowed = LOOK_OPTIONS | (APP_OPTIONS if show == AUTO else frozenset())
    for option in sorted(set(options) - allowed):
        if option in APP_OPTIONS:
            why = " (it belongs to the channel)"
        elif option in {*CONTROLS, "launch", "launch_when_running", "id"}:
            why = " (a control of the slot: [controls])"
        else:
            why = ""
        problems.append(f"{where}: {option} is no option of a place for {show}{why}")
    if options.get("encoder") == "homeassistant":
        problems.append(f'{where}: encoder = "homeassistant" is a control of the slot: [controls]')
    return Candidate(show, condition, options)


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
            elif name == PEOPLE:
                problems.append(f"{where}: people is built in: [people]")
            elif section != "pool" and name == AUTO:
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
    return f"{where}: {error['msg']}"
