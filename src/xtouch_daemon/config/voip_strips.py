"""
The strips of the voice chat (`voip`): the participants of a voice chat.
"""

from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, Field

from xtouch_daemon.config.base import Model
from xtouch_daemon.config.strip import STRIP_TYPE_MEANINGS
from xtouch_daemon.config.values import (
    COLORS,
    METER_POINTS,
    MUTE_LEDS,
    VOLUME_LIMIT,
    ColorName,
    Label,
    MeterPoint,
    MuteLed,
)


def _one_or_more(value: object) -> object:
    """One name, or a list of them."""
    return (value,) if isinstance(value, str) else value


def _person_names(value: tuple[str, ...]) -> tuple[str, ...]:
    if any(not name.strip() for name in value):
        raise ValueError("an empty name")
    return value


class VoipStripConfig(Model):
    """
    A participant of the voice chat, from the provider of `[voip]`: with `person` always the same one (a `person`
    channel), else whoever of the people of `auto` it shows (the look of `[people]`).
    """

    type: Annotated[Literal["voip"], STRIP_TYPE_MEANINGS]
    person: Annotated[
        tuple[str, ...],
        BeforeValidator(_one_or_more, json_schema_input_type=str | list[str]),
        AfterValidator(_person_names),
    ] = ()
    """
    The participant the strip always shows: their name in the voice chat (any case), or several names of the same
    person, e.g. "Alice" and "alice-phone". While they are away, the name shows dark.
    """
    label: Label | None = None
    """The top line of the LCD of a strip with `person`; by default the first name of `person`."""
    color: Annotated[ColorName, COLORS] = "white"
    """The backlight of the LCD while the participant is there and quiet."""
    talking_color: Annotated[ColorName, COLORS] = "green"
    """The backlight of the LCD while the participant talks."""
    meter: bool = True
    """The LED meter shows the voice of the participant, if the voice chat tells it. Needs `behavior.meters`."""
    meter_point: Annotated[MeterPoint, METER_POINTS] | None = None
    """
    Where the meter takes the voice: before the fader and Mute, or after them. Before, a muted participant who talks
    lights it without a level. By default `behavior.meter_point`.
    """
    mute_led: Annotated[MuteLed, MUTE_LEDS] = "on"
    """The LED of Mute while the participant is muted for you: lit, or flashing."""
    max_volume: Annotated[int, Field(ge=1, le=VOLUME_LIMIT)] | None = None
    """
    The volume of the participant, in percent, with the fader at the top; by default `behavior.max_volume`. Above
    100 % they are louder than Mumble plays them, and may clip.
    """

    @property
    def title(self) -> str:
        """The top line of a strip with `person` (its label, else the first name), "" for the people of `auto`."""
        return self.label or (self.person[0] if self.person else "")
