"""
The logic of a part that can be bound (`Kind.BINDING`, see docs/development/design/bindings.md): how it is bound now,
what binding it to something else makes of its value, and what the options of a program or an entity take when unset.
"""

from collections.abc import Callable, Mapping
from typing import Any, cast

from xtouch_daemon.config.bindings import HOME_ASSISTANT
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.gui.domain.schema import Option, describe

PROGRAM = "program"
"""The mode of a part bound to a program of your own (a table)."""
WORDS = "words"
"""The mode of a part that is not bound: its words, or its default."""
CHANNEL = "channel"
"""The mode of a fader or an encoder of `[controls]` that sets the value of a `custom` channel (`{ channel = ... }`)."""
ENTITY = "entity"
"""The mode of a part bound to an entity of Home Assistant (`{ entity = ... }`)."""

MODE_TITLES = {
    HOME_ASSISTANT: "Home Assistant",
    ENTITY: "An entity",
    PROGRAM: "A program",
    CHANNEL: "A channel",
    WORDS: "Not bound",
}
"""The modes of a part for people, as the menu of the button and the button show them."""

COLUMN_PLACEHOLDERS: dict[str, str] = {
    "step": "behavior.encoder_step % of the range",
    "push": "none: a push does nothing",
    "watch": "none: the value shows what was set last",
}
"""What an unset option of a program does, where its default is no value."""
DEFAULT_ENCODER_STEP = BehaviorConfig.model_fields["encoder_step"].default
"""Percent of the range one step of the encoder is by default (`behavior.encoder_step`)."""


def mode_of(value: object) -> str:
    """
    How a part is bound: `CHANNEL` for a table with `channel`, `ENTITY` for one with `entity`, `PROGRAM` for another
    table, `HOME_ASSISTANT`, or `WORDS` for a word, a switch or nothing.
    """
    if isinstance(value, Mapping):
        return CHANNEL if "channel" in value else ENTITY if "entity" in value else PROGRAM
    return HOME_ASSISTANT if value == HOME_ASSISTANT else WORDS


def modes_of(option: Option) -> list[dict[str, str]]:
    """The modes the part can be bound to, with their titles, in the order of the menu."""
    modes = [
        *([HOME_ASSISTANT] if option.home_assistant else []),
        *([ENTITY] if option.entity is not None else []),
        PROGRAM,
        *([CHANNEL] if option.channel else []),
        WORDS,
    ]
    return [{"mode": mode, "title": MODE_TITLES[mode]} for mode in modes]


def bind_tip(option: Option, value: object) -> str:
    """What the button of the binding says of itself."""
    mode = mode_of(value)
    if not in_words(option, value):
        title = MODE_TITLES[mode]
        return f"Bound to {title if mode == HOME_ASSISTANT else title.lower()}: click to change"
    targets = [
        *(["Home Assistant"] if option.home_assistant else []),
        *(
            ["one of its entities" if option.home_assistant else "an entity of Home Assistant"]
            if option.entity is not None
            else []
        ),
        "a program of your own",
        *(["a custom channel"] if option.channel else []),
    ]
    return "Bind it to " + (", ".join(targets[:-1]) + " or " if len(targets) > 1 else "") + targets[-1]


def in_words(option: Option, value: object) -> bool:
    """Whether the field of the words shows: not bound, or bound to Home Assistant where that is one of the words."""
    mode = mode_of(value)
    return mode == WORDS or (mode == HOME_ASSISTANT and HOME_ASSISTANT in option.choices)


def bound_value(mode: str, kept: Mapping[str, Any], channels: list[str]) -> object:
    """
    The value of binding the part to `mode`: Home Assistant, a program or an entity with the options they had last
    (`kept` has them by mode), a channel (the first `custom` one), or None (not bound: the default).
    """
    if mode == CHANNEL:
        return {"channel": channels[0] if channels else ""}
    return {
        HOME_ASSISTANT: HOME_ASSISTANT,
        PROGRAM: dict(kept.get(PROGRAM) or {}),
        ENTITY: dict(kept.get(ENTITY) or {"entity": ""}),
        WORDS: None,
    }[mode]


def word(option: Option, value: object, placeholder: str | None) -> object:
    """The word shown (or what it is by default), None while the part is bound to a program, a channel or an entity."""
    if mode_of(value) in (PROGRAM, CHANNEL, ENTITY):
        return None
    if value is None and option.default is None and placeholder:
        return placeholder
    return option.default if value is None else value


def number_start(name: str, table: Mapping[str, Any]) -> float:
    """Where a number of the program starts once it is set: `step` at one step of the range, the rest at `min`."""
    low, high = table.get("min", 0), table.get("max", 100)
    if not isinstance(low, int | float) or not isinstance(high, int | float) or high <= low:
        low, high = 0, 100
    return (high - low) * DEFAULT_ENCODER_STEP / 100 if name == "step" else float(low)


def default_text(option: Option, placeholder: Callable[[], str] | None) -> str:
    return placeholder() if placeholder is not None else describe(option.default)


def nested(
    problems: list[tuple[tuple[int | str, ...], str]], columns: set[str]
) -> tuple[dict[str, list[str]], list[str]]:
    """
    Splits the problems of a binding: those of an option of its program (`fader.max`, or a message "service: nothing
    sets ...") go to the option, the rest stay. Each problem is its path below the option and its message.
    """
    by_column: dict[str, list[str]] = {name: [] for name in columns}
    rest: list[str] = []
    for below, message in problems:
        named, colon, said = message.partition(": ")
        if below and cast(str, below[0]) in by_column:
            by_column[cast(str, below[0])].append(message)
        elif not below and colon and named in by_column:
            by_column[named].append(said[:1].upper() + said[1:])
        else:
            rest.append(message)
    return by_column, rest
