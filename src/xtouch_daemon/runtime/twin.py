"""
The virtual twin (see docs/development/design/previews.md): the strips of a configuration in a situation, on a
device of their own. It is built from the parts of the real path (`Surface`, `Desk`, `SlotMixer`, `SlotEngine`, the
strip controllers) and from a `Config` and the `Names` of what is real right now, and from nothing else: it holds no
reference to the sound server, the voice chat, Home Assistant or the files of the daemon, so nothing it does reaches
them. What the GUI draws of it is the mirror of its `Surface`, as for the device.
"""

import asyncio
import contextlib
import dataclasses
import logging
import math
import time
from collections.abc import Callable

from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState, Device, Direction, Stream
from xtouch_daemon.config.model import Config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.hardware.transport import NoPort
from xtouch_daemon.live.messages import TwinView, fingerprint
from xtouch_daemon.live.server import strip_states
from xtouch_daemon.runtime.binder import SlotMixer
from xtouch_daemon.runtime.rig import Rig
from xtouch_daemon.slots.model import DEFAULT
from xtouch_daemon.slots.outcomes import Situation
from xtouch_daemon.slots.resolver import Result
from xtouch_daemon.slots.world import Names, world, world_of_now
from xtouch_daemon.system.commands import Commands
from xtouch_daemon.system.launch import Launcher
from xtouch_daemon.voip.demo import DemoProvider

_LOGGER = logging.getLogger("xtouch_daemon.twin")

METER_INTERVAL = 0.02
"""How often the made-up signal of a playing target gives a peak (a capture of the sound server: 50 times a second)."""


class TwinBackend:
    """
    A sound server that is only in memory: `state` is what the twin's strips see, and every command changes it and
    tells the twin (`changed`), as the real one reports after a command.
    """

    def __init__(self, changed: Callable[[AudioState], None]):
        self.state = AudioState()
        self._changed = changed

    def set_state(self, state: AudioState) -> None:
        """A new world; what the twin's strips set (volumes, mutes, balances) stays for what is still there."""
        old = self.state
        streams = {(s.app, s.binary): s for s in old.streams}
        devices = {(d.direction, d.name): d for d in (*old.outputs, *old.inputs)}

        def stream(new: Stream) -> Stream:
            kept = streams.get((new.app, new.binary))
            return new if kept is None else _kept(new, volume=kept.volume, muted=kept.muted, balance=kept.balance)

        def device(new: Device) -> Device:
            kept = devices.get((new.direction, new.name))
            return new if kept is None else _kept(new, volume=kept.volume, muted=kept.muted, balance=kept.balance)

        self._set(
            dataclasses.replace(
                state,
                streams=tuple(stream(s) for s in state.streams),
                outputs=tuple(device(d) for d in state.outputs),
                inputs=tuple(device(d) for d in state.inputs),
            )
        )

    def _set(self, state: AudioState) -> None:
        self.state = state
        self._changed(state)

    async def run(self, on_state: Callable[[AudioState], None]) -> None:
        raise NotImplementedError("a twin is told by `set_state()`, it has no sound server to follow")

    def _device(self, direction: Direction, name: str, **changes: object) -> None:
        def change(device: Device) -> Device:
            return dataclasses.replace(device, **changes) if device.name == name else device

        state = self.state
        if direction == Direction.OUTPUT:
            self._set(dataclasses.replace(state, outputs=tuple(change(d) for d in state.outputs)))
        else:
            self._set(dataclasses.replace(state, inputs=tuple(change(d) for d in state.inputs)))

    def _stream(self, index: int, **changes: object) -> None:
        self._set(
            dataclasses.replace(
                self.state,
                streams=tuple(dataclasses.replace(s, **changes) if s.index == index else s for s in self.state.streams),
            )
        )

    async def set_device_volume(self, direction: Direction, name: str, percent: int) -> None:
        self._device(direction, name, volume=percent, fraction=None)

    async def set_device_mute(self, direction: Direction, name: str, muted: bool) -> None:
        self._device(direction, name, muted=muted)

    async def set_device_balance(self, direction: Direction, name: str, balance: float) -> None:
        self._device(direction, name, balance=balance)

    async def set_default(self, direction: Direction, name: str) -> None:
        if direction == Direction.OUTPUT:
            self._set(dataclasses.replace(self.state, default_output=name))
        else:
            self._set(dataclasses.replace(self.state, default_input=name))

    async def set_card_profile(self, card: str, profile: str) -> None:
        # a twin has no sound cards
        return None

    async def set_stream_volume(self, index: int, percent: int) -> None:
        self._stream(index, volume=percent, fraction=None)

    async def set_stream_mute(self, index: int, muted: bool) -> None:
        self._stream(index, muted=muted)

    async def set_stream_balance(self, index: int, balance: float) -> None:
        self._stream(index, balance=balance)


def _kept[T: (Stream, Device)](new: T, **changes: object) -> T:
    return dataclasses.replace(new, **changes)


async def pulse(
    target: CaptureTarget,
    feed: Callable[[float], None],
    playing: Callable[[], bool],
    gain: Callable[[], float | None],
) -> None:
    """
    The made-up signal of a target for the meters of a twin: a slow, uneven swell like music, while it plays. What a
    capture of the sound server gives is after the volume of a stream or an input and before that of an output's monitor
    (see `scale_of()`), so does this.
    """
    loop = asyncio.get_running_loop()
    start = loop.time()
    while True:
        await asyncio.sleep(METER_INTERVAL)
        if not playing():
            continue
        t = loop.time() - start
        signal = 0.25 + 0.7 * abs(math.sin(t * 2.3)) * abs(math.sin(t * 0.9 + 0.5))
        volume = gain()
        feed(signal if target.monitor or volume is None else signal * volume)


def _no_launch(command: list[str]) -> None:
    """What a launch does in a twin: nothing (it is logged by the strip)."""
    _LOGGER.debug(f"Not launching {command}: a twin starts nothing")


class Twin(Rig):
    """
    The strips of `config` in `situation`, with the real `names` as stand-ins first: a rig (see `runtime.rig`) on a
    device that is never there, a sound server in memory and a made-up voice chat. `run()` steps the slots and plays
    the voice chat; `view()` is what the GUI draws; `play()` puts a hand on it. The situation is the GUI's alone: the
    chord, the controls and the requests of modes and overrides change nothing (see `SlotEngine.fixed`).
    """

    def __init__(
        self,
        config: Config,
        situation: Situation,
        names: Names | None = None,
        clock: Callable[[], float] = time.monotonic,
        real: bool = False,
        commands: Commands | None = None,
    ):
        """
        `real`: the world is the one of now (`world_of_now()`, a preview of edits without Simulate); `situation` gives
        only the mode and the states then. `commands` runs the programs of custom channels (by default
        `SimulatedCommands`: watches only).
        """
        self.situation = situation
        self.real = real
        self.names = names or Names()
        self.on_change: Callable[[], None] = lambda: None
        """Called when what the twin shows may have changed (its strips, a step of its slots): its view goes out."""
        self.sound = TwinBackend(self.on_state)
        """The twin's sound server."""
        self.people = DemoProvider(())
        """The twin's voice chat."""
        super().__init__(
            config,
            Surface(port=NoPort()),
            self.sound,
            self.people,
            capturer=pulse,
            clock=clock,
            logger=_LOGGER,
            commands=commands,
        )
        self.slots.fixed = True
        self.surface.on_change = lambda: self.on_change()
        self._apply_situation()

    def _new_mixer(self) -> SlotMixer:
        return SlotMixer(
            self.surface,
            self.backend,
            self.config,
            self.slots,
            self.desk,
            self.voip,
            launcher=Launcher(spawn=_no_launch),
            processes=lambda: frozenset(),
            commands=self.commands,
            on_presence=self.wake_slots,
        )

    def _stepped(self, result: Result) -> None:
        self.on_change()

    # -- the situation ----------------------------------------------------------------------------------------------

    def set_situation(self, situation: Situation, real: bool = False) -> None:
        """Another situation: a new world, the overrides and the mode picked of the situation (see `real`)."""
        if (situation, real) == (self.situation, self.real):
            return
        self.situation, self.real = situation, real
        self._apply_situation()

    def set_names(self, names: Names) -> None:
        """The real applications and people changed: the stand-ins follow."""
        if names != self.names:
            self.names = names
            self._apply_situation()

    def reconfigure(self, config: Config) -> None:
        """Another configuration (the GUI's edit): like a reload, ids carry over; the situation stays."""
        super().reconfigure(config)
        self._apply_situation()

    def _apply_situation(self) -> None:
        scene = self.config.slots.scene
        situation = self.situation
        if situation.mode not in (DEFAULT, *scene.modes):
            # the real mode, which the edits removed
            situation = dataclasses.replace(situation, mode=DEFAULT)
        overrides, mode = situation.choices(scene)
        # past `fixed`: the situation is where the choices come from
        engine = self.slots.simulation.engine
        engine.overrides = overrides
        engine.mode_pick = mode
        # custom channels are there as their `present` says in reality, else as the situation says
        self.slots.made_absent = None if self.real else situation.absent(scene)
        made = world_of_now(self.names) if self.real else world(scene, situation, self.names)
        self.sound.set_state(made.audio)
        self.people.set_people(made.people)
        self.wake_slots()

    # -- running ----------------------------------------------------------------------------------------------------

    async def run(self) -> None:
        """Steps the slots and plays the voice chat and the meters until cancelled."""
        async with asyncio.TaskGroup() as group:
            group.create_task(self.people.run(), name="twin voice chat")
            group.create_task(self.desk.run(), name="twin meters")
            group.create_task(self.follow(), name="twin slots")

    async def wait_closed(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await self.desk.wait_closed()

    # -- hands ------------------------------------------------------------------------------------------------------

    def play(self, event: protocol.StripEvent) -> None:
        """A hand on the twin: the bytes the device would send for it, through the surface."""
        match event:
            case protocol.FaderMoved(strip=strip, value=value):
                data = protocol.fader_moved(strip, value)
            case protocol.FaderTouched(strip=strip, touched=touched):
                data = protocol.fader_touched(strip, touched)
            case protocol.ButtonPressed(strip=strip, button=button, pressed=pressed):
                data = protocol.button(strip, button, pressed)
            case protocol.EncoderTurned(strip=strip, steps=steps):
                data = protocol.encoder_turned(strip, steps)
            case protocol.EncoderPressed(strip=strip, pressed=pressed):
                data = protocol.encoder_pressed(strip, pressed)
            case _:
                return
        self.surface.hand(data)

    # -- what the GUI draws -----------------------------------------------------------------------------------------

    def view(self) -> TwinView | None:
        """What the twin shows; None before its first step."""
        slots = self.slots.view()
        if slots is None:
            return None
        return TwinView(fingerprint(self.config), strip_states(self.surface, self._clock()), slots)
