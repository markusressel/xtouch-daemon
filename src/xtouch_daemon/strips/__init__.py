"""The kinds of strips, and building them from the configuration."""

from typing import assert_never

from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.layout_strips import InheritStripConfig, VoipStripConfig
from xtouch_daemon.config.strips import EmptyStripConfig, HomeAssistantStripConfig, StripConfig
from xtouch_daemon.config.values import MeterPoint, default_encoder
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.strips.apps import AppGroupStrip, AppStrip, AutoStrip
from xtouch_daemon.strips.base import Identity, Look, StripController, StripEnv, VolumeStrip
from xtouch_daemon.strips.device import ChoiceStrip, DeviceStrip
from xtouch_daemon.strips.homeassistant import HomeAssistantControls, HomeAssistantStrip
from xtouch_daemon.strips.voip import VoipSeat, VoipStrip
from xtouch_daemon.system.launch import LaunchButton


class EmptyStrip(StripController):
    """A dark strip that does nothing."""

    def update(self, state: AudioState) -> None:
        self.strip.reset()


def strip_identity(config: StripConfig, position: int) -> Identity:
    """
    The identity of a strip of strips and layouts, by its place in the configuration (from 0): its `id`, else
    `strip_<n>`; its label, else "Strip <n>".
    """
    strip_id = getattr(config, "id", None) or f"strip_{position + 1}"
    return Identity(strip_id, getattr(config, "label", None) or f"Strip {position + 1}")


def look_of(config: StripConfig, meter_point: MeterPoint = "pre_fader") -> Look:
    """The look of a strip of strips and layouts; `meter_point` is the one its layout gives it."""
    match config:
        case EmptyStripConfig() | InheritStripConfig():
            return Look(meter=False)
        case HomeAssistantStripConfig():
            return Look(config.label, config.color, meter=False)
        case VoipStripConfig():
            return Look(config.label, config.color, config.meter, meter_point)
        case DeviceStripConfig() | AppsStripConfig() | AutoStripConfig():
            return Look(
                config.label if not isinstance(config, AutoStripConfig) else None,
                config.color,
                config.meter,
                meter_point,
                {Button.REC: config.rec, Button.SOLO: config.solo},
                config.lit_when_idle,
            )
        case _ as unreachable:
            assert_never(unreachable)


def launch_button(config: StripConfig, identity: Identity, env: StripEnv) -> LaunchButton | None:
    """What Select starts on a strip with `launch`; None for one without."""
    if not isinstance(config, AppsStripConfig | AutoStripConfig | VoipStripConfig) or config.launch is None:
        return None
    always = not isinstance(config, VoipStripConfig) and config.launch_when_running
    return LaunchButton(config.launch, env.launcher, identity.name, always=always)


def build_strip(
    config: StripConfig,
    strip: Strip,
    env: StripEnv,
    aliases: dict[str, str],
    identity: Identity,
    look: Look,
    seat: VoipSeat | None = None,
) -> StripController:
    """
    The controller of a strip, with its identity and look (see `strip_identity()` and `look_of()`). `seat` is where a
    `voip` strip sits among those of its layout (see `Mixer`); `inherit` strips are resolved by `Config.all_strips()`
    already.
    """
    if isinstance(config, EmptyStripConfig):
        return EmptyStrip(strip, env, identity, look)
    assert not isinstance(config, InheritStripConfig), "all_strips() resolves inherit strips"
    if isinstance(config, VoipStripConfig):
        assert seat is not None, "the mixer seats voip strips"
        return VoipStrip(strip, env, identity, look, seat, config)
    if isinstance(config, HomeAssistantStripConfig):
        assert env.bridge is not None, "the configuration has no homeassistant strips without [mqtt]"
        return HomeAssistantStrip(strip, env, env.bridge, identity, look)
    encoder = config.encoder or default_encoder(config.type, config.fader)
    controls = None
    if config.uses_home_assistant:
        assert env.bridge is not None, "the configuration has no strips in Home Assistant without [mqtt]"
        controls = HomeAssistantControls(
            strip,
            env,
            env.bridge,
            identity,
            fader=config.fader == "homeassistant",
            encoder=encoder == "homeassistant",
        )
    match config:
        case DeviceStripConfig(choices=choices) if choices:
            controller: VolumeStrip = ChoiceStrip(
                strip,
                env,
                identity,
                Direction(config.type),
                choices,
                look,
                min_volume=config.min_volume,
                max_volume=config.max_volume,
                encoder=encoder,
                controls=controls,
            )
        case DeviceStripConfig():
            controller = DeviceStrip(
                strip,
                env,
                identity,
                Direction(config.type),
                config.device,
                look,
                select=config.select,
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
                identity,
                config.match,
                look,
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
                identity,
                aliases,
                look,
                config.min_volume,
                config.max_volume,
                encoder,
                controls,
            )
        case _ as unreachable:
            assert_never(unreachable)
    if isinstance(controller, AppStrip):
        controller.launch = launch_button(config, identity, env)
    return controller
