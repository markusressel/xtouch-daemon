"""
Running a configuration of channels, states and slots on the device (the prototype of
docs/design/channels-states-slots.md): the `SlotEngine` feeds a `Simulation` with what the sound server, the
processes and the voice chat show, and takes the requests (a mode, an override, a pin); its result says what the
`SlotMixer` (`runtime.binder`) puts on each strip of the device.
"""

import json
import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.model import Config
from xtouch_daemon.live.messages import VoipState
from xtouch_daemon.slots.inputs import App, Channel, Member, excluded, owner_of
from xtouch_daemon.slots.model import DEFAULT, Scene
from xtouch_daemon.slots.recording import Observer
from xtouch_daemon.slots.resolver import Result
from xtouch_daemon.slots.simulation import Known, Simulation
from xtouch_daemon.slots.states import Override, States

_LOGGER = logging.getLogger(__name__)

PEOPLE_FILE_NAME = "people.json"
"""The file of the order of the people, in the state directory of the daemon."""
CHOICES_FILE_NAME = "slots.json"
"""The file of the overrides and the mode picked, in the state directory of the daemon."""
BATCH = 0.1
"""Changes are resolved together this long after the first one (a game starts several streams and a process)."""
PROCESS_INTERVAL = 2.0
"""How often the processes are scanned for the states, as for the rules of layouts."""

type Choices = tuple[Mapping[str, Override], str | None]
"""What was chosen by hand: the overrides of states, and the mode picked (None for the rules)."""


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
        assert config.slots is not None, "only for a configuration of slots"
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

    def reconfigure(self, config: Config) -> None:
        """Goes on with another configuration (a reload): states, channels, members and choices carry over by id."""
        assert config.slots is not None, "only for a configuration of slots"
        before = self.simulation
        self.config = config
        self.scene = config.slots.scene
        self.simulation = Simulation(self.scene)
        self.simulation.carry(before)
        self.pins = {slot: member for slot, member in self.pins.items() if slot in self.scene.stacks}
        self._keep_choices()

    @property
    def mode(self) -> str:
        states = self.simulation.states
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

    def deadline(self) -> float | None:
        """When a delay or a dwell ends, if one is pending: then the slots need another step."""
        return self.simulation.deadline()

    # -- requests -------------------------------------------------------------------------------------------------

    def pick_mode(self, mode: str | None) -> None:
        """A mode by hand (`default` too), None for the rules; from the next step on."""
        self.simulation.engine.pick_mode(mode)
        self._keep_choices()

    def set_override(self, state: str, value: Override) -> None:
        """The override of a state that is no mode; from the next step on."""
        self.simulation.engine.set_override(state, value)
        self._keep_choices()

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
        result = self.simulation.result
        return result.slots[slot].member if result is not None else None

    def candidates(self) -> list[App]:
        """What a slot of `auto` can pick: the applications without a slot of their own, in the order they started."""
        scene = self.scene
        return [
            App(app)
            for app in self.simulation.pools.playing
            if not excluded(scene, app) and owner_of(scene, app) is None
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
        observation = self.observer.observe(audio, processes, voip, now)
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


def read_people(path: Path, now: float, wall_now: float) -> dict[str, float]:
    """The people `write_people()` kept, at times of the clock that says `now` (none without a readable file)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        _LOGGER.warning(f"Can't read the order of the people from {path}: {e}")
        return {}
    return {str(person): now - (wall_now - float(at)) for person, at in data}


def write_people(path: Path, known: Known, now: float, wall_now: float) -> None:
    """Keeps the people known for the next start, in their order, with wall-clock times. Errors are logged."""
    data = [[person, round(wall_now - (now - at), 1)] for person, at in known.items()]
    _write(path, data, "the order of the people")


def _write(path: Path, data: object, what: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # whole or not at all
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(data) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError as e:
        _LOGGER.warning(f"Can't keep {what} in {path}: {e}")


def read_choices(path: Path, scene: Scene) -> Choices:
    """The choices `write_choices()` kept, those that still fit the scene (none without a readable file)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        overrides = {str(name): Override(value) for name, value in data["overrides"].items()}
        mode = data["mode"]
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        _LOGGER.warning(f"Can't read the overrides and the mode from {path}: {e}")
        return {}, None
    kept = {name: value for name, value in overrides.items() if name in scene.states and not scene.states[name].mode}
    return kept, mode if mode == DEFAULT or mode in scene.modes else None


def write_choices(path: Path, choices: Choices) -> None:
    """Keeps the choices for the next start. Errors are logged."""
    overrides, mode = choices
    _write(
        path,
        {"overrides": {name: value.value for name, value in overrides.items()}, "mode": mode},
        "the overrides and the mode",
    )
