"""The kinds of strips, and building them from the configuration."""

from typing import assert_never

from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.bindings import HOME_ASSISTANT, ValueBinding, WatchBinding, color_name
from xtouch_daemon.config.buttons import BUTTON_NAMES, ButtonName
from xtouch_daemon.config.strip import BaseStripConfig
from xtouch_daemon.config.strips import CustomStripConfig, EmptyStripConfig, HomeAssistantStripConfig, StripConfig
from xtouch_daemon.config.values import EncoderMode, MeterPoint, default_encoder
from xtouch_daemon.config.voip_strips import VoipStripConfig
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.strips.apps import AppGroupStrip, AppStrip, AutoStrip
from xtouch_daemon.strips.base import Identity, Look, StripController, StripEnv, VolumeStrip
from xtouch_daemon.strips.bound import Parts
from xtouch_daemon.strips.custom import CustomStrip
from xtouch_daemon.strips.device import ChoiceStrip, DeviceStrip
from xtouch_daemon.strips.homeassistant import HomeAssistantControls, HomeAssistantStrip, OfflineHomeAssistantStrip
from xtouch_daemon.strips.voip import VoipStrip
from xtouch_daemon.system.launch import LaunchButton
from xtouch_daemon.voip.provider import VoipProvider


class EmptyStrip(StripController):
    """A dark strip that does nothing."""

    def update(self, state: AudioState) -> None:
        self.strip.reset()


BUTTONS: dict[Button, ButtonName] = {Button.SELECT: "select", Button.REC: "rec", Button.SOLO: "solo"}


def look_of(config: StripConfig, meter_point: MeterPoint = "pre_fader") -> Look:
    """The look of a strip configuration; `meter_point` is where its meter takes the level (`Config.meter_point()`)."""
    match config:
        case EmptyStripConfig():
            return Look(meter=False)
        case HomeAssistantStripConfig():
            return Look(config.label, config.color, meter=False)
        case CustomStripConfig():
            # a bound color is white in the look; the custom strip shows the color of its line itself
            return Look(config.label, color_name(config.color), meter=False)
        case VoipStripConfig():
            return Look(config.label, config.color, config.meter, meter_point)
        case DeviceStripConfig() | AppsStripConfig() | AutoStripConfig():
            # a bound color is white until it is known; a bound meter shows no audio
            return Look(
                config.label if not isinstance(config, AutoStripConfig) else None,
                color_name(config.color),
                config.meter is True,
                meter_point,
                {button: config.button(name) for button, name in BUTTONS.items()},
                config.lit_when_idle,
                parts_of(config),
            )
        case _ as unreachable:
            assert_never(unreachable)


def parts_of(config: BaseStripConfig) -> Parts:
    """The parts of an audio strip that are bound (`config.bindings`)."""
    return Parts(
        config.fader if isinstance(config.fader, ValueBinding) else None,
        config.encoder if isinstance(config.encoder, ValueBinding) else None,
        config.lcd,
        config.color if config.color == HOME_ASSISTANT or isinstance(config.color, WatchBinding) else None,
        config.meter if not isinstance(config.meter, bool) else None,
    )


def home_assistant_controls(
    config: BaseStripConfig, strip: Strip, env: StripEnv, identity: Identity, encoder: EncoderMode
) -> HomeAssistantControls | None:
    """
    The parts of an audio strip in Home Assistant, and the numbers there of the values of its programs (with `[mqtt]`
    only); None for a strip without any.
    """
    bridge = env.bridge
    values = {name: part for name in ("fader", "encoder") if isinstance(part := getattr(config, name), ValueBinding)}
    if bridge is None or not (config.uses_home_assistant or values):
        return None
    return HomeAssistantControls(
        strip,
        env,
        bridge,
        identity,
        fader=config.fader == HOME_ASSISTANT,
        encoder=encoder == HOME_ASSISTANT,
        buttons=config.home_assistant_buttons,
        lcd=config.lcd == HOME_ASSISTANT,
        color=config.color == HOME_ASSISTANT,
        meter=config.meter == HOME_ASSISTANT,
        leds=tuple(name for name in BUTTON_NAMES if config.button(name).led == HOME_ASSISTANT),
        values=values,
    )


def launch_button(config: StripConfig, identity: Identity, env: StripEnv) -> LaunchButton | None:
    """What Select starts on a strip with `launch`; None for one without."""
    if not isinstance(config, AppsStripConfig | AutoStripConfig) or config.launch is None:
        return None
    return LaunchButton(config.launch, env.launcher, identity.name, always=config.launch_when_running)


def build_strip(
    config: StripConfig,
    strip: Strip,
    env: StripEnv,
    aliases: dict[str, str],
    identity: Identity,
    look: Look,
    voip: VoipProvider | None = None,
    home_assistant: bool = True,
) -> StripController:
    """
    The controller of a strip, with its identity and look (see `look_of()`); `voip` is the voice chat of the strips
    of people. Only a channel has entities in Home Assistant (`home_assistant`): a member (an application, a device)
    has none, its parts there show what they do while Home Assistant is not there.
    """
    if isinstance(config, EmptyStripConfig):
        return EmptyStrip(strip, env, identity, look)
    if isinstance(config, VoipStripConfig):
        assert voip is not None, "the strips of people need the voice chat"
        return VoipStrip(strip, env, identity, look, voip, config)
    if isinstance(config, HomeAssistantStripConfig):
        if env.bridge is None:
            # Simulate has no MQTT: the strip looks as while Home Assistant is not there
            return OfflineHomeAssistantStrip(strip, env, identity, look)
        return HomeAssistantStrip(strip, env, env.bridge, identity, look)
    if isinstance(config, CustomStripConfig):
        return CustomStrip(strip, env, identity, look, config, env.commands)
    # an encoder bound to a program does what its binding says (`Look.parts`), whatever its mode
    encoder = (
        default_encoder(config.type, config.fader)
        if config.encoder is None or isinstance(config.encoder, ValueBinding)
        else config.encoder
    )
    # without a bridge (Simulate) the parts in Home Assistant stay as while it is not connected
    controls = home_assistant_controls(config, strip, env, identity, encoder) if home_assistant else None
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
    controller.fader_in_home_assistant = config.fader == HOME_ASSISTANT
    if isinstance(controller, AppStrip):
        controller.launch = launch_button(config, identity, env)
    return controller
