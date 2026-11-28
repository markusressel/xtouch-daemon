"""
The sections of the configuration besides the channels, states and slots: `[device]`, `[behavior]`, `[mqtt]`,
`[homeassistant]`, `[switching]` and `[voip]`.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from xtouch_daemon.config.base import ConfigError, Meanings, Model, ShownWith
from xtouch_daemon.config.names import WithPresets
from xtouch_daemon.config.permissions import warn_if_readable
from xtouch_daemon.config.values import (
    INSTANT,
    METER_POINTS,
    SHUTDOWN_SEQUENCES,
    STARTUP_SEQUENCES,
    VOLUME_LIMIT,
    FaderNumber,
    MeterPoint,
    Pace,
    Percent,
    Sequence,
    SequenceDelay,
    ShowStep,
    Slug,
    Volume,
)


class DeviceConfig(Model):
    """The device the daemon drives."""

    name: str = "X-Touch-Ext"
    """A part of the name of the sound card of the extender, as `/proc/asound/cards` lists it."""
    virtual: bool = False
    """
    Drives the virtual device instead, to try things without the device (`xtouch-daemon virtual-device`, or the
    GUI's). A reload switches to it, or back to the device.
    """
    touch_required: bool = True
    """
    A fader changes its value only while you touch it, so a fader the motor moves changes nothing. Off, every move
    counts, e.g. a fader pushed with a fingertip the sensor does not notice.
    """
    touchless_faders: tuple[FaderNumber, ...] = ()
    """
    Faders whose touch sensor is broken, numbered from 1 on the left. A move counts as a touch, half a second
    without a move as letting go.
    """
    startup: Annotated[Sequence, STARTUP_SEQUENCES] = "sweep"
    """How the strips light up after the device connects."""
    startup_sweep_delay: Annotated[SequenceDelay, ShownWith("startup", "sweep")] = 80
    """Milliseconds from one strip to the next."""
    startup_curtain_delay: Annotated[SequenceDelay, ShownWith("startup", "curtain")] = 80
    """Milliseconds from one pair of strips to the next."""
    startup_show_delay: Annotated[SequenceDelay, ShownWith("startup", "show")] = 60
    """Milliseconds from one strip to the next: the speed of the wave."""
    startup_show_step: Annotated[ShowStep, ShownWith("startup", "show")] = 30
    """
    Milliseconds per step of the light of a strip: its ring lights one more LED, its meter one more level. Its light
    takes 24 steps, 12 up and 12 down.
    """
    startup_show_fader: Annotated[Percent, ShownWith("startup", "show")] = 60
    """The height, in percent, that the faders rise to in the wave."""
    shutdown: Annotated[Sequence, SHUTDOWN_SEQUENCES] = "sweep"
    """How the strips go dark when the daemon stops."""
    shutdown_sweep_delay: Annotated[SequenceDelay, ShownWith("shutdown", "sweep")] = 80
    """Milliseconds from one strip to the next."""
    shutdown_curtain_delay: Annotated[SequenceDelay, ShownWith("shutdown", "curtain")] = 80
    """Milliseconds from one pair of strips to the next."""
    shutdown_show_delay: Annotated[SequenceDelay, ShownWith("shutdown", "show")] = 60
    """Milliseconds from one strip to the next: the speed of the wave."""
    shutdown_show_step: Annotated[ShowStep, ShownWith("shutdown", "show")] = 30
    """
    Milliseconds per step of the light of a strip: its ring lights one more LED, its meter one more level. Its light
    takes 24 steps, 12 up and 12 down.
    """
    shutdown_show_fader: Annotated[Percent, ShownWith("shutdown", "show")] = 60
    """The height, in percent, that the faders rise to in the wave."""

    def pace(self, startup: bool) -> Pace:
        """The startup sequence (`startup`) or the shutdown sequence, with the options of its type."""
        direction = "startup" if startup else "shutdown"
        sequence: Sequence = getattr(self, direction)

        def value(name: str, default: Pace) -> float:
            return getattr(self, f"{direction}_{sequence}_{name}", getattr(default, name))

        return Pace(
            sequence, value("delay", INSTANT) / 1000, value("step", INSTANT) / 1000, value("fader", INSTANT) / 100
        )


class BehaviorConfig(WithPresets):
    """How the faders, encoders, meters and `auto` strips behave."""

    max_volume: Annotated[int, Field(ge=100, le=VOLUME_LIMIT)] = 130
    """
    The volume, in percent, with a fader at the top. Above 100 % the audio is amplified. With 130, 100 % is at the 0
    dB mark of the device and the fader is linear (see `unity_at`).
    """
    unity_at: Annotated[int, Field(ge=10, le=95)] = 77
    """
    Where 100 % is on the fader, in percent of its travel from the bottom; the device marks 0 dB at about 77. Above
    the mark the fader goes on to `max_volume`. A strip whose range ends at 100 % stays linear.
    """
    encoder_step: Annotated[int, Field(ge=1, le=10)] = 1
    """Percent per step of an encoder: of the volume (`volume`), or of the number (`homeassistant`)."""
    reset_volume: Volume = 100
    """The volume a push on a `volume` encoder sets, within the range of the strip."""
    meters: bool = True
    """The LED meters show the level. Off, every meter stays dark; `meter` turns off a single one."""
    meter_point: Annotated[MeterPoint, METER_POINTS] = "pre_fader"
    """
    Where the meters take the level: before the volume and Mute of the strip, or after them. A channel or a place
    may have its own `meter_point`.
    """

    @model_validator(mode="after")
    def _reset_within_reach(self) -> BehaviorConfig:
        if self.reset_volume > self.max_volume:
            raise ValueError(f"reset_volume ({self.reset_volume}) is above max_volume ({self.max_volume})")
        return self


class MqttConfig(Model):
    """The MQTT broker Home Assistant uses, for `homeassistant` strips."""

    host: str
    """The host name or address of the broker, e.g. "homeassistant.local" for the Mosquitto add-on."""
    port: Annotated[int, Field(ge=1, le=65535)] = 1883
    """The port of the broker. 1883 is the usual one without TLS."""
    username: str | None = None
    """The user to log in as. Without it, the daemon connects without logging in."""
    password: SecretStr | None = None
    """The password. `password_file` or `password_env` keep it out of the configuration."""
    password_file: Path | None = None
    """A file with the password (`~` is your home directory). Whitespace around it is ignored."""
    password_env: str | None = None
    """
    An environment variable with the password, e.g. set with `systemctl --user edit xtouch-daemon` (`Environment=`).
    """
    discovery_prefix: str = "homeassistant"
    """The MQTT discovery prefix of Home Assistant. Change it only if Home Assistant uses another one."""
    namespace: Slug = "xtouch"
    """
    The start of the entity IDs (`number.xtouch_strip_1_fader`) and the topics: lower case letters, digits and `_`.
    """
    device_name: str = "X-Touch Extender"
    """The name of the device in Home Assistant."""

    @model_validator(mode="after")
    def _one_password(self) -> MqttConfig:
        _one_of(self, "password")
        return self

    def resolve_password(self) -> str | None:
        """The password from where it is configured."""
        return _resolve_secret(self, "mqtt", "password")


def _one_of(section: BaseModel, name: str) -> list[str]:
    """The options that set the secret `name` (`name`, `name_file`, `name_env`); ValueError for more than one."""
    sources = [option for option in (name, f"{name}_file", f"{name}_env") if getattr(section, option) is not None]
    if len(sources) > 1:
        raise ValueError(f"set only one of {', '.join(sources)}")
    return sources


def _resolve_secret(section: BaseModel, where: str, name: str) -> str | None:
    """
    A secret from where the section configures it: the option itself, a file (`<name>_file`), or an environment
    variable (`<name>_env`); None without any. ConfigError for a file that can't be read or a variable that is not set.
    """
    value: SecretStr | None = getattr(section, name)
    path: Path | None = getattr(section, f"{name}_file")
    variable: str | None = getattr(section, f"{name}_env")
    if value is not None:
        return value.get_secret_value()
    if path is not None:
        warn_if_readable(path.expanduser(), f"{where}.{name}_file")
        try:
            return path.expanduser().read_text(encoding="utf-8").strip()
        except OSError as e:
            raise ConfigError(f"{where}.{name}_file: can't read {path}: {e.strerror}") from e
    if variable is not None:
        if variable not in os.environ:
            raise ConfigError(f"{where}.{name}_env: the environment variable {variable} is not set")
        return os.environ[variable]
    return None


WEBSOCKET_PATH = "/api/websocket"
"""Where Home Assistant serves its WebSocket API, below its address."""
_SCHEMES = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}


class HomeAssistantConfig(Model):
    """The API of Home Assistant, for parts that show or set an entity, e.g. `meter = { entity = "sensor.cpu" }`."""

    url: str
    """The address of Home Assistant, as in the browser. E.g. `http://homeassistant.local:8123`."""
    token: SecretStr | None = None
    """
    A long-lived access token: create one in your profile in Home Assistant, on the Security tab. `token_file` or
    `token_env` keep it out of the configuration.
    """
    token_file: Path | None = None
    """A file with the token (`~` is your home directory). Whitespace around it is ignored."""
    token_env: str | None = None
    """
    An environment variable with the token, e.g. set with `systemctl --user edit xtouch-daemon` (`Environment=`). The
    GUI reads its own environment: start it with the variable set too.
    """

    @field_validator("url")
    @classmethod
    def _an_address(cls, value: str) -> str:
        scheme, separator, rest = value.strip().partition("://")
        if not separator or scheme.lower() not in _SCHEMES or not rest.strip("/"):
            raise ValueError(f"{value} is no address of Home Assistant, e.g. http://homeassistant.local:8123")
        return f"{scheme.lower()}://{rest.rstrip('/')}"

    @model_validator(mode="after")
    def _one_token(self) -> HomeAssistantConfig:
        if not _one_of(self, "token"):
            raise ValueError("needs token, token_file or token_env: a long-lived access token of Home Assistant")
        return self

    @property
    def websocket_url(self) -> str:
        """The address of the WebSocket API: `ws://` (`wss://` for `https://`), `/api/websocket` below `url`."""
        scheme, _, rest = self.url.partition("://")
        rest = rest.removesuffix(WEBSOCKET_PATH)
        return f"{_SCHEMES[scheme]}://{rest}{WEBSOCKET_PATH}"

    def resolve_token(self) -> str:
        """The token from where it is configured."""
        token = _resolve_secret(self, "homeassistant", "token")
        assert token is not None, "the section needs a token (checked when the file is loaded)"
        return token


class SwitchingConfig(Model):
    """The chord, and the banner of a new mode."""

    chord: tuple[FaderNumber, ...] = (1, 8)
    """
    The strips whose Solo buttons, held together, do `chord_action`, numbered from 1 on the left; none for no chord.
    Home Assistant still gets the presses of its strips.
    """
    banner: Annotated[float, Field(ge=0, le=10)] = 1.5
    """
    Seconds the LCDs show the label of a new mode, and a slot that shows something else its new label and why. 0 for
    none.
    """

    chord_action: str = "cycle_modes"
    """
    What the chord does: `cycle_modes` (the next mode), `mode:<id>` or `toggle:<state or mode>`. In the file: `chord
    = { strips = [1, 8], action = "toggle:call" }`.
    """

    @model_validator(mode="before")
    @classmethod
    def _chord_table(cls, data: Any) -> Any:
        """`chord = { strips = [...], action = ... }`: the strips and the action."""
        if isinstance(data, Mapping) and isinstance(chord := data.get("chord"), Mapping):
            unknown = set(chord) - {"strips", "action"}
            if unknown:
                raise ValueError(f"chord: {', '.join(sorted(unknown))}: only strips and action")
            data = {**data, "chord": chord.get("strips", (1, 8))}
            if "action" in chord:
                data["chord_action"] = chord["action"]
        return data

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


class VoipConfig(Model):
    """Where `voip` strips get the participants of the voice chat."""

    provider: Annotated[VoipProviderName, VOIP_PROVIDERS] = "bridge"
    """Who tells the daemon the participants of the voice chat."""
    participants: tuple[str, ...] = ("Alice", "Bob", "Carol", "Dave", "Eve")
    """The names of the participants of the `demo` provider."""
