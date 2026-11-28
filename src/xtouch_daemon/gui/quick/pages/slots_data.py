"""
What the page Slots shows, as plain data for QML: the rows of a card, the crumbs, the steps of why, the lines of the
overview. No Qt here: the backend (`slots.py`) puts these into models and properties, the tests read them directly.

Texts that QML shows as rich text name a color of the theme as `@state`, `@channel`, ... (see `rich`): QML swaps
them for the colors of the theme shown, so a new theme recolors them at once.
"""

import html
import re
from collections.abc import Mapping, Sequence
from typing import Any

from xtouch_daemon.gui.domain.slot_stacks import (
    ALWAYS,
    EMPTY,
    Row,
    Step,
    StepKind,
    ends_dark,
    free_text,
    free_words,
    is_pool,
    lcd_colors,
    readable,
    row_state,
)
from xtouch_daemon.gui.domain.status import Tone
from xtouch_daemon.gui.domain.tokens import LCD_COLORS
from xtouch_daemon.gui.quick.pages.sound import sound_of
from xtouch_daemon.gui.quick.window.rich import CONTROL_WORDS, ENTITY_CODE, ENTITY_OF, ENTITY_WORDS
from xtouch_daemon.slots.model import AUTO

CardRow = tuple[str, dict[str, Any]]
"""A row of a card with its key (see `KeyedListModel`)."""


def option_text(value: Any) -> str:
    """A value of an option as in the file, without quotes: `white`, `true`, `[a, b]`."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return "[" + ", ".join(option_text(item) for item in value) + "]"  # pyright: ignore[reportUnknownVariableType]
    return str(value)


def _entity(word: str) -> str:
    word = word.lower()
    return ENTITY_OF[word if word in ENTITY_OF else word.removesuffix("s")].value


def rich(text: str) -> str:
    """
    Help text as rich text, with `code` in a monospace font and the words of states, channels and slots in their
    colors, which it names as `@state`: see the module (`help_text` of the widgets, for QML).
    """
    parts: list[str] = []
    for index, part in enumerate(html.escape(part) for part in text.split("`")):
        if not index % 2:
            part = CONTROL_WORDS.sub(
                lambda match: f'<span style="color: @text; font-weight: 600">{match[0]}</span>', part
            )
            parts.append(
                ENTITY_WORDS.sub(lambda match: f'<span style="color: @{_entity(match[1])}">{match[0]}</span>', part)
            )
        elif match := ENTITY_CODE.match(part):
            parts.append(f'<code style="color: @{_entity(match[1])}">{part}</code>')
        else:
            parts.append(f"<code>{part}</code>")
    return "".join(parts)


def rich_lines(text: str) -> str:
    """`rich`, the lines of `text` as lines."""
    return "<br>".join(rich(line) for line in text.split("\n"))


LCD_OFF = LCD_COLORS["off"]


def candidate_data(
    candidate: Row,
    state: str,
    index: int,
    count: int,
    values: Mapping[str, Any],
    reason: str,
    member: tuple[str, str] | None,
) -> dict[str, Any]:
    """What a row of a candidate shows (see `candidate_rule` of the widget cards), for QML."""
    chips: list[dict[str, Any]] = []
    if candidate.chips == (ALWAYS,) and is_pool(values, candidate.show):
        lead = "when"
        chips.append(
            {
                "text": free_words(values, candidate.show),
                "kind": "presence",
                "tip": free_text(values, candidate.show),
                "file": False,
            }
        )
    elif candidate.chips == (ALWAYS,):
        lead = "otherwise" if index == count - 1 and count > 1 else ALWAYS
    else:
        lead = "when"
        for position, part in enumerate(candidate.chips):
            words, presence = readable(part, candidate.show, values)
            chips.append(
                {
                    "text": words,
                    "kind": "presence" if presence else "state",
                    "or": position > 0,
                    "tip": f"In the file: {part}",
                }
            )
    # a color the LCD has no backlight for has no swatch: the problems name it
    colors = [(color, where) for color, where in lcd_colors(values, candidate) if color in LCD_COLORS]
    lcd = "\n".join(f"The LCD: {color} ({where})" for color, where in colors)
    nothing = candidate.show == EMPTY
    show_tip = ""
    if member is not None:
        show_tip = f"{candidate.show} hands out {member[0]} here. " + (member[1] or "Nobody else waits for a slot.")
    channel = values.get("channel", {}).get(candidate.show)
    sound = sound_of(channel.get("type")) if isinstance(channel, Mapping) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    # a color the LCD has no backlight for stays as text, for the problems to name
    rest = {
        name: value
        for name, value in candidate.options.items()
        if name != "color" or not (isinstance(value, str) and value in LCD_COLORS)
    }
    options = ", ".join(f"{name} = {option_text(value)}" for name, value in rest.items())
    tip = (
        "The device shows this one now"
        if state == "shown"
        else "Not reached: a candidate above it is shown"
        if state == "unreached"
        else ""
    )
    return {
        "number": str(index + 1),
        "lead": lead,
        "chips": chips,
        "show": candidate.show if member is None else f"{candidate.show} · {member[0]}",
        "nothing": nothing,
        "swatches": [LCD_COLORS[color] for color, _ in colors],
        "swatchTips": [f"{color}: {where}" if nothing else lcd for color, where in colors],
        "showTip": "\n\n".join(part for part in (show_tip, lcd) if part),
        "sound": candidate.show if sound is not None and not nothing else "",
        "soundKind": sound.value if sound is not None else "",
        "options": options,
        "optionsTip": f"Options of the strip in this slot only: {options}" if options else "",
        "reason": reason,
        "state": state,
        "tip": tip,
        "first": index == 0,
        "last": index == count - 1,
        "end": False,
        "candidate": True,
    }


def end_data(index: int, count: int, dark: bool, state: str) -> dict[str, Any]:
    """The dark strip at the end of the rail."""
    return {
        "number": "",
        "lead": "",
        "chips": [],
        "show": "nothing to show: the strip is dark" if dark else "nothing to show: the strip goes dark",
        "nothing": True,
        "swatches": [LCD_OFF],
        "swatchTips": ["off: the LCD is dark"],
        "showTip": "",
        "sound": "",
        "soundKind": "",
        "options": "",
        "optionsTip": "",
        "reason": "",
        "state": state,
        "tip": (
            "No candidate has anything to show now, so the strip is dark"
            if dark
            else "When no candidate above has anything to show, the strip goes dark"
        ),
        "first": index == 0,
        "last": True,
        "end": True,
        "candidate": False,
    }


def card_rows(
    candidates: list[Row],
    shown: int | None,
    why: Mapping[int, str],
    values: Mapping[str, Any],
    dark: bool,
    member: tuple[str, str] | None,
) -> list[CardRow]:
    """
    The rows of a card, each with its key: the candidate as the file has it (and how often it came before, for two
    alike), so a row keeps its key while only its state, its reason or what it hands out changes.
    """
    count = len(candidates) + ends_dark(candidates)
    result: list[CardRow] = []
    seen: dict[str, int] = {}
    for index, candidate in enumerate(candidates):
        state = row_state(index, shown, dark)
        identity = repr(candidate.entry())
        seen[identity] = seen.get(identity, 0) + 1
        data = candidate_data(
            candidate, state, index, count, values, why.get(index, ""), member if state == "shown" else None
        )
        result.append((f"{identity}#{seen[identity]}", data))
    if ends_dark(candidates):
        state = "shown" if dark else "" if shown is None else "unreached"
        result.append(("end", end_data(len(candidates), count, dark, state)))
    if not result:
        # a slot without candidates: `auto`, which picks the slot
        result.append(
            (
                "auto",
                {
                    **end_data(0, 1, False, ""),
                    "show": f"{AUTO} (no entry)",
                    "swatches": [],
                    "swatchTips": [],
                    "tip": "",
                    "end": False,
                },
            )
        )
    return result


# -- the inspector --------------------------------------------------------------------------------------------------

MARKS = {
    StepKind.PASSED: ("✗", "text_muted"),
    StepKind.HELD: ("●", "tone_warn"),
    StepKind.SHOWN: ("→", "tone_good"),
    StepKind.DARK: ("○", "text_muted"),
}
"""The mark of a step of why and the name of its color."""


def why_rows(steps: Sequence[Step]) -> list[tuple[str, dict[str, Any]]]:
    """The steps of why as rows of a list, keyed by their place and subject."""
    rows: list[tuple[str, dict[str, Any]]] = []
    for line, step in enumerate(steps):
        mark, color = MARKS[step.kind]
        rows.append(
            (
                f"{line}:{step.subject}",
                {
                    "mark": mark,
                    "color": color,
                    "subject": step.subject,
                    "final": step.kind in (StepKind.SHOWN, StepKind.DARK),
                    "reason": rich(step.reason) if step.reason else "",
                },
            )
        )
    return rows


def why_tone(steps: Sequence[Step]) -> Tone:
    """Good while the slot shows something, else neutral."""
    return Tone.GOOD if steps and steps[-1].kind == StepKind.SHOWN else Tone.NEUTRAL


def crumb_rows(
    stack: Sequence[Row], candidate: int | None, shown: int | None, dark: bool, end: bool, strip_dark: bool, ends: bool
) -> list[tuple[str, dict[str, Any]]]:
    """
    `Slot 3 › 1 games › 2 apps › dark`: the candidates in order, the one picked checked, the one the slot shows with a
    dot (a ring while it came to it and has nothing left), and the dark end of the rail.
    """
    rows: list[tuple[str, dict[str, Any]]] = []
    for index, row in enumerate(stack):
        when = f"when {row.when}" if row.when else "always"
        more = (
            ("; the slot came to it, and it has none left" if dark else "; the slot shows it") if index == shown else ""
        )
        rows.append(
            (
                f"c{index}",
                {
                    "text": f"{index + 1}  {row.show}",
                    "mark": ("ring" if dark else "dot") if index == shown else "",
                    "checked": index == candidate,
                    "tip": f"Candidate {index + 1} of {len(stack)}: {when} → {row.show}{more}",
                    "row": index,
                },
            )
        )
    if ends:
        rows.append(
            (
                "end",
                {
                    "text": "dark",
                    "mark": "dot" if strip_dark else "",
                    "checked": end,
                    "tip": (
                        "None of the candidates has anything to show now, so the strip is dark"
                        if strip_dark
                        else "When none of the candidates has anything to show, the strip goes dark"
                    ),
                    "row": len(stack),
                },
            )
        )
    return rows


def hint_text(slot: int, stack: Sequence[Row], candidate: int | None, end: bool, strip_dark: bool) -> str:
    """What to do next, by what is picked: a candidate, or the end of the rail (dark now or not)."""
    if not stack:
        return (
            f"Slot {slot} has no candidate: it shows `auto`, the next application that plays or person of the voice "
            "chat. Add a candidate (+ on its card) to show a channel here, e.g. an output."
        )
    if end and strip_dark:
        return (
            "The strip is dark: none of the candidates has anything to show now. + adds a candidate at the end, "
            "e.g. an output, which is always there."
        )
    if end:
        return (
            "When none of the candidates has anything to show, the strip goes dark. + adds a candidate at the end, "
            "e.g. an output, which is always there."
        )
    if candidate is None:
        return "Pick a candidate to edit it. The first one whose condition holds is shown; + adds one at the end."
    return ""


def overview_row(slot: int, count: int, problems: int, steps: Sequence[Step]) -> tuple[str, dict[str, Any]]:
    """A line of the overview: what the slot shows now (while the daemon tells it), its candidates, its problems."""
    candidates = f"{count} candidate{'s' if count != 1 else ''}" if count else "no candidate: `auto`"
    parts = [candidates]
    tone = Tone.NEUTRAL
    if steps:
        final = steps[-1]
        if final.kind is StepKind.SHOWN:
            parts.insert(0, f"shows {final.subject}")
            tone = Tone.GOOD
        elif final.kind is StepKind.DARK:
            parts.insert(0, f"dark: {final.reason}")
    if problems:
        parts.append(f"{problems} problem{'s' if problems != 1 else ''}")
        tone = Tone.BAD
    text = "; ".join(parts)
    text = text[:1].upper() + text[1:]
    return str(slot), {
        "slot": slot,
        "text": rich(text),
        "plain": re.sub(r"`", "", text),
        "tone": tone.value,
        "tip": f"Pick slot {slot}",
    }
