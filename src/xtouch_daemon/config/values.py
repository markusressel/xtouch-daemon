"""
The kinds of values of options (labels, volumes, colors, ...), and what the values of choices mean.
"""

import shlex
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, Field

from xtouch_daemon.config.base import Meanings
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Color

ColorName = Literal["off", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]

COLORS = Meanings({"off": "No backlight."})
"""The colors name themselves; only `off` needs a word."""


Indicator = Literal["off", "recording", "playing", "default", "muted"]
"""What a button LED shows, see `INDICATORS`."""

INDICATORS = Meanings(
    {
        "off": "The LED stays dark.",
        "recording": "Lit while an application records from the device, e.g. a screen recorder from an output. On "
        "`apps` and `auto` strips: while the application records anything. Level meters don't count.",
        "playing": "Lit while audio flows: the device runs, or a stream of the applications plays.",
        "default": "Lit while the device is the default output or input. Never on `apps` and `auto` strips.",
        "muted": "Lit while the strip is muted, like the Mute LED.",
    }
)


EncoderMode = Literal["volume", "balance", "pick", "media", "homeassistant"]
"""What the encoder of a strip does, see `ENCODER_MODES`."""

ENCODER_MODES = Meanings(
    {
        "volume": "Turn: the volume in fine steps (`behavior.encoder_step`), the fader follows. Push: "
        "`behavior.reset_volume`.",
        "balance": "Turn: the balance between left and right, 5 % per step. Push: centers it. Nothing on mono "
        "devices and streams.",
        "pick": "Turn: picks another application that has no strip of its own. Push: pins it, so it stays after it "
        "stopped playing.",
        "media": "Turn: seeks in the track of the media player, 5 s per step. Push: plays or pauses.",
        "homeassistant": "Turn: changes a number entity in Home Assistant (0..100), e.g. for the brightness of a "
        "light. Push: an event there. Needs `[mqtt]`.",
    }
)

MeterPoint = Literal["pre_fader", "post_fader"]
"""Where the meter of a strip takes the level, see `METER_POINTS`."""

METER_POINTS = Meanings(
    {
        "pre_fader": "The level before the volume, like on a hardware mixer: the meter stays up while the fader is "
        "down. A muted output still shows its level; muted applications and inputs go dark.",
        "post_fader": "The level after the volume and Mute: what you hear, or what applications get from the input. "
        "Dark while muted.",
    }
)

FaderMode = Literal["volume", "homeassistant"]

FADER_MODES = Meanings(
    {
        "volume": "The fader sets the volume.",
        "homeassistant": "The fader sets a number entity in Home Assistant (0..100), e.g. for the brightness of a "
        "light; the encoder sets the volume. Needs `[mqtt]`.",
    }
)

ENCODERS: dict[str, tuple[EncoderMode, ...]] = {
    "output": ("balance", "volume", "homeassistant"),
    "input": ("balance", "volume", "homeassistant"),
    "apps": ("media", "volume", "balance", "homeassistant"),
    "auto": ("pick", "media", "volume", "balance", "homeassistant"),
}
"""The encoders of each strip type, its default first."""


def default_encoder(strip_type: str, fader: str = "volume") -> EncoderMode:
    """What the encoder of a strip of the type does without `encoder`: the volume if the fader does not set it."""
    return "volume" if fader == "homeassistant" else ENCODERS[strip_type][0]


def color_of(name: ColorName) -> Color:
    return Color.BLACK if name == "off" else Color[name.upper()]


Label = Annotated[str, Field(max_length=protocol.LCD_CELL_WIDTH, pattern=r"^[\x20-\x7e]*$")]
"""What fits on the LCD: 7 characters of ASCII."""


VOLUME_LIMIT = 200
"""The loudest volume a fader may reach, in percent: above 100 % the audio is amplified in software."""

Volume = Annotated[int, Field(ge=0, le=VOLUME_LIMIT)]
"""A volume in percent."""


FaderNumber = Annotated[int, Field(ge=1, le=protocol.STRIPS)]
"""A fader of the device, 1 on the left."""

Sequence = Literal["instant", "sweep", "curtain", "show"]
"""How the strips light up after a connect and go dark at the end, see `surface.steps()`."""

STARTUP_SEQUENCES = Meanings(
    {
        "instant": "All strips light up at once.",
        "sweep": "One strip after the other from the left, 80 ms apart.",
        "curtain": "From the middle outwards, pair by pair (4 and 5 first, 1 and 8 last).",
        "show": "A wave of light runs across from the left: each strip lights up white, its meter jumps up and "
        "falls, its ring fills up. Behind it the strips show what they are, about 1.2 s after the connect.",
    }
)

SHUTDOWN_SEQUENCES = Meanings(
    {
        "instant": "All strips go dark at once.",
        "sweep": "One strip after the other from the right.",
        "curtain": "From the outside in, pair by pair.",
        "show": "From the right, each strip flashes white, its meter jumps up and its ring drains; then it goes dark.",
    }
)


Slug = Annotated[str, Field(pattern=r"^[a-z0-9_]+$", max_length=64)]
"""Part of entity IDs and MQTT topics: lower case letters, digits and underscores."""


def _split_command(value: object) -> object:
    """A command as one string is split like a shell would (quotes), but nothing is expanded."""
    if not isinstance(value, str):
        return value
    try:
        return tuple(shlex.split(value))
    except ValueError as e:
        raise ValueError(f"can't split the command: {e}") from e


def _a_command(value: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        raise ValueError("an empty command: name the program first")
    if any(not part.strip() for part in value):
        raise ValueError("an empty part of the command")
    return value


Command = Annotated[
    tuple[str, ...], BeforeValidator(_split_command, json_schema_input_type=str | list[str]), AfterValidator(_a_command)
]
"""A program and its arguments, run without a shell (`launch`)."""

LAUNCH_HELP = (
    "A program that Select starts while none of the applications runs: the program, then each argument, e.g. "
    '`["mumble", "mumble://me@voice.example.org/Gaming"]`. It runs without a shell, so nothing is expanded.'
)
"""The help of `launch`, which several strip types have."""
LAUNCH_WHEN_RUNNING_HELP = (
    "Select starts `launch` also while the application runs, e.g. a `mumble://` URL that connects a running Mumble "
    "to a server."
)
