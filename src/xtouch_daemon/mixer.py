"""
The mixer: the strips of one configuration, fed with every audio state and every event of the device, and their
meters. A new configuration gets a new mixer on the same surface and sound server connection.
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
from xtouch_daemon.config import DEFAULT_LAYOUT, Config, StripConfig, VoipStripConfig
from xtouch_daemon.launch import Launcher
from xtouch_daemon.layouts import running_processes
from xtouch_daemon.media import MediaPlayers
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.strips import build_strip, launch_button
from xtouch_daemon.strips.apps import AppGroupStrip, AutoAssigner, AutoSlot, AutoStrip
from xtouch_daemon.strips.base import StripController, StripEnv
from xtouch_daemon.strips.voip import VoipGroup
from xtouch_daemon.surface import Surface
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
        self.state: AudioState = DISCONNECTED
        self.controllers: list[StripController] = []
        places = self._voip_places(config.all_strips(layout), surface, env)
        for strip_config, strip, place in zip(config.all_strips(layout), surface.strips, places, strict=True):
            self.controllers.append(build_strip(strip_config, strip, env, config.aliases, place))
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
        self, strips: tuple[StripConfig, ...], surface: Surface, env: StripEnv
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
                launch = launch_button(strip, surface.strips[index], env)
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
        for controller, meter in zip(self.controllers, self.meters, strict=True):
            controller.update(self.state)
            meter.watch(controller.meter_targets(self.state))

    def on_event(self, event: protocol.StripEvent) -> None:
        controller = self.controllers[event.strip]
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

    def close(self) -> None:
        if self.voip is not None:
            self.voip.unsubscribe(self.refresh)
        for controller, meter in zip(self.controllers, self.meters, strict=True):
            meter.close()
            controller.close()
