"""
The mixer: the strips of one configuration, fed with every audio state and every event of the device, and their
meters. A new configuration gets a new mixer on the same surface and sound server connection.
"""

import asyncio
import time
from collections.abc import Callable
from typing import assert_never

from xtouch_daemon import protocol
from xtouch_daemon.audio.backend import AudioBackend
from xtouch_daemon.audio.meter import PW_RECORD, CaptureTarget, Meter
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config import Config
from xtouch_daemon.strips import build_strip
from xtouch_daemon.strips.apps import AppGroupStrip, AutoAssigner, AutoStrip
from xtouch_daemon.strips.base import StripController, StripEnv
from xtouch_daemon.surface import Surface

METER_INTERVAL = 0.1
"""How often the meters show the peak since the last time (the device lets them fall in between)."""
AUTO_INTERVAL = 1.0
"""How often `auto` strips are checked for applications whose hold time is over."""


class Mixer:
    def __init__(
        self,
        surface: Surface,
        backend: AudioBackend,
        config: Config,
        clock: Callable[[], float] = time.monotonic,
        capture_command: str = PW_RECORD,
    ):
        env = StripEnv(backend, config.behavior)
        self.state: AudioState = DISCONNECTED
        self.controllers: list[StripController] = [
            build_strip(strip_config, strip, env, config.aliases)
            for strip_config, strip in zip(config.all_strips(), surface.strips, strict=True)
        ]
        self.auto_strips = [controller for controller in self.controllers if isinstance(controller, AutoStrip)]
        self.claimed = tuple(
            controller.patterns for controller in self.controllers if isinstance(controller, AppGroupStrip)
        )
        self.assigner = AutoAssigner(len(self.auto_strips), config.behavior.auto_hold, config.behavior.ignore, clock)
        self.meters = [self._meter(controller, capture_command) for controller in self.controllers]

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
        """Shows the meters, and lets `auto` strips go of applications that stopped long enough."""
        ticks_per_auto = round(AUTO_INTERVAL / METER_INTERVAL)
        tick = 0
        while True:
            await asyncio.sleep(METER_INTERVAL)
            for controller, meter in zip(self.controllers, self.meters, strict=True):
                level = meter.take_level()
                if level is not None:
                    controller.strip.set_meter(level)
            tick += 1
            if self.auto_strips and tick % ticks_per_auto == 0:
                self.refresh()

    def close(self) -> None:
        for controller, meter in zip(self.controllers, self.meters, strict=True):
            meter.close()
            controller.close()
