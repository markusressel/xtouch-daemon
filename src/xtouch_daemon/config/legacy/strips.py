"""
The strips of the format with strips and layouts: those of today (`config.strips`) and `inherit`, a strip of another
layout.
"""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, Field

from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.base import Model
from xtouch_daemon.config.layout_strips import VoipStripConfig
from xtouch_daemon.config.strip import STRIP_TYPE_MEANINGS, BaseStripConfig
from xtouch_daemon.config.strips import EmptyStripConfig, HomeAssistantStripConfig
from xtouch_daemon.config.values import MAX_STRIPS, Slug


class InheritStripConfig(Model):
    """
    A strip of another layout (or of its own), with all its options: by default the strip of the default layout at
    this place.
    """

    type: Annotated[Literal["inherit"], STRIP_TYPE_MEANINGS]
    layout: Slug | None = None
    """The `name` of the layout of the strip; by default the default layout (the top-level `[[strip]]` list)."""
    strip: Annotated[int, Field(ge=1, le=MAX_STRIPS)] | Slug | None = None
    """
    The strip in that layout: its position in the layout's list (from 1), or its `id`; by default the strip at this
    place.
    """


LegacyStripConfig = Annotated[
    DeviceStripConfig
    | AppsStripConfig
    | AutoStripConfig
    | HomeAssistantStripConfig
    | EmptyStripConfig
    | InheritStripConfig
    | VoipStripConfig,
    Field(discriminator="type"),
]
LEGACY_STRIP_MODELS: tuple[type[BaseModel], ...] = get_args(get_args(LegacyStripConfig)[0])
"""The models of the strip types."""
LEGACY_STRIP_TYPES: tuple[str, ...] = tuple(
    name for model in LEGACY_STRIP_MODELS for name in get_args(model.model_fields["type"].annotation)
)
"""The values of `type` of a strip: output, input, apps, auto, homeassistant, empty, inherit, voip."""


def collapses(strip: LegacyStripConfig) -> bool:
    """Whether the strip gives its place to the ones after it while it has nothing to control (`collapse`)."""
    return isinstance(strip, BaseStripConfig | VoipStripConfig) and strip.collapse
