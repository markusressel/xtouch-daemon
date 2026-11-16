"""
Helpers for the tests of the strips.
"""

from tests.support.audio import output, source
from tests.support.hardware import RecordingSurface
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.hardware.protocol import Button, Color
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.strips.device import DeviceStrip


def make(
    surface: RecordingSurface,
    env: StripEnv,
    direction: Direction = Direction.OUTPUT,
    device: str | tuple[str, ...] | None = "speaker",
    **kwargs: object,
) -> DeviceStrip:
    devices = () if device is None else (device,) if isinstance(device, str) else device
    return DeviceStrip(surface.strips[0], env, direction, devices, color=Color.CYAN, **kwargs)  # type: ignore[arg-type]


STATE = AudioState(
    outputs=(output("speaker", 50), output("buds", 30, running=True)),
    inputs=(source("mic", 80),),
    default_output="buds",
    default_input="mic",
)


REC_SOLO = {Button.REC: "recording", Button.SOLO: "playing"}
