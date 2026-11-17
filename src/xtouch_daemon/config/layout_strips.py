"""
The strips of the voice chat (`voip`): the participants of a voice chat.
"""

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, Field, model_validator

from xtouch_daemon.config.base import Model
from xtouch_daemon.config.strip import STRIP_TYPE_MEANINGS
from xtouch_daemon.config.values import (
    COLORS,
    METER_POINTS,
    VOLUME_LIMIT,
    ColorName,
    Command,
    Label,
    MeterPoint,
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
    meter_point: Annotated[MeterPoint, METER_POINTS] | None = None
    """
    Where the meter takes the voice: before the fader and Mute (a muted participant who talks lights it, without a
    level: Mumble doesn't fetch their voice), or after them; by default the `meter_point` of the layout, else
    `behavior.meter_point`.
    """
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
    def _refused(cls, data: object) -> object:
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
