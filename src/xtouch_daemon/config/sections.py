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
    """Part of the name of the extender's sound card, as `/proc/asound/cards` lists it."""
    virtual: bool = False
    """
    Drive the virtual device instead (`xtouch-daemon virtual-device`, or the GUI's), for trying things without the
    device. `xtouch-daemon run --virtual-device` does the same for one run. Changes with a restart.
    """
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


class BehaviorConfig(WithPresets):
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
    meter_point: Annotated[MeterPoint, METER_POINTS] = "pre_fader"
    """
    Where the meters take the level: before the volume and Mute of the strip, or after them. A channel or a place
    may have its own (`meter_point`).
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


class SwitchingConfig(Model):
    """The chord, and the banner of a new mode."""

    chord: tuple[FaderNumber, ...] = (1, 8)
    """
    The strips whose Solo buttons, held together, do `chord_action` (by default: the next mode), numbered from 1 on the
    left; none for no chord. Solo does nothing on audio strips, on `homeassistant` strips Home Assistant still gets
    the presses.
    """
    banner: Annotated[float, Field(ge=0, le=10)] = 1.5
    """
    Seconds the LCDs show the label of a new mode, and a slot that shows something else its new label and why; 0 for
    none.
    """

    chord_action: str = "cycle_modes"
    """
    What the chord does, `cycle_modes`, `mode:<id>` or `toggle:<state or mode>`
    (checked with the slots). In the file: `chord = { strips = [1, 8], action = "toggle:call" }`.
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
    """Who tells the participants."""
    participants: tuple[str, ...] = ("Alice", "Bob", "Carol", "Dave", "Eve")
    """The names of the participants of the `demo` provider."""
