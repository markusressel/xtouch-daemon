"""The kinds of strips, and building them from the configuration."""

from typing import assert_never

from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config import (
    AppsStripConfig,
    AutoStripConfig,
    DeviceStripConfig,
    EmptyStripConfig,
    HomeAssistantStripConfig,
    Indicator,
    StripConfig,
    color_of,
)
from xtouch_daemon.protocol import Button
from xtouch_daemon.strips.apps import AppGroupStrip, AutoStrip
from xtouch_daemon.strips.base import StripController, StripEnv
from xtouch_daemon.strips.device import DeviceStrip
from xtouch_daemon.strips.homeassistant import HomeAssistantStrip
from xtouch_daemon.surface import Strip


class EmptyStrip(StripController):
    """A dark strip that does nothing."""

    def update(self, state: AudioState) -> None:
        self.strip.reset()


def build_strip(config: StripConfig, strip: Strip, env: StripEnv, aliases: dict[str, str]) -> StripController:
    if isinstance(config, EmptyStripConfig):
        return EmptyStrip(strip, env)
    if isinstance(config, HomeAssistantStripConfig):
        assert env.bridge is not None, "the configuration has no homeassistant strips without [mqtt]"
        strip_id = config.id or f"strip_{strip.index + 1}"
        return HomeAssistantStrip(strip, env, env.bridge, strip_id, config.label, config.color)
    indicators: dict[Button, Indicator] = {Button.REC: config.rec, Button.SOLO: config.solo}
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
                indicators=indicators,
            )
        case AppsStripConfig():
            return AppGroupStrip(
                strip, env, config.match, config.label, color_of(config.color), config.meter, indicators
            )
        case AutoStripConfig():
            return AutoStrip(strip, env, aliases, color_of(config.color), config.meter, indicators)
        case _ as unreachable:
            assert_never(unreachable)
