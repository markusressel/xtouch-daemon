"""
The options strips share: what they show (label, color), their buttons and knobs.
"""

from typing import Annotated

from pydantic import model_validator

from xtouch_daemon.config.base import Meanings, Model
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.values import (
    COLORS,
    ENCODER_MODES,
    ENCODERS,
    FADER_MODES,
    INDICATORS,
    METER_POINTS,
    ColorName,
    EncoderMode,
    FaderMode,
    Indicator,
    MeterPoint,
    Volume,
)


class BaseStripConfig(Model):
    color: Annotated[ColorName, COLORS] = "white"
    """The backlight of the LCD. It goes dark while the strip has nothing to control, unless `lit_when_idle` is on."""
    lit_when_idle: bool = False
    """
    Keeps the LCD lit while the strip has nothing to control, e.g. no application plays or the device is not there.
    The fader stays down.
    """
    meter: bool = True
    """The LED meter shows the level. Needs `behavior.meters`."""
    meter_point: Annotated[MeterPoint, METER_POINTS] | None = None
    """
    Where the meter takes the level: before the volume and Mute of the strip, or after them. By default
    `behavior.meter_point`.
    """
    rec: Annotated[Indicator, INDICATORS] = "recording"
    """What the LED of the Rec button shows. The button does nothing, except with `profiles`."""
    solo: Annotated[Indicator, INDICATORS] = "off"
    """What the LED of the Solo button shows. The button does nothing."""
    min_volume: Volume | None = None
    """The volume, in percent, with the fader at the bottom. E.g. 50 gives the whole fader to the upper half."""
    max_volume: Volume | None = None
    """
    The volume, in percent, with the fader at the top; by default `behavior.max_volume`. Above 100 % the audio is
    amplified, e.g. 200 for weak speakers.
    """
    encoder: Annotated[EncoderMode, ENCODER_MODES] | None = None
    """What the encoder does when you turn and push it. Its LED ring shows the value."""
    fader: Annotated[FaderMode, FADER_MODES] = "volume"
    """What the fader sets."""

    @property
    def uses_home_assistant(self) -> bool:
        return "homeassistant" in (self.fader, self.encoder)

    @model_validator(mode="after")
    def _encoder_of_the_type(self) -> BaseStripConfig:
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


STRIP_TYPE_MEANINGS = Meanings(
    {
        "output": "An output device (speakers, headphones): the fader sets its volume. One device, one of several, or "
        "whatever is the default output.",
        "input": "An input device (a microphone): the fader sets its volume. One device, one of several, or whatever "
        "is the default input.",
        "apps": "All playback streams of a group of applications, e.g. every browser, like the per-application "
        "sliders of pavucontrol.",
        "auto": "The next application that plays and has no channel of its own, and the people of the voice chat.",
        "homeassistant": "A strip for Home Assistant: its fader, encoder, LCD, LEDs and buttons are entities there, "
        "and automations decide what they do. Needs `[mqtt]`.",
        "empty": "A dark strip that does nothing; its fader stays at the bottom.",
        "voip": "A participant of the voice chat: the fader sets their volume, Mute mutes them for you, the meter "
        "shows their voice. With `person` always the same one, else one of the people `auto` hands out.",
    }
)
"""What each strip type is, shown when it is chosen."""
