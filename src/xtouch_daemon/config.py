"""
The configuration: a TOML file, by default `$XDG_CONFIG_HOME/xtouch-daemon/config.toml`. See `config.example.toml`
(also written by `xtouch-daemon init-config`) for every option.
"""

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator

from xtouch_daemon import protocol
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


ColorName = Literal["off", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]


Indicator = Literal["off", "recording", "playing", "default", "muted"]
"""
What a button LED shows: `recording`: an application records the device (an input, or the monitor of an output) or
records at all (applications); `playing`: audio flows; `default`: the device is the default; `muted`: muted.
"""


EncoderMode = Literal["volume", "balance", "pick", "media", "homeassistant"]
"""
What the encoder of a strip does: `volume`: fine steps, a push resets it; `balance`: left/right, a push centers it;
`pick` (`auto` strips): which application the strip has, a push pins it; `media` (applications): seeks in the track
of their media player, a push plays or pauses; `homeassistant`: a number entity in Home Assistant, e.g. for the
brightness of a light.
"""

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


class DeviceConfig(_Model):
    """The device the daemon drives."""

    name: str = "X-Touch-Ext"
    """Part of the name of the sound card of the extender (see /proc/asound/cards)."""
    touch_required: bool = True
    """
    Whether a fader changes a value only while the device reports a touch. Off, every move counts, as on
    `touchless_faders`: e.g. pushing a fader from below with a fingertip, which the touch sensor does not notice.
    """
    touchless_faders: tuple[FaderNumber, ...] = ()
    """
    Faders whose touch sensor does not work, numbered from 1 on the left: a move counts as a touch, a short pause in
    the moves as letting go.
    """
    startup: Sequence = "sweep"
    """
    How the strips light up after a connect: `instant` all at once, `sweep` one after the other from the left,
    `curtain` from the middle outwards, `show` behind a wave of light from the left.
    """
    shutdown: Sequence = "sweep"
    """
    How the strips go dark when the daemon stops: `instant` all at once, `sweep` one after the other from the right,
    `curtain` from the outside in, `show` with a flash of light from the right.
    """


class BehaviorConfig(_Model):
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
    """Percent per step of an encoder."""
    reset_volume: Volume = 100
    """The volume a push on an encoder sets (within the range of the strip)."""
    meters: bool = True
    """Whether the LED meters show audio levels."""
    auto_hold: Annotated[float, Field(ge=0)] = 5.0
    """Seconds an `auto` strip keeps an application after it stopped playing (so it does not jump between tracks)."""
    ignore: tuple[str, ...] = ("speech-dispatcher",)
    """Applications that `auto` strips never take (part of the name or binary, ignoring case)."""

    @model_validator(mode="after")
    def _reset_within_reach(self) -> BehaviorConfig:
        if self.reset_volume > self.max_volume:
            raise ValueError(f"reset_volume ({self.reset_volume}) is above max_volume ({self.max_volume})")
        return self


Slug = Annotated[str, Field(pattern=r"^[a-z0-9_]+$", max_length=64)]
"""Part of entity IDs and MQTT topics: lower case letters, digits and underscores."""


class _StripConfig(_Model):
    color: ColorName = "white"
    """The backlight of the LCD."""
    meter: bool = True
    """Whether this strip's LED meter shows the level (if `behavior.meters` is on)."""
    rec: Indicator = "recording"
    """What the LED of the rec button shows."""
    solo: Indicator = "off"
    """What the LED of the solo button shows."""
    min_volume: Volume | None = None
    """The volume of the fader at the bottom, in percent; by default 0."""
    max_volume: Volume | None = None
    """The volume of the fader at the top, in percent; by default `behavior.max_volume`."""
    encoder: EncoderMode | None = None
    """What the encoder does; by default `balance` for devices, `media` for `apps`, `pick` for `auto` strips."""
    fader: Literal["volume", "homeassistant"] = "volume"
    """What the fader sets: the volume, or a number entity in Home Assistant (then the encoder sets the volume)."""
    id: Slug | None = None
    """
    With `fader` or `encoder` in Home Assistant: part of the entity IDs; by default `strip_<position>`, so set it to
    keep the entities when moving the strip.
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


class DeviceStripConfig(_StripConfig):
    """An output or an input device, or whatever is the default one."""

    type: Literal["output", "input"]
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
    """Whether the select button makes the device the default (needs `device`)."""
    profiles: tuple[ProfileConfig, ...] = ()
    """
    Profiles of the device's sound card to switch between with the rec button, e.g. analog and digital output. Its
    LED is on for every profile but the first. Name `device` so that it matches the devices of every profile (e.g.
    `alsa_output.pci-0000_11_00.4.*`): each profile has a device of its own.
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

    @field_validator("profiles")
    @classmethod
    def _two_profiles(cls, value: tuple[ProfileConfig, ...]) -> tuple[ProfileConfig, ...]:
        if len(value) == 1:
            raise ValueError("at least two to switch between")
        return value

    def volume_ranges(self, behavior: BehaviorConfig) -> list[tuple[str, int, int]]:
        ranges = super().volume_ranges(behavior)
        _, bottom, top = ranges[0]
        for number, profile in enumerate(self.profiles, start=1):
            ranges.append(
                (
                    f"profiles[{number}]",
                    bottom if profile.min_volume is None else profile.min_volume,
                    top if profile.max_volume is None else profile.max_volume,
                )
            )
        return ranges

    @model_validator(mode="after")
    def _profiles_take_rec(self) -> DeviceStripConfig:
        if self.profiles and "rec" in self.model_fields_set:
            raise ValueError("rec: with profiles its LED shows the profile")
        return self


class AppsStripConfig(_StripConfig):
    """All streams of a group of applications, e.g. every browser."""

    type: Literal["apps"]
    match: Annotated[tuple[str, ...], Field(min_length=1)]
    """Parts of the names or binaries of the applications (ignoring case), see `xtouch-daemon list-apps`."""
    label: Label
    """The top line of the LCD."""

    @field_validator("match")
    @classmethod
    def _not_blank(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not pattern.strip() for pattern in value):
            raise ValueError("an empty pattern would match every application")
        return value


class AutoStripConfig(_StripConfig):
    """The next application that plays and has no strip of its own."""

    type: Literal["auto"]


class EmptyStripConfig(_Model):
    """A dark strip that does nothing."""

    type: Literal["empty"]


class HomeAssistantStripConfig(_Model):
    """A strip that belongs to Home Assistant: its parts are entities there, automations decide what they do."""

    type: Literal["homeassistant"]
    id: Slug | None = None
    """Part of the entity IDs; by default `strip_<position>`, so set it to keep the entities when moving the strip."""
    label: Label | None = None
    """The top line of the LCD until Home Assistant sets one; also the start of the entity names."""
    color: ColorName = "white"
    """The LCD backlight until Home Assistant sets one."""


StripConfig = Annotated[
    DeviceStripConfig | AppsStripConfig | AutoStripConfig | HomeAssistantStripConfig | EmptyStripConfig,
    Field(discriminator="type"),
]
STRIP_MODELS: tuple[type[BaseModel], ...] = get_args(get_args(StripConfig)[0])
"""The models of the strip types."""


class MqttConfig(_Model):
    """The MQTT broker Home Assistant uses, for `homeassistant` strips."""

    host: str
    port: Annotated[int, Field(ge=1, le=65535)] = 1883
    username: str | None = None
    password: SecretStr | None = None
    """The password itself; `password_file` or `password_env` keep it out of the configuration."""
    password_file: Path | None = None
    """A file that holds the password (`~` is the home directory); surrounding whitespace is ignored."""
    password_env: str | None = None
    """An environment variable that holds the password."""
    discovery_prefix: str = "homeassistant"
    """The MQTT discovery prefix of Home Assistant."""
    namespace: Slug = "xtouch"
    """Starts the entity IDs (`number.xtouch_strip_1_fader`) and is part of the topics."""
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


class Config(_Model):
    device: DeviceConfig = DeviceConfig()
    behavior: BehaviorConfig = BehaviorConfig()
    aliases: dict[str, Label] = {}
    """Names to show for applications on `auto` strips: {"name the sound server reports": "label"}."""
    strips: Annotated[tuple[StripConfig, ...], Field(alias="strip", max_length=protocol.STRIPS)] = ()
    """Up to 8 strips from the left; missing ones are `auto`."""
    mqtt: MqttConfig | None = None
    """The MQTT broker, needed by `homeassistant` strips."""

    @model_validator(mode="after")
    def _volume_ranges(self) -> Config:
        for number, strip in enumerate(self.strips, start=1):
            if not isinstance(strip, _StripConfig):
                continue
            for where, bottom, top in strip.volume_ranges(self.behavior):
                if bottom >= top:
                    place = f"strip[{number}]" + (f".{where}" if where else "")
                    raise ValueError(f"{place}: min_volume ({bottom}) is not below max_volume ({top})")
        return self

    @model_validator(mode="after")
    def _home_assistant_strips(self) -> Config:
        ids = [strip_id for _, strip_id in self.home_assistant_strips()]
        if ids and self.mqtt is None:
            raise ValueError("strips in Home Assistant need an [mqtt] section")
        duplicates = sorted({strip_id for strip_id in ids if ids.count(strip_id) > 1})
        if duplicates:
            raise ValueError(f"strips in Home Assistant with the same id: {', '.join(duplicates)}")
        return self

    def all_strips(self) -> tuple[StripConfig, ...]:
        """The configuration of every strip of the device, the ones that are not configured `auto`."""
        return self.strips + tuple(AutoStripConfig(type="auto") for _ in range(protocol.STRIPS - len(self.strips)))

    def home_assistant_strips(self) -> list[tuple[StripConfig, str]]:
        """The strips with entities in Home Assistant (`homeassistant` ones, and a fader or encoder), with their ids."""
        return [
            (strip, strip.id or f"strip_{number}")
            for number, strip in enumerate(self.strips, start=1)
            if isinstance(strip, HomeAssistantStripConfig)
            or (isinstance(strip, _StripConfig) and strip.uses_home_assistant)
        ]


class ConfigError(Exception):
    """A configuration that can't be used, with a message for the user."""


STRIP_TYPES: tuple[str, ...] = tuple(
    name for model in STRIP_MODELS for name in get_args(model.model_fields["type"].annotation)
)
"""The values of `type` of a strip: output, input, apps, auto, empty."""


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
