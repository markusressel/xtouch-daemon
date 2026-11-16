"""The kinds of strips, and building them from the configuration."""

from typing import assert_never

from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.layout_strips import InheritStripConfig, VoipStripConfig
from xtouch_daemon.config.strips import EmptyStripConfig, HomeAssistantStripConfig, StripConfig
from xtouch_daemon.config.values import Indicator, color_of, default_encoder
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.launch import LaunchButton
from xtouch_daemon.strips.apps import AppGroupStrip, AppStrip, AutoStrip
from xtouch_daemon.strips.base import StripController, StripEnv, VolumeStrip
from xtouch_daemon.strips.device import ChoiceStrip, DeviceStrip
from xtouch_daemon.strips.homeassistant import HomeAssistantControls, HomeAssistantStrip
from xtouch_daemon.strips.voip import VoipSeat, VoipStrip


class EmptyStrip(StripController):
    """A dark strip that does nothing."""

    def update(self, state: AudioState) -> None:
        self.strip.reset()


def launch_button(config: StripConfig, strip: Strip, env: StripEnv) -> LaunchButton | None:
    """What Select starts on a strip with `launch`; None for one without."""
    if not isinstance(config, AppsStripConfig | AutoStripConfig | VoipStripConfig) or config.launch is None:
        return None
    always = not isinstance(config, VoipStripConfig) and config.launch_when_running
    return LaunchButton(config.launch, env.launcher, f"Strip {strip.index + 1}", always=always)


def build_strip(
    config: StripConfig,
    strip: Strip,
    env: StripEnv,
    aliases: dict[str, str],
    seat: VoipSeat | None = None,
) -> StripController:
    """
    The controller of a strip. `seat` is where a `voip` strip sits among those of its layout (see `Mixer`);
    `inherit` strips are resolved by `Config.all_strips()` already.
    """
    if isinstance(config, EmptyStripConfig):
        return EmptyStrip(strip, env)
    assert not isinstance(config, InheritStripConfig), "all_strips() resolves inherit strips"
    if isinstance(config, VoipStripConfig):
        assert seat is not None, "the mixer seats voip strips"
        return VoipStrip(strip, env, seat, config)
    if isinstance(config, HomeAssistantStripConfig):
        assert env.bridge is not None, "the configuration has no homeassistant strips without [mqtt]"
        strip_id = config.id or f"strip_{strip.index + 1}"
        return HomeAssistantStrip(strip, env, env.bridge, strip_id, config.label, config.color)
    indicators: dict[Button, Indicator] = {Button.REC: config.rec, Button.SOLO: config.solo}
    encoder = config.encoder or default_encoder(config.type, config.fader)
    controls = None
    if config.uses_home_assistant:
        assert env.bridge is not None, "the configuration has no strips in Home Assistant without [mqtt]"
        controls = HomeAssistantControls(
            strip,
            env,
            env.bridge,
            config.id or f"strip_{strip.index + 1}",
            getattr(config, "label", None) or f"Strip {strip.index + 1}",
            fader=config.fader == "homeassistant",
            encoder=encoder == "homeassistant",
        )
    match config:
        case DeviceStripConfig(choices=choices) if choices:
            controller: VolumeStrip = ChoiceStrip(
                strip,
                env,
                Direction(config.type),
                choices,
                label=config.label,
                color=color_of(config.color),
                meter=config.meter,
                indicators=indicators,
                min_volume=config.min_volume,
                max_volume=config.max_volume,
                encoder=encoder,
                controls=controls,
                strip_id=config.id or f"strip_{strip.index + 1}",
            )
        case DeviceStripConfig():
            controller = DeviceStrip(
                strip,
                env,
                Direction(config.type),
                config.device,
                label=config.label,
                color=color_of(config.color),
                meter=config.meter,
                select=config.select,
                indicators=indicators,
                profiles=config.profiles,
                min_volume=config.min_volume,
                max_volume=config.max_volume,
                encoder=encoder,
                controls=controls,
            )
        case AppsStripConfig():
            controller = AppGroupStrip(
                strip,
                env,
                config.match,
                config.label,
                color_of(config.color),
                config.meter,
                indicators,
                config.min_volume,
                config.max_volume,
                encoder,
                controls,
                config.process_names,
            )
        case AutoStripConfig():
            controller = AutoStrip(
                strip,
                env,
                aliases,
                color_of(config.color),
                config.meter,
                indicators,
                config.min_volume,
                config.max_volume,
                encoder,
                controls,
            )
        case _ as unreachable:
            assert_never(unreachable)
    controller.lit_when_idle = config.lit_when_idle
    if isinstance(controller, AppStrip):
        controller.launch = launch_button(config, strip, env)
    return controller
