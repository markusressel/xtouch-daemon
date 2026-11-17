"""
Running a configuration of channels, states and slots on the device (the prototype of
docs/design/channels-states-slots.md): a `Simulation` fed with what the sound server, the processes and the voice
chat show, whose result becomes the strips of a mixer. A mixer is built anew only when the strip of a slot changes
(another channel, a pool instead of a channel), like at a layout switch; the members of `auto` and `people` are
handed out by its `auto` and `voip` strips.
"""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.slots import Shape, shape_of, showing
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import VoipState
from xtouch_daemon.slots.model import DEFAULT
from xtouch_daemon.slots.recording import Observer
from xtouch_daemon.slots.resolver import Result
from xtouch_daemon.slots.simulation import Known, Simulation
from xtouch_daemon.slots.states import States

_LOGGER = logging.getLogger(__name__)

DARK: Shape = ((None, None, None, None),) * protocol.STRIPS
"""Every slot dark: before the first step."""
PEOPLE_FILE_NAME = "people.json"
"""The file of the order of the people, in the state directory of the daemon."""
INTERVAL = 0.2
"""How often the slots are resolved: also the batching of changes that come together (a game starts)."""
PROCESS_INTERVAL = 2.0
"""How often the processes are scanned for the states, as for the rules of layouts."""


class SlotRunner:
    """The slots of `config` (which has `slots`) over time: `step()` after each look at the system."""

    def __init__(
        self,
        config: Config,
        people_file: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        """
        `people_file` keeps the order of the people across restarts (None: nowhere). `clock` is the clock of
        `step()`, `wall_clock` the one of the file.
        """
        assert config.slots is not None, "only for a configuration of slots"
        self.config = config
        self.scene = config.slots.scene
        self.people_file = people_file
        self._clocks = (clock, wall_clock)
        known = read_people(people_file, clock(), wall_clock()) if people_file is not None else {}
        self.simulation = Simulation(self.scene, known=known)
        self._kept: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())
        """The people known and those present when the file was written last."""
        self.observer = Observer()
        self.shape: Shape | None = None
        """What the strips of the mixer show; None before the first step (the sound server is not there yet)."""

    @property
    def mode(self) -> str:
        states = self.simulation.states
        return states.mode if states is not None else DEFAULT

    @property
    def modes(self) -> tuple[str, ...]:
        """`default` and the modes, in the order of the file."""
        return (DEFAULT, *self.scene.modes)

    def mode_label(self, mode: str) -> str:
        label = self.scene.states[mode].label if mode in self.scene.states else None
        return label or mode.capitalize()

    def mixer_config(self) -> Config:
        """The configuration of today's format for the mixer: the strips of the result, all of them dark before."""
        return showing(self.config, self.shape or DARK)

    def step(
        self,
        audio: AudioState,
        processes: frozenset[str],
        voip: VoipState | None,
        held: frozenset[int],
        now: float,
    ) -> bool:
        """
        Resolves the slots with what the system shows at `now`; `held` are the slots (from 1) under a finger. True
        if the strips changed: then the mixer is built anew from `mixer_config()`.
        """
        observation = self.observer.observe(audio, processes, voip, now)
        before = self.simulation.states
        previous = self.simulation.result
        result = self.simulation.step(observation, now, held)
        states = self.simulation.states
        assert states is not None
        self._log_states(before, states)
        self._keep_people(tuple(person.name for person in observation.people))
        shape = shape_of(result)
        if shape == self.shape:
            return False
        self._log_slots(previous, result)
        self.shape = shape
        return True

    def _keep_people(self, people: tuple[str, ...]) -> None:
        """Writes the people known when someone came or went (then they were last seen)."""
        known = self.simulation.known
        kept = (tuple(known), people)
        if self.people_file is None or kept == self._kept:
            return
        self._kept = kept
        clock, wall_clock = self._clocks
        write_people(self.people_file, known, clock(), wall_clock())

    def pick_mode(self, mode: str | None) -> None:
        """A mode by hand (`default` too), None for the rules."""
        self.simulation.engine.pick_mode(mode)

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
        _LOGGER.info(f"Slots: {', '.join(changes)}")
        for slot in after.slots:
            if before is None or str(before.slots[slot]) != str(after.slots[slot]):
                _LOGGER.debug(f"Slot {slot}: {'; '.join(after.why[slot])}")


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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # whole or not at all
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(data) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError as e:
        _LOGGER.warning(f"Can't keep the order of the people in {path}: {e}")
