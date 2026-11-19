"""
Helpers for the tests of the strips.
"""

import tomllib
from collections.abc import Mapping

from pydantic import TypeAdapter

from tests.support.audio import output, source
from tests.support.hardware import RecordingSurface
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config.buttons import ButtonSetup
from xtouch_daemon.config.strips import StripConfig
from xtouch_daemon.config.values import Indicator
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.strips import build_strip, look_of
from xtouch_daemon.strips.base import Identity, Look, StripController, StripEnv
from xtouch_daemon.strips.device import DeviceStrip

ID = Identity("strip_1", "Strip 1")
"""The identity of a controller of the tests that has no other."""


def strips_of(text: str) -> tuple[StripConfig, ...]:
    """The strips of `[[strip]]` tables, as the configurations of channels and places are checked."""
    adapter = TypeAdapter[StripConfig](StripConfig)
    return tuple(adapter.validate_python(strip) for strip in tomllib.loads(text)["strip"])


def build(
    config: StripConfig,
    strip: Strip,
    env: StripEnv,
    aliases: dict[str, str] | None = None,
    name: str | None = None,
) -> StripController:
    """
    The controller of a strip of the configuration on `strip`, with the look of its place; `name` is its id (of the
    channel), by default `strip_<position>`.
    """
    position = strip.index + 1
    identity = Identity(name or f"strip_{position}", getattr(config, "label", None) or f"Strip {position}")
    return build_strip(config, strip, env, aliases or {}, identity, look_of(config))


def leds(indicators: Mapping[Button, Indicator]) -> dict[Button, ButtonSetup]:
    """Buttons that do nothing, whose LEDs show the indicators."""
    return {button: ButtonSetup(led=indicator) for button, indicator in indicators.items()}


def make(
    surface: RecordingSurface,
    env: StripEnv,
    direction: Direction = Direction.OUTPUT,
    device: str | tuple[str, ...] | None = "speaker",
    **kwargs: object,
) -> DeviceStrip:
    devices = () if device is None else (device,) if isinstance(device, str) else device
    buttons = leds(kwargs.pop("indicators", None) or {})  # type: ignore[arg-type]
    # as the configuration has them: Select makes the device the default, Rec switches the profiles
    buttons[Button.SELECT] = ButtonSetup("default" if kwargs.pop("select", True) and devices else "off", led="press")
    if kwargs.get("profiles"):
        buttons[Button.REC] = ButtonSetup("profile", led="press")
    look = Look(
        kwargs.pop("label", None),  # type: ignore[arg-type]
        "cyan",
        kwargs.pop("meter", True),  # type: ignore[arg-type]
        buttons=buttons,
    )
    return DeviceStrip(surface.strips[0], env, ID, direction, devices, look, **kwargs)  # type: ignore[arg-type]


STATE = AudioState(
    outputs=(output("speaker", 50), output("buds", 30, running=True)),
    inputs=(source("mic", 80),),
    default_output="buds",
    default_input="mic",
)


REC_SOLO: dict[Button, Indicator] = {Button.REC: "recording", Button.SOLO: "playing"}
