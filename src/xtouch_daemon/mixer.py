"""
The mixer: the strips of one configuration, fed with every audio state and every event of the device, and their
meters. A new configuration gets a new mixer on the same surface and sound server connection. With `collapse`, the
strips of the configuration move between the strips of the device (see `placement.py`).
"""

import asyncio
import time
from collections.abc import Callable, Mapping
from typing import assert_never

from haad_mqtt_autodiscovery.entity import MQTTEntity

from xtouch_daemon import protocol
from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.meter import PW_RECORD, CaptureTarget, Meter
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config import DEFAULT_LAYOUT, Config, StripConfig, VoipStripConfig, collapses
from xtouch_daemon.launch import Launcher
from xtouch_daemon.layouts import running_processes
from xtouch_daemon.media import MediaPlayers
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.placement import Flow, Placement
from xtouch_daemon.protocol import Button
from xtouch_daemon.strips import build_strip, launch_button
from xtouch_daemon.strips.apps import AppGroupStrip, AutoAssigner, AutoSlot, AutoStrip
from xtouch_daemon.strips.base import StripController, StripEnv
from xtouch_daemon.strips.voip import VoipGroup
from xtouch_daemon.surface import Surface, VirtualStrip
from xtouch_daemon.voip.provider import VoipProvider

METER_INTERVAL = 0.1
"""How often the meters show the peak since the last time (the device lets them fall in between)."""
AUTO_INTERVAL = 1.0
"""How often `auto` strips are checked for applications whose hold time is over."""
PROCESS_INTERVAL = 2.0
"""How often the processes are checked while a strip launches applications (`launch`), like the layout rules."""


class Mixer:
    def __init__(
        self,
        surface: Surface,
        backend: AudioBackend,
        config: Config,
        clock: Callable[[], float] = time.monotonic,
        capture_command: str = PW_RECORD,
        bridge: MqttBridge | None = None,
        players: MediaPlayers | None = None,
        layout: str = DEFAULT_LAYOUT,
        voip: VoipProvider | None = None,
        shared_entities: Mapping[MQTTEntity, str | None] | None = None,
        keep: frozenset[str] = frozenset(),
        preview: bool = False,
        launcher: Launcher | None = None,
        processes: Callable[[], frozenset[str]] = running_processes,
    ):
        """
        `layout` is the layout whose strips the mixer drives, `voip` the provider of the participants for `voip`
        strips. `shared_entities` are entities in Home Assistant that are not of a strip (e.g. the layout select),
        `keep` the unique ids of entities of the other layouts, which stay in Home Assistant. `preview`: the
        configuration is a live preview of the GUI (see `MqttBridge.set_entities()`). `launcher` starts the
        applications of strips with `launch`, `processes` tells the processes that run, which those need.
        """
        self.bridge = bridge
        self.layout = layout
        self.voip = voip
        self.shared_entities = dict(shared_entities or {})
        self.keep = keep
        self.preview = preview
        self._scan_processes = processes
        self.processes: frozenset[str] = frozenset()
        """The processes that run, while a strip launches an application (`launch`), every PROCESS_INTERVAL."""
        env = StripEnv(backend, config.behavior, bridge, players, voip, launcher or Launcher(), lambda: self.processes)
        self.surface = surface
        self.state: AudioState = DISCONNECTED
        self.controllers: list[StripController] = []
        strips = config.all_strips(layout)
        self.strips = [VirtualStrip(surface, index) for index in range(len(strips))]
        """What each strip of the configuration shows, on the strip of the device it is on (see `flow`)."""
        places = self._voip_places(strips, self.strips, env)
        for strip_config, strip, place in zip(strips, self.strips, places, strict=True):
            self.controllers.append(build_strip(strip_config, strip, env, config.aliases, place))
        self.flow = Flow(
            self.strips,
            surface.strips,
            [collapses(strip) for strip in strips],
            lambda index: self.controllers[index].title,
            config.behavior.collapse_hold,
            clock,
        )
        self._touched: set[int] = set()
        """The faders of the device (from 0) a finger is on."""
        self._held: set[tuple[int, Button | None]] = set()
        """The buttons of the device held down: the strip (from 0) and the button, None for the encoder."""
        self.auto_strips = [controller for controller in self.controllers if isinstance(controller, AutoStrip)]
        self.claimed = tuple(
            controller.patterns for controller in self.controllers if isinstance(controller, AppGroupStrip)
        )
        self.assigner = AutoAssigner(len(self.auto_strips), config.behavior.auto_hold, config.behavior.ignore, clock)
        for index, auto in enumerate(self.auto_strips):
            auto.slot = AutoSlot(self.assigner, index, lambda: self.state, self.claimed, self.refresh)
        self.meters = [self._meter(controller, capture_command) for controller in self.controllers]
        self.watches_processes = any(controller.launches for controller in self.controllers)
        if self.watches_processes:
            self.processes = processes()
        self.entities = {
            entity: default for controller in self.controllers for entity, default in controller.entities.items()
        }
        """The entities of the strips in Home Assistant, for the MQTT bridge."""
        if voip is not None:
            voip.subscribe(self.refresh)

    def _voip_places(
        self, strips: tuple[StripConfig, ...], views: list[VirtualStrip], env: StripEnv
    ) -> list[tuple[VoipGroup, int] | None]:
        """The group and the place in it of every `voip` strip: its places are the same object (`all_strips()`)."""
        places: list[tuple[VoipGroup, int] | None] = []
        previous: tuple[VoipGroup, int] | None = None
        for index, strip in enumerate(strips):
            if not isinstance(strip, VoipStripConfig):
                previous = None
            elif previous is not None and strips[index - 1] is strip and previous[1] + 1 < strip.count:
                previous = (previous[0], previous[1] + 1)
            else:
                assert self.voip is not None, "the configuration has no voip strips without [voip]"
                launch = launch_button(strip, views[index], env)
                previous = (VoipGroup(self.voip, strip.count, self.refresh, launch, env.processes), 0)
            places.append(previous)
        return places

    def _meter(self, controller: StripController, command: str) -> Meter:
        def playing(target: CaptureTarget) -> bool:
            return controller.is_playing(target, self.state)

        return Meter(playing, command)

    # -- input ----------------------------------------------------------------------------------------------------

    def on_state(self, state: AudioState) -> None:
        self.state = state
        self.refresh()

    def refresh(self) -> None:
        for strip, app in zip(self.auto_strips, self.assigner.assign(self.state, self.claimed), strict=True):
            strip.assign(app)
        for controller in self.controllers:
            controller.update(self.state)
        self._place()
        self._watch_meters()

    def _watch_meters(self) -> None:
        """The meters capture for the strips on the device only."""
        for index, (controller, meter) in enumerate(zip(self.controllers, self.meters, strict=True)):
            on_device = self.flow.position(index) is not None
            meter.watch(controller.meter_targets(self.state) if on_device else set())

    def _place(self) -> bool:
        """Moves the strips if one collapsed or came back (not while a finger is on the device); True if they moved."""
        absent = [controller.absent(self.state) for controller in self.controllers] if self.state.connected else None
        busy = bool(self._touched or self._held) or any(strip.held for strip in self.surface.strips)
        return self.flow.update(absent, busy)

    @property
    def placement(self) -> Placement:
        """For each strip of the device, the place of the strip of the configuration it shows."""
        return self.flow.placement

    def on_event(self, event: protocol.StripEvent) -> None:
        self._follow_hands(event)
        index = self.flow.strip_at(event.strip)
        released = isinstance(event, protocol.FaderTouched | protocol.ButtonPressed | protocol.EncoderPressed)
        if index is not None:
            self._handle(self.controllers[index], event)
        if released and not (self._touched or self._held) and self._place():
            # what waited for the hand to let go
            self._watch_meters()

    def _follow_hands(self, event: protocol.StripEvent) -> None:
        """Which faders are touched and which buttons held: the strips don't move under a finger."""
        match event:
            case protocol.FaderTouched(strip=strip, touched=touched):
                (self._touched.add if touched else self._touched.discard)(strip)
            case protocol.ButtonPressed(strip=strip, button=button, pressed=pressed):
                (self._held.add if pressed else self._held.discard)((strip, button))
            case protocol.EncoderPressed(strip=strip, pressed=pressed):
                (self._held.add if pressed else self._held.discard)((strip, None))
            case _:
                pass

    @staticmethod
    def _handle(controller: StripController, event: protocol.StripEvent) -> None:
        match event:
            case protocol.FaderMoved(value=value):
                controller.on_fader(protocol.fader_fraction(value))
            case protocol.FaderTouched(touched=touched):
                controller.on_touch(touched)
            case protocol.ButtonPressed(button=button, pressed=pressed):
                controller.on_button(button, pressed)
            case protocol.EncoderTurned(steps=steps):
                controller.on_encoder(steps)
            case protocol.EncoderPressed(pressed=pressed):
                controller.on_encoder_press(pressed)
            case _ as unreachable:
                assert_never(unreachable)

    # -- running --------------------------------------------------------------------------------------------------

    async def run(self) -> None:
        """
        Announces the entities of the `homeassistant` strips, then shows the meters and lets `auto` strips go of
        applications that stopped long enough.
        """
        if self.bridge is not None:
            await self.bridge.set_entities(self.entities | self.shared_entities, keep=self.keep, preview=self.preview)
        ticks_per_auto = round(AUTO_INTERVAL / METER_INTERVAL)
        ticks_per_scan = round(PROCESS_INTERVAL / METER_INTERVAL)
        tick = 0
        while True:
            await asyncio.sleep(METER_INTERVAL)
            for controller, meter in zip(self.controllers, self.meters, strict=True):
                level = meter.take_level()
                if level is None:
                    level = controller.held_meter()
                if level is not None:
                    controller.strip.set_meter(level)
            tick += 1
            if self.watches_processes and tick % ticks_per_scan == 0:
                # a launched application shows up, the LED of a launch that took too long stops flashing
                self.processes = self._scan_processes()
                self.refresh()
            elif self.auto_strips and tick % ticks_per_auto == 0:
                self.refresh()
            elif self._place():
                # a strip collapsed after its hold time
                self._watch_meters()

    def close(self) -> None:
        if self.voip is not None:
            self.voip.unsubscribe(self.refresh)
        for controller, meter in zip(self.controllers, self.meters, strict=True):
            meter.close()
            controller.close()
        for strip in self.strips:
            # the next mixer draws on the device
            strip.target = None
