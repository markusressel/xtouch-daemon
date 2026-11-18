"""
Every strip type (`StripConfig`), and the strips that control nothing of the sound (`empty`, `homeassistant`).
"""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, Field

from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.base import Model
from xtouch_daemon.config.strip import STRIP_TYPE_MEANINGS
from xtouch_daemon.config.values import COLORS, ColorName, Label
from xtouch_daemon.config.voip_strips import VoipStripConfig


class EmptyStripConfig(Model):
    """A dark strip that does nothing."""

    type: Annotated[Literal["empty"], STRIP_TYPE_MEANINGS]


class HomeAssistantStripConfig(Model):
    """A strip that belongs to Home Assistant: its parts are entities there, automations decide what they do."""

    type: Annotated[Literal["homeassistant"], STRIP_TYPE_MEANINGS]
    label: Label | None = None
    """The top line of the LCD until Home Assistant sets one. The names of the entities start with it."""
    color: Annotated[ColorName, COLORS] = "white"
    """The backlight of the LCD until Home Assistant sets one."""


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
