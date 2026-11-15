"""
The configuration: a TOML file, by default `$XDG_CONFIG_HOME/xtouch-daemon/config.toml`. See `config.example.toml`
(also written by `xtouch-daemon init-config`) for every option.
"""

import os
import tomllib
from importlib import resources
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from xtouch_daemon import protocol
from xtouch_daemon.protocol import Color

APP_NAME = "xtouch-daemon"


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME / "config.toml"


def example_config() -> str:
    return resources.files("xtouch_daemon").joinpath("config.example.toml").read_text(encoding="utf-8")


class _Model(BaseModel):
    # a typo in an option name is an error, not silently ignored
    model_config = ConfigDict(extra="forbid", frozen=True)


ColorName = Literal["off", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]


def color_of(name: ColorName) -> Color:
    return Color.BLACK if name == "off" else Color[name.upper()]


Label = Annotated[str, Field(max_length=protocol.LCD_CELL_WIDTH, pattern=r"^[\x20-\x7e]*$")]
"""What fits on the LCD: 7 characters of ASCII."""


class DeviceConfig(_Model):
    name: str = "X-Touch-Ext"
    """Part of the name of the sound card of the extender (see /proc/asound/cards)."""


class BehaviorConfig(_Model):
    max_volume: Annotated[int, Field(ge=100, le=150)] = 100
    """The volume of a fader at the top, in percent: above 100 % the audio is amplified in software."""
    encoder_step: Annotated[int, Field(ge=1, le=10)] = 1
    """Percent per step of an encoder."""
    reset_volume: Annotated[int, Field(ge=0, le=150)] = 100
    """The volume a push on an encoder sets."""
    meters: bool = True
    """Whether the LED meters show audio levels."""
    auto_hold: Annotated[float, Field(ge=0)] = 5.0
    """Seconds an `auto` strip keeps an application after it stopped playing (so it does not jump between tracks)."""
    ignore: tuple[str, ...] = ("speech-dispatcher",)
    """Applications that `auto` strips never take (part of the name or binary, ignoring case)."""

    @model_validator(mode="after")
    def _reset_within_reach(self) -> "BehaviorConfig":
        if self.reset_volume > self.max_volume:
            raise ValueError(f"reset_volume ({self.reset_volume}) is above max_volume ({self.max_volume})")
        return self


class _StripConfig(_Model):
    color: ColorName = "white"
    meter: bool = True
    """Whether this strip's LED meter shows the level (if `behavior.meters` is on)."""


class DeviceStripConfig(_StripConfig):
    type: Literal["output", "input"]
    device: str | None = None
    """The node name (`xtouch-daemon list-devices`) or description of the device; without it the default device."""
    label: Label | None = None
    """The top line of the LCD; by default "Output" or "Input", or the start of the device's description."""
    select: bool = True
    """Whether the select button makes the device the default (needs `device`)."""


class AppsStripConfig(_StripConfig):
    type: Literal["apps"]
    match: Annotated[tuple[str, ...], Field(min_length=1)]
    """Parts of the names or binaries of the applications (ignoring case), see `xtouch-daemon list-apps`."""
    label: Label

    @field_validator("match")
    @classmethod
    def _not_blank(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not pattern.strip() for pattern in value):
            raise ValueError("an empty pattern would match every application")
        return value


class AutoStripConfig(_StripConfig):
    type: Literal["auto"]


class EmptyStripConfig(_Model):
    type: Literal["empty"]


StripConfig = Annotated[
    DeviceStripConfig | AppsStripConfig | AutoStripConfig | EmptyStripConfig, Field(discriminator="type")
]


class Config(_Model):
    device: DeviceConfig = DeviceConfig()
    behavior: BehaviorConfig = BehaviorConfig()
    aliases: dict[str, Label] = {}
    """Names to show for applications on `auto` strips: {"name the sound server reports": "label"}."""
    strips: Annotated[tuple[StripConfig, ...], Field(alias="strip", max_length=protocol.STRIPS)] = ()
    """Up to 8 strips from the left; missing ones are `auto`."""

    def all_strips(self) -> tuple[StripConfig, ...]:
        """The configuration of every strip of the device, the ones that are not configured `auto`."""
        return self.strips + tuple(AutoStripConfig(type="auto") for _ in range(protocol.STRIPS - len(self.strips)))


class ConfigError(Exception):
    """A configuration that can't be used, with a message for the user."""


def _location(loc: tuple[int | str, ...]) -> str:
    parts: list[str] = []
    for part in loc:
        if isinstance(part, int) and parts:
            parts[-1] = f"{parts[-1]}[{part + 1}]"
        elif part not in ("output", "input", "apps", "auto", "empty"):
            parts.append(str(part))
    return ".".join(parts)


def _message(message: str) -> str:
    # pydantic puts "Value error, " before the messages of the validators here
    return message.removeprefix("Value error, ")


def parse_config(text: str, source: str = "config") -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{source} is not valid TOML: {e}") from e
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        problems = "\n".join(f"  {_location(error['loc'])}: {_message(error['msg'])}" for error in e.errors())
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
