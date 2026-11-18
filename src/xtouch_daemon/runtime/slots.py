"""
Running a configuration of channels, states and slots on the device (the prototype of
docs/development/design/channels-states-slots.md): the `SlotEngine` feeds a `Simulation` with what the sound server, the
processes and the voice chat show, and takes the requests (a mode, an override, a pin); its result says what the
`SlotMixer` (`runtime.binder`) puts on each strip of the device.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.model import Config
from xtouch_daemon.live.messages import SlotsState, SlotView, StateView, VoipState
from xtouch_daemon.runtime.slot_files import (
    CHOICES_FILE_NAME,
    PEOPLE_FILE_NAME,
    Choices,
    read_choices,
    read_people,
    write_choices,
    write_people,
)
from xtouch_daemon.slots.inputs import App, Channel, Device, Member, Person, excluded, owner_of
from xtouch_daemon.slots.model import DEFAULT
from xtouch_daemon.slots.outcomes import Situation
from xtouch_daemon.slots.recording import Observer
from xtouch_daemon.slots.resolver import Result
from xtouch_daemon.slots.simulation import Simulation
from xtouch_daemon.slots.states import Override, States

_LOGGER = logging.getLogger(__name__)

BATCH = 0.1
"""Changes are resolved together this long after the first one (a game starts several streams and a process)."""
PROCESS_INTERVAL = 2.0
"""How often the processes are scanned for the states."""


class SlotEngine:
    """
    The slots of a configuration (which has `slots`) over time: `step()` after each look at the system, `deadline()`
    when the next one is due without a change. It outlives the configuration: `reconfigure()` goes on with a new one
    (a reload). Overrides, the mode picked and the people are kept across restarts in `state_dir`.
    """

    def __init__(
        self,
        config: Config,
        state_dir: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        """`state_dir` keeps the choices and the people (None: nowhere); `wall_clock` is the clock of the files."""
        self.config = config
        self.scene = config.slots.scene
        self.state_dir = state_dir
        self._clocks = (clock, wall_clock)
        people = state_dir / PEOPLE_FILE_NAME if state_dir is not None else None
        known = read_people(people, clock(), wall_clock()) if people is not None else {}
        overrides, mode = (
            read_choices(state_dir / CHOICES_FILE_NAME, self.scene) if state_dir is not None else ({}, None)
        )
        self.simulation = Simulation(self.scene, overrides, mode, known=known)
        self._kept: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())
        """The people known and those present when the file was written last."""
        self._chosen: Choices = self.choices
        """The choices when the file was written last (or read)."""
        self.pins: dict[int, App | Channel] = {}
        """The members pinned to slots of `auto` (the `pick` encoder)."""
        self.picks: dict[int, App] = {}
        """The applications picked for slots of `auto` for the next step; then they keep their slots as members do."""
        self.on_request: Callable[[], None] = lambda: None
        """Called after a request of a slot's encoder, which should show at once."""
        self.observer = Observer()
        self.homeassistant: frozenset[str] = frozenset()
        """The states whose input in Home Assistant is on (`homeassistant = true`, see `runtime.homeassistant`)."""
        self.situation: Situation | None = None
        """The what-if the GUI tries on the device (see `simulate()`), None for reality."""
        self.what_if: Simulation | None = None
        """The slots of `situation` over time, next to the real ones (`simulation`), which wait meanwhile."""

    @property
    def active(self) -> Simulation:
        """What the device shows: the situation's slots while one runs, else the real ones."""
        return self.what_if if self.what_if is not None else self.simulation

    def simulate(self, situation: Situation | None) -> None:
        """
        Runs a situation instead of reality from the next step on (None: reality again), in a `Simulation` of its own
        that starts where the real one is: its states are overrides, its mode the one picked, what the sound server
        and the voice chat show is made for it (`Situation.observation`). Nothing of it is kept or told to Home
        Assistant. See `docs/development/design/try-and-simulate.md`.
        """
        self.situation = situation
        if situation is None:
            self.what_if = None
            return
        if self.what_if is None:
            self.what_if = Simulation(self.scene)
            self.what_if.carry(self.simulation)
        overrides, mode = situation.choices(self.scene)
        self.what_if.engine.overrides = overrides
        self.what_if.engine.mode_pick = mode

    def reconfigure(self, config: Config) -> None:
        """Goes on with another configuration (a reload): states, channels, members and choices carry over by id."""
        before = self.simulation
        self.config = config
        self.scene = config.slots.scene
        self.simulation = Simulation(self.scene)
        self.simulation.carry(before)
        if self.what_if is not None:
            what_if, self.what_if = self.what_if, Simulation(self.scene)
            self.what_if.carry(what_if)
            self.simulate(self.situation)
        self.pins = {slot: member for slot, member in self.pins.items() if slot in self.scene.stacks}
        self._keep_choices()

    @property
    def mode(self) -> str:
        """The mode the device shows (of the situation while one runs)."""
        states = self.active.states
        return states.mode if states is not None else DEFAULT

    @property
    def modes(self) -> tuple[str, ...]:
        """`default` and the modes, in the order of the file."""
        return (DEFAULT, *self.scene.modes)

    @property
    def choices(self) -> Choices:
        engine = self.simulation.engine
        return dict(engine.overrides), engine.mode_pick

    def mode_label(self, mode: str) -> str:
        label = self.scene.states[mode].label if mode in self.scene.states else None
        return label or mode.capitalize()

    def wall_time(self, moment: float) -> str:
        """A time of the clock of the steps (e.g. when a state got its value) as an ISO time of the wall clock."""
        clock, wall_clock = self._clocks
        return datetime.fromtimestamp(wall_clock() - (clock() - moment), UTC).isoformat(timespec="seconds")

    def view(self) -> SlotsState | None:
        """The slots, states and mode for the live view; None before the first step."""
        active = self.active
        result, states = active.result, active.states
        if result is None or states is None:
            return None
        engine = active.engine
        return SlotsState(
            states.mode,
            engine.mode_pick,
            tuple(
                SlotView(
                    slot,
                    shown.candidate,
                    shown.channel,
                    shown.pool,
                    _member_text(shown.member),
                    result.why[slot],
                )
                for slot, shown in result.slots.items()
            ),
            tuple(
                StateView(
                    name,
                    self.value(name),
                    name in self.scene.modes,
                    self.wall_time(states.since[name]) if name in states.since else None,
                    states.reasons.get(name) if self.value(name) else None,
                    engine.overrides.get(name, Override.AUTO).value,
                )
                for name in self.scene.states
            ),
            {pool: tuple(_member_text(member) or "" for member in members) for pool, members in result.waiting.items()},
        )

    def deadline(self) -> float | None:
        """When a delay or a dwell ends, if one is pending: then the slots need another step."""
        return self.active.deadline()

    # -- requests -------------------------------------------------------------------------------------------------

    def pick_mode(self, mode: str | None) -> None:
        """A mode by hand (`default` too), None for the rules; from the next step on."""
        self.simulation.engine.pick_mode(mode)
        self._keep_choices()

    def set_override(self, state: str, value: Override) -> None:
        """The override of a state that is no mode; from the next step on."""
        self.simulation.engine.set_override(state, value)
        self._keep_choices()

    # -- the actions of buttons in [controls] (see `runtime.controls`): they show at once -------------------------

    def value(self, name: str) -> bool:
        """Whether a state is on, or a mode is the mode (in the situation while one runs); False before a step."""
        states = self.active.states
        return states is not None and (states.mode == name if name in self.modes else states.values.get(name, False))

    def cycle_modes(self) -> None:
        """The next mode, as the chord picks it."""
        modes = self.modes
        self.choose_mode(modes[(modes.index(self.mode) + 1) % len(modes)])

    def choose_mode(self, mode: str) -> None:
        """A mode by hand (until the rules want another one)."""
        _LOGGER.info(f"Mode {mode} (a control)")
        self.pick_mode(mode)
        self.on_request()

    def toggle(self, name: str) -> None:
        """
        A mode: picks it, and the next time gives the choice back to the rules. A state: overrides it to the opposite
        of its value now, and the next time gives it back to its sources.
        """
        engine = self.simulation.engine
        if name in self.scene.modes:
            back = engine.mode_pick == name
            _LOGGER.info(f"Mode {'auto' if back else name} (a control)")
            self.pick_mode(None if back else name)
        else:
            # the real value: a situation that runs doesn't change what the override does
            states = self.simulation.states
            on = states is not None and states.values.get(name, False)
            value = Override.AUTO if name in engine.overrides else Override.OFF if on else Override.ON
            _LOGGER.info(f"State {name}: override {value} (a control)")
            self.set_override(name, value)
        self.on_request()

    def pin(self, slot: int, member: App | Channel | None) -> None:
        """Pins a member to a slot of `auto`, None takes the pin away; from the next step on."""
        if member is None:
            self.pins.pop(slot, None)
        else:
            self.pins[slot] = member

    def pick(self, slot: int, app: App) -> None:
        """Puts an application on a slot of `auto` at the next step (one another slot has moves on)."""
        self.picks[slot] = app

    def member(self, slot: int) -> Member | None:
        """What a slot shows of a pool, None before the first step."""
        result = self.active.result
        return result.slots[slot].member if result is not None else None

    def candidates(self) -> list[App]:
        """What a slot of `auto` can pick: the applications without a slot of their own, in the order they started."""
        scene = self.scene
        return [
            App(app) for app in self.active.pools.playing if not excluded(scene, app) and owner_of(scene, app) is None
        ]

    def slot(self, index: int) -> EngineSlot:
        """Where the `pick` encoder of the slot (from 0) picks."""
        return EngineSlot(self, index + 1)

    # -- steps ----------------------------------------------------------------------------------------------------

    def step(
        self,
        audio: AudioState,
        processes: frozenset[str],
        voip: VoipState | None,
        held: frozenset[int],
        now: float,
    ) -> Result:
        """Resolves the slots with what the system shows at `now`; `held` are the slots (from 1) under a finger."""
        observation = self.observer.observe(audio, processes, voip, now, self.homeassistant)
        if self.what_if is not None and self.situation is not None:
            # reality waits; nothing of the situation is kept
            what_if = self.what_if
            before, previous = what_if.states, what_if.result
            result = what_if.step(self.situation.observation(self.scene, observation), now, held)
            assert what_if.states is not None
            self._log_states(before, what_if.states)
            self._log_slots(previous, result)
            return result
        before = self.simulation.states
        previous = self.simulation.result
        result = self.simulation.step(observation, now, held, self.picks | self.pins)
        # a pick was asked for once: from now on its application keeps the slot as members do
        self.picks = {}
        states = self.simulation.states
        assert states is not None
        self._log_states(before, states)
        self._keep_people(tuple(person.name for person in observation.people))
        # an override ends at an edge of its state, a mode picked when the rules want another one
        self._keep_choices()
        self._log_slots(previous, result)
        return result

    def _keep_people(self, people: tuple[str, ...]) -> None:
        """Writes the people known when someone came or went (then they were last seen)."""
        known = self.simulation.known
        kept = (tuple(known), people)
        if self.state_dir is None or kept == self._kept:
            return
        self._kept = kept
        clock, wall_clock = self._clocks
        write_people(self.state_dir / PEOPLE_FILE_NAME, known, clock(), wall_clock())

    def _keep_choices(self) -> None:
        """Writes the choices when they changed."""
        choices = self.choices
        if self.state_dir is None or choices == self._chosen:
            return
        self._chosen = choices
        write_choices(self.state_dir / CHOICES_FILE_NAME, choices)

    @staticmethod
    def _log_states(before: States | None, after: States) -> None:
        if before is None:
            on = [name for name, value in after.values.items() if value]
            _LOGGER.info(f"States at the start: {', '.join(on) or 'none'}")
            return
        for name, value in after.values.items():
            if before.values.get(name) != value:
                why = f" ({after.reasons[name]})" if value and after.reasons.get(name) else ""
                _LOGGER.info(f"State {name} {'on' if value else 'off'}{why}")

    @staticmethod
    def _log_slots(before: Result | None, after: Result) -> None:
        changes = [
            f"{slot} {shown}"
            for slot, shown in after.slots.items()
            if before is None or str(before.slots[slot]) != str(shown)
        ]
        if not changes:
            return
        _LOGGER.info(f"Slots: {', '.join(changes)}")
        for slot in after.slots:
            if before is None or str(before.slots[slot]) != str(after.slots[slot]):
                _LOGGER.debug(f"Slot {slot}: {'; '.join(after.why[slot])}")


class EngineSlot:
    """A slot of `auto` for the `pick` encoder of its strip: its requests go to the engine (see `PickSlot`)."""

    def __init__(self, engine: SlotEngine, slot: int):
        self.engine = engine
        self.number = slot

    @property
    def pinned(self) -> bool:
        return self.number in self.engine.pins

    def position(self) -> tuple[int, int] | None:
        candidates = self.engine.candidates()
        member = self.engine.member(self.number)
        return (candidates.index(member), len(candidates)) if isinstance(member, App) and member in candidates else None

    def pick(self, steps: int) -> None:
        candidates = self.engine.candidates()
        if not candidates:
            return
        member = self.engine.member(self.number)
        if isinstance(member, App) and member in candidates:
            app = candidates[(candidates.index(member) + steps) % len(candidates)]
        else:
            app = candidates[0 if steps > 0 else -1]
        if self.pinned:
            # a pinned slot stays pinned, with the new application
            self.engine.pin(self.number, app)
        self.engine.pick(self.number, app)
        self.engine.on_request()

    def toggle_pin(self) -> None:
        """Pins what the slot shows (an application or a channel), or unpins it."""
        member = self.engine.member(self.number)
        if self.pinned:
            self.engine.pin(self.number, None)
        elif isinstance(member, App | Channel):
            self.engine.pin(self.number, member)
        self.engine.on_request()


def _member_text(member: Member | None) -> str | None:
    """How the live view names a member: `app:<name>`, `person:<name>`, `device:<node name>`, or the channel."""
    match member:
        case App(name=name):
            return f"app:{name}"
        case Person(channel=None, name=name):
            return f"person:{name}"
        case Device(name=name):
            return f"device:{name}"
        case Person(channel=str(channel)) | Channel(id=channel):
            return channel
        case _:
            return None
