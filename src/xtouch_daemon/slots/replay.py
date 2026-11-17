"""
Replaying recorded observations through a `Simulation`: what the states and slots would have done, when, and how
often a slot went back and forth.
"""

import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from xtouch_daemon.slots.inputs import Observation
from xtouch_daemon.slots.model import Scene
from xtouch_daemon.slots.resolver import SLOTS
from xtouch_daemon.slots.simulation import Simulation

FLAP_WINDOW = 60.0
"""A slot that goes back to what it showed within this many seconds flaps."""
MAX_STEPS_BETWEEN = 1000
"""At most this many deadlines between two observations (delays and dwell times ending)."""


@dataclass(frozen=True)
class Event:
    at: float
    text: str


@dataclass
class Report:
    events: list[Event] = field(default_factory=list)
    changes: dict[int, int] = field(default_factory=lambda: dict.fromkeys(SLOTS, 0))
    """Per slot, how often it changed."""
    flaps: list[Event] = field(default_factory=list)
    """Slots that went back to what they showed shortly before."""
    on_time: dict[str, float] = field(default_factory=dict)
    """Per state and mode, the seconds it was on."""
    start: float = 0.0
    end: float = 0.0

    def summary(self) -> list[str]:
        hours = (self.end - self.start) / 3600
        lines = [f"{hours:.1f} h replayed, {sum(self.changes.values())} slot changes, {len(self.flaps)} flaps"]
        lines.append("changes per slot: " + ", ".join(f"{slot}: {count}" for slot, count in self.changes.items()))
        lines += [f"{name} on for {_duration(seconds)}" for name, seconds in self.on_time.items() if seconds]
        return lines


def _duration(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 120 else f"{seconds / 60:.0f} min"


def clock(at: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(at))


def replay(scene: Scene, log: Iterable[tuple[float, Observation]], simulation: Simulation | None = None) -> Report:
    simulation = simulation or Simulation(scene)
    report = Report()
    history: dict[int, list[tuple[float, str]]] = {slot: [] for slot in SLOTS}
    last_states: dict[str, bool] = {}
    previous: tuple[float, Observation] | None = None

    def step(observation: Observation, at: float) -> None:
        result = simulation.step(observation, at)
        states = simulation.states
        assert states is not None
        for name, value in states.values.items():
            if name in last_states and last_states[name] != value:
                why = f" ({states.reasons[name]})" if value and states.reasons[name] else ""
                report.events.append(Event(at, f"{name} {'on' if value else 'off'}{why}"))
        if last_states and previous is not None:
            for name, value in last_states.items():
                if value:
                    report.on_time[name] = report.on_time.get(name, 0.0) + at - previous[0]
        last_states.clear()
        last_states.update(states.values)
        for slot, shown in result.slots.items():
            text = str(shown)
            past = history[slot]
            if past and past[-1][1] != text:
                report.changes[slot] += 1
                report.events.append(Event(at, f"slot {slot}: {past[-1][1]} -> {text}"))
                if len(past) >= 2 and past[-2][1] == text and at - past[-2][0] <= FLAP_WINDOW:
                    report.flaps.append(Event(at, f"slot {slot}: {past[-1][1]} and back to {text}"))
            if not past or past[-1][1] != text:
                past.append((at, text))

    for at, observation in log:
        if previous is None:
            report.start = at
        else:
            for _ in range(MAX_STEPS_BETWEEN):
                deadline = simulation.deadline()
                if deadline is None or deadline >= at or deadline <= previous[0]:
                    break
                step(previous[1], deadline)
                previous = (deadline, previous[1])
        step(observation, at)
        previous = (at, observation)
        report.end = at
    return report
