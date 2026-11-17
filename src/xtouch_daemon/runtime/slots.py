"""
Running a configuration of channels, states and slots on the device (the prototype of
docs/design/channels-states-slots.md): a `Simulation` fed with what the sound server, the processes and the voice
chat show, whose result becomes the strips of a mixer. A mixer is built anew only when the strip of a slot changes
(another channel, a pool instead of a channel), like at a layout switch; the members of `auto` and `people` are
handed out by its `auto` and `voip` strips.
"""

import logging

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.slots import Shape, shape_of, showing
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import VoipState
from xtouch_daemon.slots.model import DEFAULT
from xtouch_daemon.slots.recording import Observer
from xtouch_daemon.slots.resolver import Result
from xtouch_daemon.slots.simulation import Simulation
from xtouch_daemon.slots.states import States

_LOGGER = logging.getLogger(__name__)

DARK: Shape = ((None, None, None, None),) * protocol.STRIPS
"""Every slot dark: before the first step."""
INTERVAL = 0.2
"""How often the slots are resolved: also the batching of changes that come together (a game starts)."""
PROCESS_INTERVAL = 2.0
"""How often the processes are scanned for the states, as for the rules of layouts."""


class SlotRunner:
    """The slots of `config` (which has `slots`) over time: `step()` after each look at the system."""

    def __init__(self, config: Config):
        assert config.slots is not None, "only for a configuration of slots"
        self.config = config
        self.scene = config.slots.scene
        self.simulation = Simulation(self.scene)
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
        shape = shape_of(result)
        if shape == self.shape:
            return False
        self._log_slots(previous, result)
        self.shape = shape
        return True

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
