"""
Helpers for the tests of the strips.
"""

import tomllib

from pydantic import TypeAdapter

from tests.support.audio import output, source
from tests.support.hardware import RecordingSurface
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config.strips import StripConfig
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.strips import build_strip, look_of, strip_identity
from xtouch_daemon.strips.base import Identity, Look, StripController, StripEnv
from xtouch_daemon.strips.device import DeviceStrip

ID = Identity("strip_1", "Strip 1")
"""The identity of a controller of the tests that has no other."""


def strips_of(text: str) -> tuple[StripConfig, ...]:
    """The strips of `[[strip]]` tables, as the configurations of channels and places are checked."""
    adapter = TypeAdapter[StripConfig](StripConfig)
    return tuple(adapter.validate_python(strip) for strip in tomllib.loads(text)["strip"])


def build(config: StripConfig, strip: Strip, env: StripEnv, aliases: dict[str, str] | None = None) -> StripController:
    """The controller of a strip of the configuration on `strip`, with the identity and look of its place."""
    return build_strip(config, strip, env, aliases or {}, strip_identity(config, strip.index), look_of(config))


def make(
    surface: RecordingSurface,
    env: StripEnv,
    direction: Direction = Direction.OUTPUT,
    device: str | tuple[str, ...] | None = "speaker",
    **kwargs: object,
) -> DeviceStrip:
    devices = () if device is None else (device,) if isinstance(device, str) else device
    look = Look(
        kwargs.pop("label", None),  # type: ignore[arg-type]
        "cyan",
        kwargs.pop("meter", True),  # type: ignore[arg-type]
        indicators=kwargs.pop("indicators", None) or {},  # type: ignore[arg-type]
    )
    return DeviceStrip(surface.strips[0], env, ID, direction, devices, look, **kwargs)  # type: ignore[arg-type]


STATE = AudioState(
    outputs=(output("speaker", 50), output("buds", 30, running=True)),
    inputs=(source("mic", 80),),
    default_output="buds",
    default_input="mic",
)


REC_SOLO = {Button.REC: "recording", Button.SOLO: "playing"}
