"""
The sections of the configuration besides the channels, states and slots: `[device]`, `[behavior]`, `[mqtt]`,
`[switching]` and `[voip]`.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from xtouch_daemon.config.base import ConfigError, Meanings, Model
from xtouch_daemon.config.names import WithPresets
from xtouch_daemon.config.values import (
    METER_POINTS,
    SHUTDOWN_SEQUENCES,
    STARTUP_SEQUENCES,
    VOLUME_LIMIT,
    FaderNumber,
    MeterPoint,
    Sequence,
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
    GUI's). Takes effect after a restart.
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
    shutdown: Annotated[Sequence, SHUTDOWN_SEQUENCES] = "sweep"
    """How the strips go dark when the daemon stops."""


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
