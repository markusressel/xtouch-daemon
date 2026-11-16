"""
The states and modes: their sources in an observation, their delays, the overrides, the mode that is on, and the
composed states. Pure: the caller passes the time.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from xtouch_daemon.config.presets import Kind, expand
from xtouch_daemon.slots.inputs import Observation, app_matches, device_matches
from xtouch_daemon.slots.model import DEFAULT, MODE_DELAY_OFF, STATE_DELAY_OFF, Scene, StateConfig
from xtouch_daemon.slots.timing import Delayed


class Override(StrEnum):
    AUTO = "auto"
    ON = "on"
    OFF = "off"


@dataclass(frozen=True)
class States:
    """The value of every state and mode (and `default`) at a moment, and why."""

    values: Mapping[str, bool]
    mode: str
    """The mode that is on, `default` without another one."""
    reasons: Mapping[str, str]
    """What turned each state that is on on: a source (`discord records`), `override`, a mode pick, `when`."""
    since: Mapping[str, float]
    """When each state (and mode) got its value."""


def source(
    state: StateConfig, name: str, observation: Observation, present: frozenset[str], scene: Scene
) -> str | None:
    """What of its sources is on now (e.g. `discord records`), None if none is."""
    for app in observation.playing:
        if app_matches(app, expand(state.apps, Kind.STREAMS)):
            return f"{app} plays"
    for app in observation.recording:
        if app_matches(app, expand(state.recording, Kind.STREAMS)):
            return f"{app} records"
    if state.voice_chat and observation.voice_chat:
        return "in a voice chat"
    for process in sorted(observation.processes):
        if app_matches(process, expand(state.processes, Kind.PROCESSES)):
            return f"{process} runs"
    for pattern in state.devices:
        for device in sorted(observation.devices):
            if device_matches(device, pattern):
                return f"{device} is there"
    for channel in scene.members_of(state.channels):
        if channel in present:
            return f"{channel} is present"
    if state.homeassistant and name in observation.homeassistant:
        return "Home Assistant"
    return None


class StateEngine:
    """
    Evaluates the states at each update. `overrides` and `mode_pick` are the ones kept from before a restart: the
    first update is the baseline (no delays, no edge), so they survive it.
    """

    def __init__(self, scene: Scene, overrides: Mapping[str, Override] | None = None, mode_pick: str | None = None):
        self.scene = scene
        self.overrides: dict[str, Override] = {
            name: value for name, value in (overrides or {}).items() if value is not Override.AUTO
        }
        self.mode_pick = mode_pick
        """The mode picked by hand (`select.xtouch_mode`), None for `auto`."""
        self._delayed = {
            name: Delayed(
                state.delay_on,
                state.delay_off if state.delay_off is not None else MODE_DELAY_OFF if state.mode else STATE_DELAY_OFF,
            )
            for name, state in scene.states.items()
        }
        self._order = composed_order(scene)
        self._since: dict[str, float] = {}
        self._last: dict[str, bool] = {}
        self._reasons: dict[str, str] = {}

    def set_override(self, name: str, value: Override) -> None:
        """Takes effect at the next update, past the delays."""
        assert not self.scene.states[name].mode, "modes are picked with pick_mode()"
        if value is Override.AUTO:
            self.overrides.pop(name, None)
        else:
            self.overrides[name] = value

    def pick_mode(self, mode: str | None) -> None:
        """A mode by hand, or None for `auto` (the rules decide)."""
        assert mode is None or mode == DEFAULT or mode in self.scene.modes, f"no mode {mode}"
        self.mode_pick = mode

    def update(self, observation: Observation, present: frozenset[str], now: float) -> States:
        values: dict[str, bool] = {}
        reasons: dict[str, str] = {}
        rule_changed = False
        # the states with sources, modes included: their delays, and the end of overrides at an edge
        for name, state in self.scene.states.items():
            if name in self.scene.conditions:
                continue
            why = source(state, name, observation, present, self.scene)
            delayed = self._delayed[name]
            edge = delayed.update(why is not None, now)
            if why is not None:
                self._reasons[name] = why
            if edge and state.mode:
                rule_changed = True
            if edge and not state.persist:
                self.overrides.pop(name, None)
            values[name] = delayed.value
            reasons[name] = self._reasons.get(name, "") if delayed.value else ""
        mode = self._mode(values, rule_changed)
        for name in self.scene.modes:
            on = name == mode
            reasons[name] = ("picked" if self.mode_pick is not None else reasons[name]) if on else ""
            values[name] = on
        values[DEFAULT] = mode == DEFAULT
        reasons[DEFAULT] = "picked" if mode == DEFAULT and self.mode_pick is not None else ""
        # the overrides of the states with sources, then the composed states in the order of what they name
        for name, value in self.overrides.items():
            if name not in self.scene.conditions:
                values[name] = value is Override.ON
                reasons[name] = "override" if values[name] else ""
        for name in self._order:
            condition = self.scene.conditions[name]
            delayed = self._delayed[name]
            edge = delayed.update(condition.holds(values, lambda target: False), now)
            if edge and not self.scene.states[name].persist:
                self.overrides.pop(name, None)
            override = self.overrides.get(name)
            values[name] = delayed.value if override is None else override is Override.ON
            reasons[name] = "" if not values[name] else "override" if override is not None else condition.text
        for name, value in values.items():
            if self._last.get(name) != value:
                self._since[name] = now
        self._last = values
        return States(values, mode, reasons, dict(self._since))

    def deadline(self) -> float | None:
        """The next time a delay ends, if one is pending: then the states need an update."""
        return min((d for delayed in self._delayed.values() if (d := delayed.deadline()) is not None), default=None)

    def _mode(self, values: Mapping[str, bool], rule_changed: bool) -> str:
        if rule_changed:
            # a pick lasts until a rule starts or stops matching
            self.mode_pick = None
        if self.mode_pick is not None:
            return self.mode_pick
        on = [name for name in self.scene.modes if values[name]]
        if not on:
            return DEFAULT
        # the highest priority, then the first in the file
        return max(on, key=lambda name: (self.scene.states[name].priority, -on.index(name)))


def composed_order(scene: Scene) -> list[str]:
    """The composed states, each after the composed states it names (the model has no loops)."""
    order: list[str] = []

    def visit(name: str) -> None:
        if name in order:
            return
        for other in sorted(scene.conditions[name].states):
            if other in scene.conditions:
                visit(other)
        order.append(name)

    for name in scene.conditions:
        visit(name)
    return order
