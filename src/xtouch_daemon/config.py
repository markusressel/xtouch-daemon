"""
The configuration: a TOML file, by default `$XDG_CONFIG_HOME/xtouch-daemon/config.toml`. See `config.example.toml`
(also written by `xtouch-daemon init-config`) for every option.
"""

import os
import shlex
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Annotated, Literal, get_args

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    PrivateAttr,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from xtouch_daemon import presets, protocol
from xtouch_daemon.protocol import Color

APP_NAME = "xtouch-daemon"


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME / "config.toml"


def example_config() -> str:
    return resources.files("xtouch_daemon").joinpath("config.example.toml").read_text(encoding="utf-8")


class _Model(BaseModel):
    # a typo in an option name is an error, not silently ignored; the docstrings of the fields are their descriptions,
    # which the GUI shows as help
    model_config = ConfigDict(extra="forbid", frozen=True, use_attribute_docstrings=True)


def _no_blank(value: tuple[str, ...]) -> tuple[str, ...]:
    if any(not pattern.strip() for pattern in value):
        raise ValueError("an empty pattern would match every application")
    return value


@dataclass(frozen=True)
class Presets:
    """
    The metadata of a list of names that may have presets (`@browsers`): what its names are matched against. The
    list holds the expanded names; `_WithPresets.written()` has the entries as written.
    """

    kind: presets.Kind


def _expand_streams(value: tuple[str, ...]) -> tuple[str, ...]:
    return presets.expand(value, presets.Kind.STREAMS)


def _expand_processes(value: tuple[str, ...]) -> tuple[str, ...]:
    return presets.expand(value, presets.Kind.PROCESSES)


StreamNames = Annotated[
    tuple[str, ...], AfterValidator(_no_blank), AfterValidator(_expand_streams), Presets(presets.Kind.STREAMS)
]
"""Parts of the names or binaries of applications (ignoring case), and presets of them."""
ProcessNames = Annotated[
    tuple[str, ...], AfterValidator(_no_blank), AfterValidator(_expand_processes), Presets(presets.Kind.PROCESSES)
]
"""Parts of the names of processes (ignoring case), and presets of them."""


class _WithPresets(_Model):
    """A model with lists of names (`StreamNames`, `ProcessNames`): they keep the entries as written."""

    _written: dict[str, tuple[str, ...]] = PrivateAttr(default_factory=dict)
    """The lists with presets as written, by option; the options hold what the presets stand for."""

    @model_validator(mode="wrap")
    @classmethod
    def _keep_written(cls, data: object, handler: ModelWrapValidatorHandler[_WithPresets]) -> _WithPresets:
        model = handler(data)
        if isinstance(data, Mapping):
            for name in cls.preset_options():
                written = data.get(name)
                if isinstance(written, list | tuple) and any(presets.is_preset(str(entry)) for entry in written):
                    model._written[name] = tuple(map(str, written))
        return model

    @classmethod
    def preset_options(cls) -> dict[str, presets.Kind]:
        """The options that are lists of names with presets, and what their names are matched against."""
        return {
            name: item.kind
            for name, field in cls.model_fields.items()
            for item in field.metadata
            if isinstance(item, Presets)
        }

    def written(self, name: str) -> tuple[str, ...]:
        """The entries of a list of names as written, with the presets (e.g. `@browsers`) instead of their names."""
        written: tuple[str, ...] = self._written[name] if name in self._written else getattr(self, name)
        return written


@dataclass(frozen=True, eq=False)
class Meanings:
    """
    What the values of a choice mean, as metadata of its option (`Annotated[Indicator, INDICATORS]`): the GUI shows
    the meaning of the chosen value. Keep it in line with the tables of the docs.
    """

    meanings: Mapping[str, str]


ColorName = Literal["off", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]

COLORS = Meanings({"off": "No backlight."})
"""The colors name themselves; only `off` needs a word."""


Indicator = Literal["off", "recording", "playing", "default", "muted"]
"""What a button LED shows, see `INDICATORS`."""

INDICATORS = Meanings(
    {
        "off": "The LED stays dark.",
        "recording": "Lit while an application records: from the input, from the monitor of the output (e.g. a "
        "screen recorder), or on `apps` and `auto` strips, while the application records anything (e.g. Discord "
        "using a microphone). Level meters don't count.",
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
        "pick": "Turn: picks the application of the strip among those without a strip of their own. Push: pins it, "
        "so it stays after it stopped playing.",
        "media": "Turn: seeks in the track of the applications' media player (MPRIS), 5 s per step. Push: plays or "
        "pauses.",
        "homeassistant": "Turn: changes a number entity in Home Assistant (0..100), e.g. for the brightness of a "
        "light. Push: an event there. Needs `[mqtt]`.",
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

MAX_STRIPS = 32
"""
The most strips a layout may have: more than the 8 of the device only with `collapse`, see `Config.unreachable()`.
"""


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


class DeviceConfig(_Model):
    """The device the daemon drives."""

    name: str = "X-Touch-Ext"
    """Part of the name of the extender's sound card, as `/proc/asound/cards` lists it."""
    touch_required: bool = True
    """
    Whether a fader changes a value only while the device reports a touch, so a fader moved by its motor does not
    count. Off, every move counts, as on `touchless_faders`: e.g. pushing a fader from below with a fingertip, which
    the touch sensor does not notice.
    """
    touchless_faders: tuple[FaderNumber, ...] = ()
    """
    Faders whose touch sensor does not work, numbered from 1 on the left: a move counts as a touch, half a second
    without a move as letting go. Without it such a fader goes back to its value after every move.
    """
    startup: Annotated[Sequence, STARTUP_SEQUENCES] = "sweep"
    """How the strips light up after the device connects."""
    shutdown: Annotated[Sequence, SHUTDOWN_SEQUENCES] = "sweep"
    """How the strips go dark when the daemon stops."""


class BehaviorConfig(_WithPresets):
    """How the faders, encoders, meters and `auto` strips behave."""

    max_volume: Annotated[int, Field(ge=100, le=VOLUME_LIMIT)] = 130
    """
    The volume of a fader at the top, in percent: above 100 % the audio is amplified in software. Strips may have a
    range of their own (`min_volume`, `max_volume`). 130 puts 100 % at the 0 dB mark of the device (see `unity_at`)
    with the same slope above it as below, so the fader is linear over its whole travel.
    """
    unity_at: Annotated[int, Field(ge=10, le=95)] = 77
    """
    Where on the fader 100 % is, in percent of its travel from the bottom; the X-Touch Extender marks 0 dB at about
    77. Below that mark the fader goes up to 100 %, above it from 100 % to the `max_volume` of the strip, e.g. with
    77 and 130 the top 23 % of the travel amplify by up to 30 %. Strips whose range ends at 100 % (or starts above
    it) are not affected: their fader is linear from the bottom to the top.
    """
    encoder_step: Annotated[int, Field(ge=1, le=10)] = 1
    """
    Percent per step of an encoder: of the volume with the `volume` encoder, of the number with a `homeassistant`
    one.
    """
    reset_volume: Volume = 100
    """The volume a push on a `volume` encoder sets, at most `max_volume` (and within the range of the strip)."""
    meters: bool = True
    """Whether the LED meters show audio levels at all. Off, every meter stays dark; `meter` turns off a single one."""
    auto_hold: Annotated[float, Field(ge=0)] = 5.0
    """
    Seconds an `auto` strip keeps an application after it stopped playing, so a music player does not jump to
    another strip between two tracks.
    """
    ignore: StreamNames = ("speech-dispatcher",)
    """
    Applications that `auto` strips never take: parts of the name or binary, ignoring case, e.g. "notification" for
    notification sounds, or presets like `@games`.
    """
    collapse_hold: Annotated[float, Field(ge=0)] = 3.0
    """
    Seconds a strip with `collapse` keeps its fader after it has nothing to control anymore, before the strips after
    it move up. It comes back at once.
    """

    @model_validator(mode="after")
    def _reset_within_reach(self) -> BehaviorConfig:
        if self.reset_volume > self.max_volume:
            raise ValueError(f"reset_volume ({self.reset_volume}) is above max_volume ({self.max_volume})")
        return self


Slug = Annotated[str, Field(pattern=r"^[a-z0-9_]+$", max_length=64)]
"""Part of entity IDs and MQTT topics: lower case letters, digits and underscores."""


class _StripConfig(_Model):
    color: Annotated[ColorName, COLORS] = "white"
    """The backlight of the LCD. It is dark while the strip has nothing to control, unless `lit_when_idle` is on."""
    lit_when_idle: bool = False
    """
    Whether the LCD keeps its backlight while the strip has nothing to control: no application of an `apps` group
    plays, the device of a device strip is not there, an `auto` strip has no application. The label stays readable
    then; the fader stays down all the same.
    """
    meter: bool = True
    """Whether this strip's LED meter shows the level (if `behavior.meters` is on)."""
    rec: Annotated[Indicator, INDICATORS] = "recording"
    """What the LED of the Rec button shows. The button itself does nothing (except with `profiles`)."""
    solo: Annotated[Indicator, INDICATORS] = "off"
    """What the LED of the Solo button shows. The button itself does nothing."""
    min_volume: Volume | None = None
    """
    The volume of the fader at the bottom, in percent; by default 0. E.g. 50 gives the whole travel of the fader to
    the upper half.
    """
    max_volume: Volume | None = None
    """
    The volume of the fader at the top, in percent; by default `behavior.max_volume`. Above 100 % the audio is
    amplified in software, e.g. 200 for weak speakers.
    """
    encoder: Annotated[EncoderMode, ENCODER_MODES] | None = None
    """What the encoder does when it is turned and pushed; its LED ring shows the value."""
    fader: Annotated[FaderMode, FADER_MODES] = "volume"
    """What the fader sets."""
    id: Slug | None = None
    """
    With `fader` or `encoder` in Home Assistant (or `choices` and `[mqtt]`): part of the entity IDs, e.g. "desk" for
    `number.xtouch_desk_fader`; by default `strip_<position>` (its place in the list, not on the device), so set it to
    keep the entities when moving the strip.
    """
    collapse: bool = False
    """
    Whether the strip gives its fader to the strips after it while it has nothing to control (see `collapse_hold`):
    its devices are not there, no application of an `apps` group has a stream, an `auto` strip has no application. The
    strips after it move one place to the left, and back when it returns. Moving strips are bad for muscle memory, the
    LCDs say what each strip is.
    """

    @property
    def uses_home_assistant(self) -> bool:
        return "homeassistant" in (self.fader, self.encoder)

    @model_validator(mode="after")
    def _encoder_of_the_type(self) -> _StripConfig:
        strip_type = str(getattr(self, "type", ""))
        if self.encoder is not None and self.encoder not in ENCODERS[strip_type]:
            raise ValueError(
                f"encoder: {self.encoder} is not for {strip_type} strips ({', '.join(ENCODERS[strip_type])})"
            )
        if self.fader == "homeassistant" and self.encoder not in (None, "volume"):
            raise ValueError("encoder: with the fader in Home Assistant, the encoder sets the volume")
        if getattr(self, "launch_when_running", False) and getattr(self, "launch", None) is None:
            raise ValueError("launch_when_running: needs launch")
        return self

    def volume_ranges(self, behavior: BehaviorConfig) -> list[tuple[str, int, int]]:
        """Where each volume range of the strip is configured (e.g. `profiles[2]`, "" for the strip), and the range."""
        bottom = 0 if self.min_volume is None else self.min_volume
        top = behavior.max_volume if self.max_volume is None else self.max_volume
        return [("", bottom, top)]


class ProfileConfig(_Model):
    """A profile of the sound card of a device strip, e.g. analog or digital output."""

    label: Label
    """The top line of the LCD while the card is in this profile, e.g. "Phones" for the analog output."""
    profile: str
    """
    The name (`output:iec958-stereo+input:analog-stereo`) or description of the profile (`xtouch-daemon list-devices`).
    """
    min_volume: Volume | None = None
    """The volume of the fader at the bottom in this profile; by default the one of the strip."""
    max_volume: Volume | None = None
    """The volume of the fader at the top in this profile (e.g. 200 for weak speakers); by default the strip's."""


class ChoiceConfig(_Model):
    """One of the devices a strip switches between with Select, maybe in a profile of its sound card."""

    label: Label | None = None
    """The top line of the LCD while this choice is active; by default the start of the device's description."""
    device: str
    """
    The node name (`xtouch-daemon list-devices`) or description of the device; `*` and `?` are wildcards, e.g.
    `bluez_output.*` for the first Bluetooth headphones there are.
    """
    card: str | None = None
    """
    The sound card whose `profile` the choice needs, by its name (`alsa_card.pci-0000_11_00.4`) or description
    (`xtouch-daemon list-devices`); wildcards allowed.
    """
    profile: str | None = None
    """
    The profile of `card` the device is in, by its name (`output:iec958-stereo+input:analog-stereo`) or
    description. Select switches the card to it first, then the device of the choice becomes the default.
    """
    min_volume: Volume | None = None
    """The volume of the fader at the bottom while this choice is active; by default the one of the strip."""
    max_volume: Volume | None = None
    """The volume of the fader at the top while this choice is active (e.g. 200 for weak speakers)."""

    @field_validator("device")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an empty device name")
        return value

    @model_validator(mode="after")
    def _card_and_profile(self) -> ChoiceConfig:
        if (self.card is None) != (self.profile is None):
            raise ValueError("card and profile go together: the profile of which card")
        return self

    @property
    def title(self) -> str:
        """The label, or else the device: for messages and Home Assistant."""
        return self.label or self.device


STRIP_TYPE_MEANINGS = Meanings(
    {
        "output": "An output device (speakers, headphones): the fader sets its volume. One device, one of several, or "
        "whatever is the default output.",
        "input": "An input device (a microphone): the fader sets its volume. One device, one of several, or whatever "
        "is the default input.",
        "apps": "All playback streams of a group of applications, e.g. every browser, like the per-application "
        "sliders of pavucontrol.",
        "auto": "The next application that plays and has no strip of its own. Strips that are not configured are "
        "auto strips.",
        "homeassistant": "A strip that belongs to Home Assistant: its fader, encoder, LCD, LEDs and buttons are "
        "entities there, and automations decide what they do. Needs `[mqtt]`.",
        "empty": "A dark strip that does nothing; its fader stays at the bottom.",
        "inherit": "In a `[[layout]]`: the strip of the default layout (the top-level `[[strip]]` list) at this "
        "place, e.g. the same output in every layout; or, with `layout` and `strip`, any strip of any layout.",
        "voip": "A participant of the voice chat: the fader sets their volume, Mute mutes them for you, the meter "
        "shows their voice. With `person`, always the same one; the voip strips without it are a group that fills "
        "with the others, and Select on one of them shows the next ones.",
    }
)
"""What each strip type is, shown when it is chosen."""


class DeviceStripConfig(_StripConfig):
    """An output or an input device, or whatever is the default one."""

    type: Annotated[Literal["output", "input"], STRIP_TYPE_MEANINGS]
    device: tuple[str, ...] = ()
    """
    The node name (`xtouch-daemon list-devices`) or description of the device; without it the default device. Several
    (a list, or `*` wildcards like `bluez_output.*`): the strip shows the one of them that is the default, or else the
    one shown last, and Select switches between those that are there.
    """
    label: Label | None = None
    """
    The top line of the LCD; by default "Output" or "Input", or the start of the device's description. The label of
    the active profile (`profiles`) comes first.
    """
    select: bool = True
    """
    Whether the Select button makes the device the default (needs `device` or `choices`); with several devices, a
    press on the default one switches to the next. Its LED is on while the device is the default.
    """
    choices: tuple[ChoiceConfig, ...] = ()
    """
    The devices to switch between with Select, each maybe in a profile of its sound card, e.g. headphones on the
    analog output, speakers on the digital one of the same card, and Bluetooth headphones. Select goes to the next
    one that is there and makes it the default. Instead of `device` and `profiles`.
    """
    profiles: tuple[ProfileConfig, ...] = ()
    """
    Profiles of the device's sound card to switch between with the Rec button, e.g. analog and digital output. Its
    LED is on for every profile but the first. Name `device` so that it matches the devices of every profile (e.g.
    `alsa_output.pci-0000_11_00.4.*`): each profile has a device of its own. `choices` does the same with Select.
    """

    @field_validator("device", mode="before")
    @classmethod
    def _one_or_several(cls, value: object) -> object:
        return (value,) if isinstance(value, str) else value

    @field_validator("device")
    @classmethod
    def _no_blank_device(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not name.strip() for name in value):
            raise ValueError("an empty device name")
        return value

    @field_validator("profiles", "choices")
    @classmethod
    def _two_profiles[T: tuple[ProfileConfig, ...] | tuple[ChoiceConfig, ...]](cls, value: T) -> T:
        if len(value) == 1:
            raise ValueError("at least two to switch between")
        return value

    def volume_ranges(self, behavior: BehaviorConfig) -> list[tuple[str, int, int]]:
        ranges = super().volume_ranges(behavior)
        _, bottom, top = ranges[0]
        for name, options in (("profiles", self.profiles), ("choices", self.choices)):
            for number, option in enumerate(options, start=1):
                ranges.append(
                    (
                        f"{name}[{number}]",
                        bottom if option.min_volume is None else option.min_volume,
                        top if option.max_volume is None else option.max_volume,
                    )
                )
        return ranges

    @model_validator(mode="after")
    def _profiles_take_rec(self) -> DeviceStripConfig:
        if self.profiles and "rec" in self.model_fields_set:
            raise ValueError("rec: with profiles its LED shows the profile")
        return self

    @model_validator(mode="after")
    def _choices_alone(self) -> DeviceStripConfig:
        if not self.choices:
            return self
        if self.device or self.profiles:
            raise ValueError("use either choices or device/profiles")
        if not self.select:
            raise ValueError("select: with choices, Select is how the strip switches between them")
        return self

    @property
    def switches(self) -> bool:
        """Whether Select switches between `choices`."""
        return bool(self.choices)


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


Command = Annotated[tuple[str, ...], BeforeValidator(_split_command), AfterValidator(_a_command)]
"""A program and its arguments, run without a shell (`launch`)."""

LAUNCH_HELP = (
    "A command that Select starts while none of the strip's applications runs, as a list: the program, then its "
    'arguments, e.g. `["mumble", "mumble://me@voice.example.org/Gaming"]`. Never through a shell. A single string is '
    "split like a shell would (quotes), but nothing is expanded."
)
"""The help of `launch`, which several strip types have."""
LAUNCH_WHEN_RUNNING_HELP = (
    "Whether Select starts `launch` also while the application runs, e.g. a `mumble://` URL to connect a running "
    "Mumble to the server. Otherwise Select does nothing then."
)


class AppsStripConfig(_StripConfig, _WithPresets):
    """All streams of a group of applications, e.g. every browser."""

    type: Annotated[Literal["apps"], STRIP_TYPE_MEANINGS]
    match: Annotated[StreamNames, Field(min_length=1)]
    """
    Parts of the names or binaries of the applications (ignoring case), see `xtouch-daemon list-apps`, e.g. "brave",
    or presets of well-known ones, e.g. `@browsers`, `@voip`, `@games`.
    """
    label: Label
    """The top line of the LCD, e.g. "VoIP"."""
    launch: Command | None = Field(default=None, description=LAUNCH_HELP)
    launch_when_running: bool = Field(default=False, description=LAUNCH_WHEN_RUNNING_HELP)

    @property
    def process_names(self) -> tuple[str, ...]:
        """
        The parts of the names of the processes of the applications, whose processes count as running (`launch`): the
        plain entries of `match`, and the processes of its presets.
        """
        return presets.expand_known(self.written("match"), presets.Kind.PROCESSES)


class AutoStripConfig(_StripConfig):
    """The next application that plays and has no strip of its own."""

    type: Annotated[Literal["auto"], STRIP_TYPE_MEANINGS]
    launch: Command | None = Field(default=None, description=LAUNCH_HELP)
    launch_when_running: bool = Field(default=False, description=LAUNCH_WHEN_RUNNING_HELP)


def _refuse_collapse(data: object, why: str) -> object:
    if isinstance(data, Mapping) and "collapse" in data:
        raise ValueError(f"collapse: {why}")
    return data


class EmptyStripConfig(_Model):
    """A dark strip that does nothing."""

    type: Annotated[Literal["empty"], STRIP_TYPE_MEANINGS]

    @model_validator(mode="before")
    @classmethod
    def _no_collapse(cls, data: object) -> object:
        return _refuse_collapse(data, "an empty strip is there to keep its place")


class HomeAssistantStripConfig(_Model):
    """A strip that belongs to Home Assistant: its parts are entities there, automations decide what they do."""

    type: Annotated[Literal["homeassistant"], STRIP_TYPE_MEANINGS]
    id: Slug | None = None
    """
    Part of the entity IDs, e.g. "living_room" for `number.xtouch_living_room_fader`; by default `strip_<position>`,
    so set it to keep the entities (and the automations that use them) when moving the strip.
    """
    label: Label | None = None
    """The top line of the LCD until Home Assistant sets one; also the start of the entity names."""
    color: Annotated[ColorName, COLORS] = "white"
    """The LCD backlight until Home Assistant sets one."""

    @model_validator(mode="before")
    @classmethod
    def _no_collapse(cls, data: object) -> object:
        return _refuse_collapse(data, "a homeassistant strip stays, automations rely on its entities")


class InheritStripConfig(_Model):
    """
    A strip of another layout (or of its own), with all its options: by default the strip of the default layout at
    this place.
    """

    type: Annotated[Literal["inherit"], STRIP_TYPE_MEANINGS]
    layout: Slug | None = None
    """The `name` of the layout of the strip; by default the default layout (the top-level `[[strip]]` list)."""
    strip: Annotated[int, Field(ge=1, le=MAX_STRIPS)] | Slug | None = None
    """
    The strip in that layout: its position in the layout's list (from 1), or its `id`; by default the strip at this
    place.
    """


INHERIT_LIMIT = 8
"""How many `inherit` strips may refer to one another in a row."""

type _Entry = tuple[int, int]
"""A strip in the list of a layout: the index of the layout in `Config.layout_list()` and the position, from 0."""


class _Inheritance:
    """Resolves `inherit` strips into the strips they refer to; ValueError for a reference that can't be resolved."""

    def __init__(self, layouts: tuple[LayoutConfig, ...]):
        self.layouts = layouts
        self.names = [layout.name for layout in layouts]

    def where(self, entry: _Entry) -> str:
        layout, position = entry
        return (f"layout[{layout}].strip" if layout else "strip") + f"[{position + 1}]"

    def _strip(self, entry: _Entry) -> StripConfig:
        return self.layouts[entry[0]].strips[entry[1]]

    def _enter(self, entry: _Entry, chain: tuple[_Entry, ...]) -> tuple[_Entry, ...]:
        if entry in chain:
            cycle = [*chain[chain.index(entry) :], entry]
            raise ValueError(f"inherit strips that refer to each other: {' -> '.join(map(self.where, cycle))}")
        if len(chain) >= INHERIT_LIMIT:
            raise ValueError(f"{self.where(chain[0])}: more than {INHERIT_LIMIT} inherit strips refer to one another")
        return (*chain, entry)

    def _target(self, entry: _Entry) -> _Entry | None:
        """
        The strip an `inherit` strip refers to (without `strip`: the one at its own place). None: an `auto` strip after
        the configured strips of a layout.
        """
        strip = self._strip(entry)
        place = entry[1]
        assert isinstance(strip, InheritStripConfig)
        where = self.where(entry)
        if strip.layout is not None and strip.layout not in self.names:
            raise ValueError(f"{where}: inherit from the layout {strip.layout}, which is not there")
        layout = self.names.index(strip.layout) if strip.layout is not None else 0
        name = f"the layout {strip.layout}" if layout else "the default layout"
        strips = self.layouts[layout].strips
        if strip.strip is None:
            if place < len(strips):
                return layout, place
            if place < protocol.STRIPS:
                return None
            raise ValueError(f"{where}: inherit, but {name} has only {max(len(strips), protocol.STRIPS)} strips")
        if isinstance(strip.strip, int):
            if strip.strip > len(strips):
                raise ValueError(f"{where}: inherit strip {strip.strip}, but {name} has {len(strips)} strips")
            return layout, strip.strip - 1
        found = [position for position, other in enumerate(strips) if getattr(other, "id", None) == strip.strip]
        if not found:
            raise ValueError(f"{where}: inherit strip {strip.strip}, but {name} has no strip with that id")
        if len(found) > 1:
            raise ValueError(f"{where}: inherit strip {strip.strip}, but {name} has {len(found)} strips with that id")
        return layout, found[0]

    def origin(self, entry: _Entry) -> _Entry | None:
        """The strip an `inherit` strip is in the end (itself for another one), None for an `auto` strip of none."""
        chain: tuple[_Entry, ...] = ()
        current: _Entry | None = entry
        while current is not None and isinstance(self._strip(current), InheritStripConfig):
            chain = self._enter(current, chain)
            current = self._target(current)
        return current

    def resolve(self, entry: _Entry, chain: tuple[_Entry, ...] = (), lands: int | None = None) -> StripConfig:
        """The strip of the entry, with the strips `inherit` ones refer to; `lands` is the place it lands on."""
        strip = self._strip(entry)
        _, position = entry
        if lands is None:
            lands = position
        if not isinstance(strip, InheritStripConfig):
            if isinstance(strip, _StripConfig | HomeAssistantStripConfig) and strip.id is None and lands != position:
                # on another place: its entities in Home Assistant are still those of its own place
                strip = strip.model_copy(update={"id": f"strip_{position + 1}"})
            return strip
        chain = self._enter(entry, chain)
        target = self._target(entry)
        if target is None:
            return AutoStripConfig(type="auto")
        return self.resolve(target, chain, lands)


def _one_or_more(value: object) -> object:
    """One name, or a list of them."""
    return (value,) if isinstance(value, str) else value


def _person_names(value: tuple[str, ...]) -> tuple[str, ...]:
    if any(not name.strip() for name in value):
        raise ValueError("an empty name")
    return value


class VoipStripConfig(_Model):
    """
    A participant of the voice chat, from the provider of `[voip]`: with `person` always the same one, else one of
    the group of the layout's `voip` strips without `person`.
    """

    type: Annotated[Literal["voip"], STRIP_TYPE_MEANINGS]
    person: Annotated[tuple[str, ...], BeforeValidator(_one_or_more), AfterValidator(_person_names)] = ()
    """
    The participant the strip always shows: their name in the voice chat, or several names of the same person (e.g.
    "Alice" and "alice-phone"), ignoring case. While they are not there, the strip shows the name dark. Without it,
    the strip is part of the group: the `voip` strips of the layout without `person`, which show the other
    participants, and Select on one of them the next ones.
    """
    label: Label | None = None
    """The top line of the LCD of a strip with `person`; by default the first name of `person`."""
    color: Annotated[ColorName, COLORS] = "white"
    """The backlight of the LCD while a participant is there and does not talk."""
    talking_color: Annotated[ColorName, COLORS] = "green"
    """The backlight while the participant talks."""
    meter: bool = True
    """Whether the LED meter shows the participant's voice (if the provider tells it and `behavior.meters` is on)."""
    max_volume: Annotated[int, Field(ge=1, le=VOLUME_LIMIT)] | None = None
    """
    The volume of a participant with the fader at the top, in percent; by default `behavior.max_volume`, so 100 % is
    at the 0 dB mark like on the other strips. Above 100 % the voice is louder than Mumble plays it, and may clip.
    """
    launch: Command | None = None
    """
    A command that Select starts while the voice chat is not there (no plugin reports it, and its program does not
    run), e.g. `["mumble", "mumble://me@voice.example.org/Gaming"]`. Never through a shell. The `voip` strips of a
    layout with the same command start it once.
    """
    collapse: bool = False
    """
    Whether the strip gives its fader to the strips after it while it shows nobody (see `behavior.collapse_hold`):
    a strip with `person` while the person is not there, one of the group while it has no participant.
    """

    @model_validator(mode="before")
    @classmethod
    def _no_count(cls, data: object) -> object:
        if isinstance(data, Mapping) and "count" in data:
            raise ValueError("count is gone: write N voip strips; voip strips without `person` form a group")
        return data

    @model_validator(mode="after")
    def _label_of_a_person(self) -> VoipStripConfig:
        if self.label is not None and not self.person:
            raise ValueError("label: only with person; a strip of the group shows the name of its participant")
        return self

    @property
    def title(self) -> str:
        """The top line of a strip with `person` (its label, else the first name), "" for one of the group."""
        return self.label or (self.person[0] if self.person else "")


StripConfig = Annotated[
    DeviceStripConfig
    | AppsStripConfig
    | AutoStripConfig
    | HomeAssistantStripConfig
    | EmptyStripConfig
    | InheritStripConfig
    | VoipStripConfig,
    Field(discriminator="type"),
]
STRIP_MODELS: tuple[type[BaseModel], ...] = get_args(get_args(StripConfig)[0])
"""The models of the strip types."""


class MqttConfig(_Model):
    """The MQTT broker Home Assistant uses, for `homeassistant` strips."""

    host: str
    """The host name or address of the broker, e.g. "homeassistant.local" for the Mosquitto add-on."""
    port: Annotated[int, Field(ge=1, le=65535)] = 1883
    """The port of the broker; 1883 is the usual one without TLS."""
    username: str | None = None
    """The user to log in as; without it the daemon connects without logging in."""
    password: SecretStr | None = None
    """The password itself; `password_file` or `password_env` keep it out of the configuration."""
    password_file: Path | None = None
    """A file that holds the password (`~` is the home directory); surrounding whitespace is ignored."""
    password_env: str | None = None
    """
    An environment variable that holds the password, e.g. set with `systemctl --user edit xtouch-daemon`
    (`Environment=`).
    """
    discovery_prefix: str = "homeassistant"
    """The MQTT discovery prefix of Home Assistant; change it only if Home Assistant has another one."""
    namespace: Slug = "xtouch"
    """
    Starts the entity IDs (`number.xtouch_strip_1_fader`) and is part of the topics. Lower case letters, digits,
    `_`.
    """
    device_name: str = "X-Touch Extender"
    """The name of the device in Home Assistant."""

    @model_validator(mode="after")
    def _one_password(self) -> MqttConfig:
        sources = [name for name in ("password", "password_file", "password_env") if getattr(self, name) is not None]
        if len(sources) > 1:
            raise ValueError(f"set only one of {', '.join(sources)}")
        return self

    def resolve_password(self) -> str | None:
        """The password from where it is configured."""
        if self.password is not None:
            return self.password.get_secret_value()
        if self.password_file is not None:
            try:
                return self.password_file.expanduser().read_text(encoding="utf-8").strip()
            except OSError as e:
                raise ConfigError(f"mqtt.password_file: can't read {self.password_file}: {e.strerror}") from e
        if self.password_env is not None:
            if self.password_env not in os.environ:
                raise ConfigError(f"mqtt.password_env: the environment variable {self.password_env} is not set")
            return os.environ[self.password_env]
        return None


DEFAULT_LAYOUT = "default"
"""The name of the layout of the top-level `[[strip]]` list."""

LayoutLabel = Annotated[str, Field(max_length=protocol.LCD_CELL_WIDTH * protocol.STRIPS, pattern=r"^[\x20-\x7e]*$")]
"""What fits on the top lines of all LCDs: 56 characters of ASCII."""


class LayoutConfig(_WithPresets):
    """A set of strips to switch to, e.g. for games: by hand, from Home Assistant, or when an application runs."""

    name: Slug
    """
    What Home Assistant and `xtouch-daemon layout` call it: lower case letters, digits and underscores, e.g.
    "gaming".
    """
    label: LayoutLabel = ""
    """What the LCDs show when the layout comes, across the strips; by default the name."""
    apps: StreamNames = ()
    """
    Switch to the layout while one of these applications has a stream (playing or paused): parts of the names or
    binaries, ignoring case, as `match` of `apps` strips, or presets, e.g. `@games`.
    """
    processes: ProcessNames = ()
    """
    Switch to the layout while a process of one of these names runs (parts of the name, ignoring case), e.g.
    "mumble" for the voice chat even while nobody talks, or presets, e.g. `@steam-games` while a game from Steam runs.
    """
    priority: int = 0
    """Of several layouts whose rules match, the one with the highest priority comes, then the first in the file."""
    strips: Annotated[tuple[StripConfig, ...], Field(alias="strip", max_length=MAX_STRIPS)] = ()
    """Up to 8 strips from the left (more with `collapse`), as the top-level ones; missing ones are `auto`."""

    @property
    def title(self) -> str:
        """The label, or else the name."""
        return self.label or self.name

    @property
    def has_rules(self) -> bool:
        return bool(self.apps or self.processes)


class SwitchingConfig(_Model):
    """How the daemon switches between layouts (`[[layout]]`)."""

    hold: Annotated[float, Field(ge=0)] = 10.0
    """
    Seconds a layout stays after its rule stopped matching (`apps`, `processes`), e.g. while a game loads the next
    level.
    """
    chord: tuple[FaderNumber, ...] = (1, 8)
    """
    The strips whose Solo buttons, held together, switch to the next layout, numbered from 1 on the left; none for no
    chord. Solo does nothing on audio strips, on `homeassistant` strips Home Assistant still gets the presses.
    """
    banner: Annotated[float, Field(ge=0, le=10)] = 1.5
    """Seconds the LCDs show the name of the layout that comes; 0 for none."""

    @field_validator("chord")
    @classmethod
    def _two_strips(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(value)) == 1:
            raise ValueError("at least two strips, or none")
        return value


VoipProviderName = Literal["demo", "bridge"]

VOIP_PROVIDERS = Meanings(
    {
        "demo": "Participants that are not there (`participants`), who talk in turns: to try `voip` strips without a "
        "voice chat.",
        "bridge": "A plugin in the voice chat client sends its participants to the daemon over a socket "
        "(`$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock`) and gets the volumes back.",
    }
)


class VoipConfig(_Model):
    """Where `voip` strips get the participants of the voice chat."""

    provider: Annotated[VoipProviderName, VOIP_PROVIDERS] = "bridge"
    """Who tells the participants."""
    participants: tuple[str, ...] = ("Alice", "Bob", "Carol", "Dave", "Eve")
    """The names of the participants of the `demo` provider."""


class Config(_Model):
    device: DeviceConfig = DeviceConfig()
    behavior: BehaviorConfig = BehaviorConfig()
    aliases: dict[str, Label] = {}
    """
    Names to show on `auto` strips for applications, at most 7 characters: for the name the sound server reports
    (`xtouch-daemon list-apps`), the label, e.g. "Discord" for "WEBRTC VoiceEngine".
    """
    strips: Annotated[tuple[StripConfig, ...], Field(alias="strip", max_length=MAX_STRIPS)] = ()
    """
    Up to 8 strips from the left; missing ones are `auto`. More with `collapse`: the device shows the first 8 that
    have something to control.
    """
    mqtt: MqttConfig | None = None
    """The MQTT broker, needed by `homeassistant` strips."""
    switching: SwitchingConfig = SwitchingConfig()
    voip: VoipConfig | None = None
    """The participants of the voice chat, for `voip` strips: without the section, they use its defaults (`bridge`)."""
    layouts: Annotated[tuple[LayoutConfig, ...], Field(alias="layout")] = ()
    """More sets of strips to switch to; the top-level strips are the layout `default`."""

    @model_validator(mode="after")
    def _layouts(self) -> Config:
        names = [layout.name for layout in self.layouts]
        if DEFAULT_LAYOUT in names:
            raise ValueError(f"layout: {DEFAULT_LAYOUT} is the name of the top-level strips")
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"layouts with the same name: {', '.join(duplicates)}")
        for number, strip in enumerate(self.strips, start=1):
            if isinstance(strip, InheritStripConfig) and strip.layout is None and strip.strip is None:
                raise ValueError(
                    f"strip[{number}]: inherit of the default layout is only for the strips of a [[layout]] (or "
                    "name a strip or a layout)"
                )
        inheritance = _Inheritance(self.layout_list())
        for index, layout in enumerate(self.layout_list()):
            strips = f"layout[{index}].strip" if index else "strip"
            for position in range(len(layout.strips)):
                inheritance.resolve((index, position))
            people = [
                name
                for strip in self.all_strips(layout.name)
                if isinstance(strip, VoipStripConfig)
                for name in {name.casefold() for name in strip.person}
            ]
            twice = sorted({name for name in people if people.count(name) > 1})
            if twice:
                where = "" if index == 0 else f" (layout {layout.name})"
                raise ValueError(f"voip strips with the same person{where}: {', '.join(twice)}")
            never = self.unreachable(layout.name)
            if never:
                numbers = ", ".join(f"{strips}[{number}]" for number in never)
                raise ValueError(
                    f"{numbers} can never show: {protocol.STRIPS} strips before them don't collapse "
                    "(`collapse = true` on some of them, or fewer strips)"
                )
        return self

    @model_validator(mode="after")
    def _volume_ranges(self) -> Config:
        for index, layout in enumerate(self.layout_list()):
            for number, strip in enumerate(layout.strips, start=1):
                if not isinstance(strip, _StripConfig):
                    continue
                for where, bottom, top in strip.volume_ranges(self.behavior):
                    if bottom >= top:
                        place = (f"layout[{index}]." if index else "") + f"strip[{number}]"
                        place += f".{where}" if where else ""
                        raise ValueError(f"{place}: min_volume ({bottom}) is not below max_volume ({top})")
        return self

    @model_validator(mode="after")
    def _home_assistant_strips(self) -> Config:
        for layout in self.layout_list():
            if self.home_assistant_strips(layout.name) and self.mqtt is None:
                raise ValueError("strips in Home Assistant need an [mqtt] section")
            ids = [strip_id for _, strip_id in self.entity_strips(layout.name)]
            duplicates = sorted({strip_id for strip_id in ids if ids.count(strip_id) > 1})
            if duplicates:
                where = "" if layout.name == DEFAULT_LAYOUT else f" (layout {layout.name})"
                raise ValueError(f"strips in Home Assistant with the same id{where}: {', '.join(duplicates)}")
        return self

    @model_validator(mode="after")
    def _voip_strips(self) -> Config:
        strips = (strip for layout in self.layout_list() for strip in layout.strips)
        if self.voip is None and any(isinstance(strip, VoipStripConfig) for strip in strips):
            # the section has defaults for everything: voip strips don't need it written out
            return self.model_copy(update={"voip": VoipConfig()})
        return self

    def layout_list(self) -> tuple[LayoutConfig, ...]:
        """Every layout, the default one (the top-level strips) first."""
        return (LayoutConfig.model_construct(name=DEFAULT_LAYOUT, label="Default", strips=self.strips), *self.layouts)

    @property
    def layout_names(self) -> tuple[str, ...]:
        return tuple(layout.name for layout in self.layout_list())

    def layout(self, name: str) -> LayoutConfig:
        """The layout of the name (KeyError for none)."""
        for layout in self.layout_list():
            if layout.name == name:
                return layout
        raise KeyError(name)

    def all_strips(self, layout: str = DEFAULT_LAYOUT) -> tuple[StripConfig, ...]:
        """
        The configuration of every strip of a layout, at least the 8 of the device: `inherit` ones are the strips
        they refer to, and the ones that are not configured are `auto`.
        """
        index = self.layout_names.index(self.layout(layout).name)
        inheritance = _Inheritance(self.layout_list())
        result = [inheritance.resolve((index, position)) for position in range(len(self.layout(layout).strips))]
        return (*result, *(AutoStripConfig(type="auto") for _ in range(protocol.STRIPS - len(result))))

    def inherited(self, layout: str = DEFAULT_LAYOUT) -> tuple[str | None, ...]:
        """
        For each strip of `all_strips()`, where it comes from if it is an `inherit` strip (e.g.
        "layout voice, strip 2"), None for the others.
        """
        index = self.layout_names.index(self.layout(layout).name)
        inheritance = _Inheritance(self.layout_list())
        result: list[str | None] = []
        for position, strip in enumerate(self.layout(layout).strips):
            where: str | None = None
            if isinstance(strip, InheritStripConfig):
                origin = inheritance.origin((index, position))
                name = self.layout_names[origin[0]] if origin is not None else strip.layout or DEFAULT_LAYOUT
                where = ("the default layout" if name == DEFAULT_LAYOUT else f"layout {name}") + (
                    f", strip {origin[1] + 1}" if origin is not None else ", an auto strip"
                )
            result.append(where)
        return (*result, *[None] * (len(self.all_strips(layout)) - len(result)))

    def unreachable(self, layout: str = DEFAULT_LAYOUT) -> list[int]:
        """
        The strips of the layout (their numbers in its list, from 1) that can never get a fader: 8 strips without
        `collapse` come before them.
        """
        steady = 0
        never: list[int] = []
        for number, strip in enumerate(self.all_strips(layout), start=1):
            if steady >= protocol.STRIPS:
                never.append(number)
            if not collapses(strip):
                steady += 1
        return never

    def entity_strips(self, layout: str = DEFAULT_LAYOUT) -> list[tuple[StripConfig, str]]:
        """
        The strips of a layout with entities in Home Assistant, with their ids: those of `home_assistant_strips()`,
        and with [mqtt] the ones with `choices` (a select of the choice).
        """
        return [
            (strip, strip.id or f"strip_{number}")
            for number, strip in enumerate(self.all_strips(layout), start=1)
            if isinstance(strip, HomeAssistantStripConfig)
            or (isinstance(strip, _StripConfig) and strip.uses_home_assistant)
            or (self.mqtt is not None and isinstance(strip, DeviceStripConfig) and strip.switches)
        ]

    def home_assistant_strips(self, layout: str = DEFAULT_LAYOUT) -> list[tuple[StripConfig, str]]:
        """
        The strips of a layout with entities in Home Assistant (`homeassistant` ones, and a fader or encoder), with
        their ids.
        """
        return [
            (strip, strip.id or f"strip_{number}")
            for number, strip in enumerate(self.all_strips(layout), start=1)
            if isinstance(strip, HomeAssistantStripConfig)
            or (isinstance(strip, _StripConfig) and strip.uses_home_assistant)
        ]


def collapses(strip: StripConfig) -> bool:
    """Whether the strip gives its place to the ones after it while it has nothing to control (`collapse`)."""
    return isinstance(strip, _StripConfig | VoipStripConfig) and strip.collapse


class ConfigError(Exception):
    """A configuration that can't be used, with a message for the user."""


STRIP_TYPES: tuple[str, ...] = tuple(
    name for model in STRIP_MODELS for name in get_args(model.model_fields["type"].annotation)
)
"""The values of `type` of a strip: output, input, apps, auto, homeassistant, empty, inherit, voip."""


@dataclass(frozen=True)
class Problem:
    """One error of a configuration: where it is, and what is wrong."""

    path: tuple[int | str, ...]
    """Where in the TOML data, e.g. `("strip", 2, "label")` for the label of the third strip."""
    message: str
    kind: str
    """The kind of error (pydantic's error type), e.g. `extra_forbidden` for an unknown option."""

    @property
    def location(self) -> str:
        """The path for people, e.g. `strip[3].label`."""
        parts: list[str] = []
        for part in self.path:
            if isinstance(part, int) and parts:
                parts[-1] = f"{parts[-1]}[{part + 1}]"
            else:
                parts.append(str(part))
        return ".".join(parts)

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


def problems_of(error: ValidationError) -> list[Problem]:
    problems: list[Problem] = []
    for item in error.errors():
        loc = item["loc"]
        # the type of a strip follows its position in the path of its errors (`strip.2.apps.label`), but is not part
        # of the TOML data
        path = tuple(
            part for i, part in enumerate(loc) if not (i and isinstance(loc[i - 1], int) and part in STRIP_TYPES)
        )
        # pydantic puts "Value error, " before the messages of the validators here
        problems.append(Problem(path, item["msg"].removeprefix("Value error, "), item["type"]))
    return problems


def parse_config(text: str, source: str = "config") -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{source} is not valid TOML: {e}") from e
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        problems = "\n".join(f"  {problem}" for problem in problems_of(e))
        raise ConfigError(f"{source} has errors:\n{problems}") from e


def load_config(path: Path | None = None) -> Config:
    """
    The configuration from the file. Without a file at the default path it is the example configuration (6 `auto`
    strips, the default input and the default output), so the daemon is useful right away.
    """
    explicit = path is not None
    path = path or default_config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if explicit:
            raise ConfigError(f"{path} does not exist") from None
        return parse_config(example_config(), "the example configuration")
    except OSError as e:
        raise ConfigError(f"can't read {path}: {e}") from e
    return parse_config(text, str(path))
