"""
What the buttons Select, Rec and Solo of a strip do (see docs/development/design/channel-form.md): a table each with
what a press does, what a hold does (longer than HOLD_TIME) and what its LED shows. `select = true`/`false` and
`rec = "recording"` (an indicator) are shorthands: the first sets `press`, the second `led`.
"""

import re
from dataclasses import dataclass
from typing import Annotated, Literal, get_args

from pydantic import BeforeValidator, Field

from xtouch_daemon.config.base import Meanings, Model
from xtouch_daemon.config.values import INDICATORS, LAUNCH_WHEN_RUNNING_HELP, Command, Indicator

HOLD_TIME = 0.5
"""Seconds a button is held before its `hold` acts; a shorter press does `press`."""

ButtonName = Literal["select", "rec", "solo"]
BUTTON_NAMES: tuple[ButtonName, ...] = get_args(ButtonName)

ACTIONS = Meanings(
    {
        "default": "Makes the device shown the default; when it is, the next one of `device` or `choices`.",
        "next": "The strip shows (and controls) the next one of `device` or `choices` that is there; the default "
        "stays.",
        "profile": "Switches the sound card to the next of `profiles`.",
        "launch": "Starts `launch`.",
        "talk": "Mute is off while the button is held: push to talk. For inputs.",
        "mute_others": "The other strips are muted while the button is held: a solo.",
        "homeassistant": "The button belongs to Home Assistant: an event for each press and release. Needs `[mqtt]`.",
        "cycle_modes": "The next mode, as the chord picks it.",
        "off": "Nothing.",
    }
)
"""The actions of a button that are a word; `mode:<id>`, `toggle:<state>` and `{ launch = [...] }` come on top."""
PATTERN_ACTIONS = re.compile(r"(mode|toggle):[a-z0-9_]+")
"""The actions that name a mode or a state."""
WHILE_HELD = frozenset({"talk", "mute_others", "homeassistant"})
"""Actions that last while the button is held (and end when it is let go), rather than happening once."""
SLOT_ACTIONS = frozenset({"cycle_modes"})
"""Actions of the slots (with `mode:` and `toggle:`): they need `[slots]`."""

LEDS = Meanings(
    {
        **INDICATORS.meanings,
        "press": "Shows what a press does: lit while the device is the default (`default`), for every profile but the "
        "first (`profile`), while the application runs (`launch`), while the mode or state is on, while the "
        "button is held (`talk`, `mute_others`).",
        "shown": "Lit while the strip shows another device than the default one (after `next`).",
    }
)
"""What the LED of a button can show: an indicator, or what its press or `next` does."""
LedShows = Literal["off", "recording", "playing", "default", "muted", "press", "shown"]


def _an_action(value: object) -> object:
    if isinstance(value, str) and value not in ACTIONS.meanings and not PATTERN_ACTIONS.fullmatch(value):
        raise ValueError(
            f"{value} is no action ({', '.join(ACTIONS.meanings)}, mode:<id>, toggle:<state>, or {{ launch = [...] }})"
        )
    return value


class LaunchAction(Model):
    """A program a button starts, as in `[controls]`."""

    launch: Command
    """The program and its arguments."""
    launch_when_running: bool = Field(default=False, description=LAUNCH_WHEN_RUNNING_HELP)


ActionValue = str | LaunchAction
Action = Annotated[ActionValue, BeforeValidator(_an_action)]
"""An action of a button: a word of `ACTIONS`, `mode:<id>`, `toggle:<state>`, or a program to start."""


def describe_action(action: Action) -> str:
    """An action for people: the word, or the program a launch starts."""
    return action if isinstance(action, str) else f"launch {' '.join(action.launch)}"


class ButtonConfig(Model):
    """What a button does: a press, a hold, and what its LED shows. Unset, each takes what the strip type does."""

    press: Annotated[Action, ACTIONS] | None = None
    """What a press does. An action that lasts while held (`talk`, `mute_others`) needs no `hold`."""
    hold: Annotated[Action, ACTIONS] | None = None
    """What holding it for longer than half a second does; then a press acts when the button is let go."""
    led: Annotated[LedShows, LEDS] | None = None
    """What its LED shows."""


def table_of(name: str, value: object) -> object:
    """
    The table of a button for a value in the file: `select = true`/`false` stands for what Select does on the type
    or nothing, an indicator (`rec = "playing"`) for the LED; a table is itself.
    """
    if isinstance(value, bool) and name == "select":
        return {} if value else {"press": "off"}
    if isinstance(value, str):
        return {"led": value}
    return value


def _shorthand(name: ButtonName) -> BeforeValidator:
    # the JSON Schema of the file (`config.json_schema`) takes the short forms too
    written = bool | LedShows | ButtonConfig if name == "select" else LedShows | ButtonConfig
    return BeforeValidator(lambda value: table_of(name, value), json_schema_input_type=written)


SelectButton = Annotated[ButtonConfig, _shorthand("select")]
RecButton = Annotated[ButtonConfig, _shorthand("rec")]
SoloButton = Annotated[ButtonConfig, _shorthand("solo")]


@dataclass(frozen=True)
class ButtonSetup:
    """What a button does, with the defaults of the strip filled in: "off" for nothing."""

    press: Action = "off"
    hold: Action = "off"
    led: LedShows = "off"

    @property
    def acts(self) -> bool:
        return self.press != "off" or self.hold != "off"


def default_setup(
    name: ButtonName, strip_type: str, devices: bool = False, profiles: bool = False, launch: bool = False
) -> ButtonSetup:
    """
    What a button does without its table, on a strip of the type: Select makes the device the default (with `device`
    or `choices`: `devices`) or starts `launch`, Rec switches `profiles`, the LED of Rec shows a recording.
    """
    match name:
        case "select" if strip_type in ("output", "input") and devices:
            return ButtonSetup("default", led="press")
        case "select" if launch:
            return ButtonSetup("launch", led="press")
        case "rec" if profiles:
            return ButtonSetup("profile", led="press")
        case "rec":
            return ButtonSetup(led="recording")
        case _:
            return ButtonSetup()


def resolved(button: ButtonConfig, default: ButtonSetup) -> ButtonSetup:
    """The setup of a button: what its table says, the rest from `default`."""
    return ButtonSetup(
        default.press if button.press is None else button.press,
        default.hold if button.hold is None else button.hold,
        default.led if button.led is None else button.led,
    )


def indicator(led: LedShows) -> Indicator | None:
    """The indicator an LED shows, None for `press` and `shown`."""
    match led:
        case "press" | "shown":
            return None
        case _:
            return led
