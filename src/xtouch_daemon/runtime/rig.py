"""
The strips of a configuration on one surface: the hands on them (`Desk`), the slots (`SlotEngine`), the controllers of
what each slot shows (`SlotMixer`) and the loop that steps the slots over time. The daemon runs one on the device
(`runtime.daemon`), a virtual twin one on a device that is never there, with a sound server and a voice chat of its
own (`runtime.twin`): the same parts, so the twin shows what the device would.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from pathlib import Path

from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.meter import PW_RECORD, Capturer
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.model import Config
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.live.messages import Reply
from xtouch_daemon.live.server import voip_state
from xtouch_daemon.runtime.binder import SlotMixer
from xtouch_daemon.runtime.desk import Desk, touchless
from xtouch_daemon.runtime.slots import BATCH, PROCESS_INTERVAL, SlotEngine
from xtouch_daemon.slots.resolver import Result
from xtouch_daemon.slots.states import Override
from xtouch_daemon.voip.provider import VoipProvider

MANUAL = "manual"
"""The reason of a mode picked over the live view (the GUI, `xtouch-daemon mode`)."""
CHORD = "buttons"
"""The reason of a mode picked by the chord on the device."""
SLOTS_LOGGER = logging.getLogger("xtouch_daemon.runtime.slots")
"""Where the slots of the device log."""


def chord_of(config: Config) -> frozenset[int]:
    """The strips (from 0) whose Solo buttons together do the action of the chord."""
    return frozenset(number - 1 for number in config.switching.chord)


class Rig:
    """
    The strips of `config` on `surface`, for the sound server `backend` and the voice chat `voip`. `follow()` steps
    the slots; `reconfigure()` goes on with another configuration. What differs between the device and a twin is
    the mixer (`_new_mixer()`), the processes the states see (`_processes()`) and what else a step tells
    (`_stepped()`).
    """

    def __init__(
        self,
        config: Config,
        surface: Surface,
        backend: AudioBackend,
        voip: VoipProvider,
        *,
        state_dir: Path | None = None,
        capture_command: str = PW_RECORD,
        capturer: Capturer | None = None,
        clock: Callable[[], float] = time.monotonic,
        logger: logging.Logger = SLOTS_LOGGER,
    ):
        """
        `state_dir` keeps the choices and the people of the slots (None: nowhere), `capture_command` or `capturer` is
        what the meters capture with, `logger` where the states, slots and modes are logged.
        """
        self.config = config
        self.surface = surface
        self.backend = backend
        self.voip = voip
        self._clock = clock
        self.wake = asyncio.Event()
        """Set when something the slots look at changed: they are resolved BATCH later."""
        self._configure_surface(config)
        self.desk = Desk(surface, chord_of(config), self._on_chord, capture_command, capturer)
        """The strips of the device and the hands on them, for every mixer."""
        self.desk.hands_free.append(self.wake_slots)
        self.slots = SlotEngine(config, state_dir, clock=clock, logger=logger)
        """The states, the members and what each slot shows."""
        self.logger = logger
        # what the encoder of a slot picks shows at once
        self.slots.on_request = self.step
        self.mixer = self._new_mixer()

    # -- what differs -----------------------------------------------------------------------------------------------

    def _new_mixer(self) -> SlotMixer:
        """A mixer for `config` on the surface, sound server and voice chat."""
        raise NotImplementedError

    def _configure_surface(self, config: Config) -> None:
        """The options of the [device] section that apply without a restart."""
        self.surface.touchless = touchless(config)

    def _processes(self, now: float) -> frozenset[str]:
        """The processes that run, for the states."""
        return frozenset()

    def _stepped(self, result: Result) -> None:
        """A step put `result` on the strips."""

    # -- the slots --------------------------------------------------------------------------------------------------

    def wake_slots(self) -> None:
        """Something the slots look at changed (the audio, the voice chat, a finger let go)."""
        self.wake.set()

    def on_state(self, state: AudioState) -> None:
        """What the sound server shows now."""
        self.mixer.on_state(state)
        self.wake_slots()

    def step(self) -> None:
        """One step of the slots: the slots that changed show their new controllers, the banner if the mode did."""
        now = self._clock()
        slots = self.slots
        mode = slots.mode if slots.active.states is not None else None
        result = slots.step(self.mixer.state, self._processes(now), voip_state(self.voip), self.desk.held_slots(), now)
        states = slots.active.states
        assert states is not None
        seconds = self.config.switching.banner
        new_mode = mode is not None and states.mode != mode
        # a new mode shows its banner instead of a flash per slot
        self.mixer.apply(result, 0.0 if new_mode else seconds)
        self.mixer.refresh()
        self._stepped(result)
        if new_mode and seconds > 0:
            self.surface.banner(slots.mode_label(states.mode), states.reasons.get(states.mode, ""), seconds)

    async def follow(self) -> None:
        """
        Steps the slots BATCH after a change (what comes together goes together: a game starts several streams and a
        process), when a delay or a dwell ends, and every PROCESS_INTERVAL for the processes, while the sound server
        is there.
        """
        while True:
            timeout = PROCESS_INTERVAL
            if (due := self.slots.deadline()) is not None:
                timeout = min(timeout, max(0.0, due - self._clock()))
            with contextlib.suppress(TimeoutError):
                # at least a moment: a deadline that is due must not keep the others from their turn
                await asyncio.wait_for(self.wake.wait(), max(timeout, 0.001))
            if self.wake.is_set():
                await asyncio.sleep(BATCH)
                self.wake.clear()
            if self.mixer.state.connected:
                self.step()

    def reconfigure(self, config: Config) -> None:
        """
        Goes on with `config`: its [device] options and slots, and a new mixer on the same surface, sound server and
        voice chat. What the states, channels and members were carries over.
        """
        self._configure_surface(config)
        self.desk.chord = chord_of(config)
        self.config = config
        self.slots.reconfigure(config)
        self._replace_mixer()
        if self.mixer.state.connected:
            # the slots of the new configuration right away, not dark until the next step
            self.step()

    def _replace_mixer(self) -> None:
        """A new mixer for the configuration, on the same surface, sound server and voice chat."""
        state = self.mixer.state
        self.mixer.close()
        self.mixer = self._new_mixer()
        # the sound server reports again only once something changes
        self.mixer.on_state(state)

    # -- modes and overrides ----------------------------------------------------------------------------------------

    def request_mode(self, name: str, reason: str = MANUAL) -> Reply:
        """
        A mode asked for (`live.SetMode`, `mode`, the chord, Home Assistant): `default` or a mode picks it
        (until the rules want another one), "+1" ("-1") the next (previous) one, `auto` lets the rules decide.
        """
        if self.slots.fixed:
            return Reply("mode", False, "The mode comes from the situation of the GUI.")
        modes = self.slots.modes
        if name in ("+1", "-1"):
            name = modes[(modes.index(self.slots.mode) + int(name)) % len(modes)]
        elif name != "auto" and name not in modes:
            return Reply("mode", False, f"There is no mode {name} (auto, {', '.join(modes)})")
        self.logger.info(f"Mode {name} ({reason})")
        self.slots.pick_mode(None if name == "auto" else name)
        self.step()
        return Reply("mode", True, self.slots.mode)

    def request_override(self, name: str, value: str) -> Reply:
        """The override of a state that is no mode (`auto`, `on`, `off`)."""
        if self.slots.fixed:
            return Reply("override", False, "The states come from the situation of the GUI.")
        states = [state for state, config in self.slots.scene.states.items() if not config.mode]
        if name not in states:
            return Reply("override", False, f"There is no state {name} ({', '.join(states) or 'none'})")
        if value not in Override:
            return Reply("override", False, f"{value} is no override (auto, on, off)")
        self.logger.info(f"State {name}: override {value} ({MANUAL})")
        self.slots.set_override(name, Override(value))
        self.step()
        return Reply("override", True, value)

    def _on_chord(self) -> None:
        if self.slots.fixed:
            return
        action = self.config.switching.chord_action
        if action == "cycle_modes":
            self.request_mode("+1", CHORD)
        elif action.startswith("mode:"):
            self.request_mode(action.removeprefix("mode:"), CHORD)
        else:
            self.slots.toggle(action.removeprefix("toggle:"))

    # -- the end ----------------------------------------------------------------------------------------------------

    def close(self) -> None:
        """Stops the controllers of the strips and the meters' captures (`desk.wait_closed()` waits for them)."""
        self.mixer.close()
        self.desk.close()
