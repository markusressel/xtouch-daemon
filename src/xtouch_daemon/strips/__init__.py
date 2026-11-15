"""The kinds of strips, and building them from the configuration."""

from typing import assert_never

from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config import (
    AppsStripConfig,
    AutoStripConfig,
    DeviceStripConfig,
    EmptyStripConfig,
    StripConfig,
    color_of,
)
from xtouch_daemon.strips.apps import AppGroupStrip, AutoStrip
from xtouch_daemon.strips.base import StripController, StripEnv
from xtouch_daemon.strips.device import DeviceStrip
from xtouch_daemon.surface import Strip


class EmptyStrip(StripController):
    """A dark strip that does nothing."""

    def update(self, state: AudioState) -> None:
        self.strip.reset()


def build_strip(config: StripConfig, strip: Strip, env: StripEnv, aliases: dict[str, str]) -> StripController:
    match config:
        case DeviceStripConfig():
            return DeviceStrip(
                strip,
                env,
                Direction(config.type),
                config.device,
                label=config.label,
                color=color_of(config.color),
                meter=config.meter,
                select=config.select,
            )
        case AppsStripConfig():
            return AppGroupStrip(strip, env, config.match, config.label, color_of(config.color), config.meter)
        case AutoStripConfig():
            return AutoStrip(strip, env, aliases, color_of(config.color), config.meter)
        case EmptyStripConfig():
            return EmptyStrip(strip, env)
        case _ as unreachable:
            assert_never(unreachable)
