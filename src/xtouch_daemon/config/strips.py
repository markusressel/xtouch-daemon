"""
Every strip type (`StripConfig`), and the strips that control nothing of the sound (`empty`, `homeassistant`).
"""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, Field, model_validator

from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.base import Model
from xtouch_daemon.config.layout_strips import VoipStripConfig
from xtouch_daemon.config.strip import STRIP_TYPE_MEANINGS, refuse_collapse
from xtouch_daemon.config.values import COLORS, ColorName, Label, Slug


class EmptyStripConfig(Model):
    """A dark strip that does nothing."""

    type: Annotated[Literal["empty"], STRIP_TYPE_MEANINGS]

    @model_validator(mode="before")
    @classmethod
    def _no_collapse(cls, data: object) -> object:
        return refuse_collapse(data, "an empty strip is there to keep its place")


class HomeAssistantStripConfig(Model):
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
        return refuse_collapse(data, "a homeassistant strip stays, automations rely on its entities")


StripConfig = Annotated[
    DeviceStripConfig
    | AppsStripConfig
    | AutoStripConfig
    | HomeAssistantStripConfig
    | EmptyStripConfig
    | VoipStripConfig,
    Field(discriminator="type"),
]
STRIP_MODELS: tuple[type[BaseModel], ...] = get_args(get_args(StripConfig)[0])
"""The models of the strip types."""


STRIP_TYPES: tuple[str, ...] = tuple(
    name for model in STRIP_MODELS for name in get_args(model.model_fields["type"].annotation)
)
"""The values of `type` of a strip: output, input, apps, auto, homeassistant, empty, voip."""
