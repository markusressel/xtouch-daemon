"""
Every strip type (`StripConfig`), and the strips that control nothing of the sound (`empty`, `homeassistant`,
`command`).
"""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, Field, model_validator

from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.base import Model
from xtouch_daemon.config.strip import STRIP_TYPE_MEANINGS
from xtouch_daemon.config.values import COLORS, ColorName, Command, Label
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


VALUE = "{value}"
"""What `set` of a command channel replaces by the value."""


class CommandStripConfig(Model):
    """A strip whose fader and encoder set a value with programs of your own, e.g. the brightness of a screen."""

    type: Annotated[Literal["command"], STRIP_TYPE_MEANINGS]
    label: Label | None = None
    """The top line of the LCD. By default the name of the channel."""
    color: Annotated[ColorName, COLORS] = "white"
    """The backlight of the LCD."""
    set: Command
    """
    The program that sets the value, then each argument; `{value}` in an argument is the new value. E.g.
    `["brightnessctl", "set", "{value}%"]`.
    """
    watch: Command | None = None
    """
    A program that runs all the time and prints the value, one line per change. The fader, the LED ring and the LCD
    follow it.
    """
    min: float = 0.0
    """The value with the fader at the bottom and the LED ring empty."""
    max: float = 100.0
    """The value with the fader at the top and the LED ring full."""
    step: float | None = None
    """How much one step of the encoder changes the value. By default `behavior.encoder_step` percent of the range."""
    push: float | None = None
    """The value a push of the encoder sets, e.g. the full brightness. Without it, a push does nothing."""
    format: str = "{value:g}"
    """How the LCD shows the value, in the format of Python, e.g. `{value:.0%}` shows 0.55 as `55%`."""

    @model_validator(mode="after")
    def _a_value(self) -> CommandStripConfig:
        if self.min >= self.max:
            raise ValueError(f"min: {self.min:g} is not below max ({self.max:g})")
        if not any(VALUE in part for part in self.set[1:]):
            raise ValueError(f"set: no argument has {VALUE}, so the value goes nowhere")
        if self.step is not None and self.step <= 0:
            raise ValueError("step: needs to be above 0")
        if self.push is not None and not self.min <= self.push <= self.max:
            raise ValueError(f"push: {self.push:g} is not between min ({self.min:g}) and max ({self.max:g})")
        try:
            self.format.format(value=self.min)
        except (ValueError, KeyError, IndexError) as e:
            raise ValueError(f"format: {self.format} can't show a value: {e}") from e
        return self


StripConfig = Annotated[
    DeviceStripConfig
    | AppsStripConfig
    | AutoStripConfig
    | HomeAssistantStripConfig
    | CommandStripConfig
    | EmptyStripConfig
    | VoipStripConfig,
    Field(discriminator="type"),
]
STRIP_MODELS: tuple[type[BaseModel], ...] = get_args(get_args(StripConfig)[0])
"""The models of the strip types."""


STRIP_TYPES: tuple[str, ...] = tuple(
    name for model in STRIP_MODELS for name in get_args(model.model_fields["type"].annotation)
)
"""The values of `type` of a strip: output, input, apps, auto, homeassistant, command, empty, voip."""
