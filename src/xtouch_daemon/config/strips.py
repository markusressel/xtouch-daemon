"""
Every strip type (`StripConfig`), and the strips that control nothing of the sound (`empty`, `homeassistant`,
`custom`).
"""

from collections.abc import Mapping
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, Field, field_validator, model_validator

from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.base import Model
from xtouch_daemon.config.bindings import (
    FADER_PUSH,
    TARGET,
    VALUE,
    ColorPart,
    CustomMeterPart,
    CustomValuePart,
    EntityBinding,
    EntityValueBinding,
    LcdPart,
    PresentPart,
    ServiceAction,
    Target,
    ValueBinding,
    entities_in,
    placeholders_of,
    programs_in,
)
from xtouch_daemon.config.buttons import (
    PATTERN_ACTIONS,
    ButtonConfig,
    ButtonSetup,
    LaunchAction,
    MuteButton,
    RecButton,
    SelectButton,
    SoloButton,
    resolved,
    table_of,
)
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


CustomButtonName = Literal["select", "rec", "solo", "mute"]
CUSTOM_BUTTONS: tuple[CustomButtonName, ...] = get_args(CustomButtonName)
"""The buttons of a `custom` channel: Mute is a button like the others there."""
CUSTOM_PARTS = ("fader", "encoder", "lcd", "color", "meter", "present")
"""The parts of a `custom` channel that can be bound, but its buttons."""
CUSTOM_ACTIONS = frozenset({"off", "next", "cycle_modes", "homeassistant"})
"""The actions of the buttons of a `custom` channel that are a word; `mode:`, `toggle:` and `{ run = [...] }` too."""
CUSTOM_LEDS = frozenset({"off", "press", "homeassistant"})
"""What the LEDs of a `custom` channel show as a word; a `{ watch = [...] }` or `{ poll = [...] }` too."""


class CustomStripConfig(Model):
    """
    A strip of your own: each part does what you bind it to, in Home Assistant or with programs of your own. An
    unbound part is dark and does nothing.
    """

    type: Annotated[Literal["custom"], STRIP_TYPE_MEANINGS]
    label: Label | None = None
    """The top line of the LCD. By default the name of the channel, or of the target with `targets`."""
    color: ColorPart = "white"
    """The backlight of the LCD. A `watch` or a `poll` sets it with each line that is a color name."""
    fader: CustomValuePart | None = None
    """What the fader sets. Without it, the fader stays down. E.g. the brightness of a screen."""
    encoder: CustomValuePart | None = None
    """What the encoder sets. By default the value of the fader, by its `step`."""
    lcd: LcdPart | None = None
    """
    The second line of the LCD. A `watch` or a `poll` shows each line it prints. By default the value of the fader,
    else of the encoder.
    """
    meter: CustomMeterPart | None = None
    """What the LED meter shows. A `watch` or a `poll` makes it show each number it prints, from `min` to `max`."""
    select: SelectButton = ButtonConfig()
    """What Select does (`press`, `hold`) and what its LED shows (`led`). By default nothing."""
    rec: RecButton = ButtonConfig()
    """What Rec does (`press`, `hold`) and what its LED shows (`led`). By default nothing."""
    solo: SoloButton = ButtonConfig()
    """What Solo does (`press`, `hold`) and what its LED shows (`led`). By default nothing."""
    mute: MuteButton = ButtonConfig()
    """What Mute does (`press`, `hold`) and what its LED shows (`led`). By default nothing."""
    present: PresentPart | None = None
    """
    Whether the channel is there. A `watch` or a `poll`: a line with text makes it present, an empty line absent. An
    entity: it is present unless it is `unavailable` or `unknown`. Without it, the channel is always present.
    """
    targets: tuple[Target, ...] = ()
    """
    The things the strip controls one at a time. `{target}` in the programs is the `value` of the target, the LCD
    shows its `name`. Select's `next` switches. E.g. two screens.
    """
    together: bool = False
    """A move sets every target at once. The strip shows the first one."""

    @property
    def uses_home_assistant(self) -> bool:
        """Whether a part belongs to Home Assistant: it needs `[mqtt]`."""
        parts = (self.fader, self.encoder, self.lcd, self.color, self.meter)
        buttons = (part for name in CUSTOM_BUTTONS for part in (self.button(name).press, self.button(name).led))
        return "homeassistant" in (*parts, *buttons)

    @property
    def value_bound(self) -> bool:
        """Whether the fader or the encoder is a value of your own: `{value}` of `run` is its value."""
        return isinstance(self.fader, ValueBinding) or isinstance(self.encoder, ValueBinding)

    @property
    def valued(self) -> bool:
        """Whether the fader or the encoder has a value (of your own, or of an entity): `{value}` of `run` is it."""
        return any(isinstance(knob, ValueBinding | EntityValueBinding) for knob in (self.fader, self.encoder))

    def button(self, name: CustomButtonName) -> ButtonSetup:
        """What a button does: its table, the rest nothing."""
        return resolved(getattr(self, name), ButtonSetup())

    def programs(self) -> dict[str, tuple[str, ...]]:
        """The programs of its parts, by where they are, e.g. `fader.set`, `select.press.run`."""
        return programs_in(self, CUSTOM_PARTS, CUSTOM_BUTTONS)

    def entities(self) -> dict[str, EntityBinding | ServiceAction]:
        """Its parts and actions with entities of Home Assistant, by where they are, e.g. `meter`, `select.press`."""
        return entities_in(self, CUSTOM_PARTS, CUSTOM_BUTTONS)

    @field_validator("targets")
    @classmethod
    def _targets_by_name(cls, value: tuple[Target, ...]) -> tuple[Target, ...]:
        names = [target.name for target in value]
        if twice := sorted({name for name in names if names.count(name) > 1}):
            raise ValueError(f"two targets named {twice[0]}: the LCD tells them apart by their names")
        return value

    @model_validator(mode="before")
    @classmethod
    def _custom_words(cls, data: object) -> object:
        """
        A word the custom type does not take, before the validation of buttons, whose message lists the words of the
        audio strips.
        """
        if isinstance(data, Mapping):
            for name in CUSTOM_BUTTONS:
                table = table_of(name, data.get(name))
                if not isinstance(table, Mapping):
                    continue
                for part in ("press", "hold"):
                    if isinstance(action := table.get(part), str) and (problem := _action_problem(name, part, action)):
                        raise ValueError(problem)
                if isinstance(led := table.get("led"), str) and (problem := _led_problem(name, led)):
                    raise ValueError(problem)
        return data

    @model_validator(mode="after")
    def _all_bound(self) -> CustomStripConfig:
        if isinstance(self.fader, ValueBinding | EntityValueBinding) and self.fader.push is not None:
            raise ValueError(FADER_PUSH)
        if self.together and not self.targets:
            raise ValueError("together: needs targets")
        for name in CUSTOM_BUTTONS:
            self._check_button(name)
        programs = self.programs()
        for where, argv in programs.items():
            used = placeholders_of(argv)
            if "target" in used and not self.targets:
                raise ValueError(f"{where}: {TARGET} needs targets")
            if "value" in used and where.endswith(".run") and not self.valued:
                raise ValueError(f"{where}: {VALUE} needs a fader or an encoder bound to a value")
        if self.targets and not any("target" in placeholders_of(argv) for argv in programs.values()):
            raise ValueError(f"targets: no program has {TARGET}, so the targets would all be the same")
        return self

    def _check_button(self, name: CustomButtonName) -> None:
        setup = self.button(name)
        for part, action in (("press", setup.press), ("hold", setup.hold)):
            if isinstance(action, LaunchAction):
                raise ValueError(f"{name}.{part}: a custom channel runs programs ({{ run = [...] }}), it launches none")
            if isinstance(action, str) and (problem := _action_problem(name, part, action)):
                raise ValueError(problem)
            if action == "next" and (len(self.targets) < 2 or self.together):
                why = "switches nothing with together" if self.together else "needs at least two targets"
                raise ValueError(f"{name}.{part}: next {why}")
        if setup.hold == "homeassistant":
            raise ValueError(f'{name}.hold: "homeassistant" takes the whole button: set it as press')
        if setup.press == "homeassistant" and setup.hold != "off":
            raise ValueError(f"{name}.hold: homeassistant lasts while the button is held, it takes no hold")
        if isinstance(setup.led, str) and (problem := _led_problem(name, setup.led)):
            raise ValueError(problem)


def _action_problem(name: str, part: str, action: str) -> str | None:
    """What is wrong with an action of a button of a custom channel that is a word; None if nothing."""
    if action in CUSTOM_ACTIONS or PATTERN_ACTIONS.fullmatch(action):
        return None
    words = ", ".join(sorted(CUSTOM_ACTIONS))
    return (
        f"{name}.{part}: {action} is not for custom channels ({words}, mode:<id>, toggle:<state>, {{ run = [...] }}, "
        "or { service = ... })"
    )


def _led_problem(name: str, led: str) -> str | None:
    """What is wrong with what the LED of a button of a custom channel shows as a word; None if nothing."""
    if led in CUSTOM_LEDS:
        return None
    words = ", ".join(sorted(CUSTOM_LEDS))
    bindings = "{ watch = [...] }, { poll = [...] }, or { entity = ... }"
    return f"{name}.led: {led} is not for custom channels ({words}, {bindings})"


StripConfig = Annotated[
    DeviceStripConfig
    | AppsStripConfig
    | AutoStripConfig
    | HomeAssistantStripConfig
    | CustomStripConfig
    | EmptyStripConfig
    | VoipStripConfig,
    Field(discriminator="type"),
]
STRIP_MODELS: tuple[type[BaseModel], ...] = get_args(get_args(StripConfig)[0])
"""The models of the strip types."""


STRIP_TYPES: tuple[str, ...] = tuple(
    name for model in STRIP_MODELS for name in get_args(model.model_fields["type"].annotation)
)
"""The values of `type` of a strip: output, input, apps, auto, homeassistant, custom, empty, voip."""
