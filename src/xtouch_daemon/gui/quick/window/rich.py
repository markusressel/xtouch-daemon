"""
Texts with markup for QML: the help of the options (`code`, and the words for states, channels and slots in their
colors) in the colors of the theme QML shows, and the tip of a pill as it shows under the mouse.
"""

import html
import re
from collections.abc import Callable, Mapping

from PyQt6.QtGui import QColor

from xtouch_daemon.gui.domain.tokens import Entity

ENTITY_WORDS = re.compile(r"\b(states?|modes?|channels?|pools?|slots?|people|persons?|applications?)\b", re.IGNORECASE)
"""
The words for the things of the configuration, in their colors in the help: people and applications are what the
pools hand out to the slots, so they have the color of the channels. The documentation colors the same words
(docs/javascripts/entities.js): keep the two in line.
"""
CONTROL_WORDS = re.compile(r"\b(?:Select|Mute|Solo|Rec)\b|\b(?:faders?|encoders?|LCDs?|LED rings?)\b")
"""
The controls of the device, in the color of the text and a heavier weight, apart from the muted help around them
(the hues are taken: states, channels, slots, presence, the accent and the tones).
"""
ENTITY_CODE = re.compile(r"\[?(state|mode|channel|pool|people|person|apps|devices|present|slots?|controls)\b")
"""
Their sections and paths in `code`, e.g. `[state.gaming]` or `channel.out`, the pools and the condition of presence.
Not `auto`: it is also the value of an override.
"""
ENTITY_OF = {
    "state": Entity.STATE,
    "mode": Entity.STATE,
    "channel": Entity.CHANNEL,
    "pool": Entity.CHANNEL,
    "people": Entity.CHANNEL,
    "person": Entity.CHANNEL,
    "apps": Entity.CHANNEL,
    "devices": Entity.CHANNEL,
    "present": Entity.PRESENCE,
    "application": Entity.CHANNEL,
    "slot": Entity.SLOT,
    "controls": Entity.SLOT,
}


def entity(word: str) -> Entity:
    word = word.lower()
    return ENTITY_OF[word if word in ENTITY_OF else word.removesuffix("s")]


Colors = Mapping[str, QColor]
"""The colors of a theme, as `Theme.colors` has them."""


def _hex(colors: Colors, name: str) -> str:
    return QColor(colors[name]).name()


def help_html(text: str, colors: Colors) -> str:
    """`text` with `code` in a monospace font and the words of the configuration in their colors."""
    parts: list[str] = []
    for index, part in enumerate(html.escape(part) for part in text.split("`")):
        if not index % 2:
            part = CONTROL_WORDS.sub(
                lambda match: f'<span style="color: {_hex(colors, "text")}; font-weight: 600">{match[0]}</span>', part
            )
            part = ENTITY_WORDS.sub(
                lambda match: f'<span style="color: {_hex(colors, entity(match[1]).value)}">{match[0]}</span>', part
            )
            parts.append(part)
        elif match := ENTITY_CODE.match(part):
            parts.append(f'<code style="color: {_hex(colors, entity(match[1]).value)}">{part}</code>')
        else:
            parts.append(f"<code>{part}</code>")
    return "".join(parts)


def tip_html(tip: str, colors: Colors) -> str:
    """A tip (paragraphs split by an empty line): the first as it is, the others muted."""
    first, *rest = tip.split("\n\n")

    def lines(paragraph: str) -> str:
        return "<br>".join(help_html(line, colors) for line in paragraph.split("\n"))

    muted = _hex(colors, "text_muted")
    return "<br><br>".join([lines(first), *(f'<span style="color: {muted}">{lines(p)}</span>' for p in rest)])


type Rich = Callable[[str], str]
"""Turns a text into its markup: `Shell.rich`."""
