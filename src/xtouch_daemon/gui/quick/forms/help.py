"""
The help of an option as rich text for QML: the docstring with `code`, the words for the things of the configuration
(states, channels, slots) in their colors, the controls of the device in bold, and under it what an unset option takes
and the link to the documentation. The same words the documentation colors (docs/javascripts/entities.js).
"""

import html
import re

from PyQt6.QtGui import QColor

from xtouch_daemon.gui.qt.theme.tokens import THEMES, ThemeColors, ThemeMode

_ENTITY_WORDS = re.compile(r"\b(states?|modes?|channels?|pools?|slots?|people|persons?|applications?)\b", re.IGNORECASE)
_CONTROL_WORDS = re.compile(r"\b(?:Select|Mute|Solo|Rec)\b|\b(?:faders?|encoders?|LCDs?|LED rings?)\b")
_ENTITY_CODE = re.compile(r"\[?(state|mode|channel|pool|people|person|apps|devices|present|slots?|controls)\b")
_ENTITY_OF = {
    "state": "state",
    "mode": "state",
    "channel": "channel",
    "pool": "channel",
    "people": "channel",
    "person": "channel",
    "apps": "channel",
    "devices": "channel",
    "present": "presence",
    "application": "channel",
    "slot": "slot",
    "controls": "slot",
}
LEARN_MORE = "Learn more"
WHOLE_DEFAULT = 24
"""The longest default kept on one line: a longer one wraps like the text."""
CHIP_SHARE = 0.14
"""How much of the text color the background of a value in help has, over the card."""
GAP = 4


def colors_of(mode: str) -> ThemeColors:
    return THEMES[ThemeMode(mode)] if mode in ThemeMode._value2member_map_ else THEMES[ThemeMode.DARK]


def _hue(word: str, colors: ThemeColors) -> str:
    word = word.lower()
    return getattr(colors, _ENTITY_OF[word if word in _ENTITY_OF else word.removesuffix("s")])


def chip_color(colors: ThemeColors) -> str:
    """A solid color (rich text takes no transparency): the card with a little of the text over it."""
    card, text = QColor(colors.raised), QColor(colors.text)
    mixed = QColor(
        *(round(a + (b - a) * CHIP_SHARE) for a, b in zip(card.getRgb()[:3], text.getRgb()[:3], strict=True))
    )
    return mixed.name()


def help_text(text: str, colors: ThemeColors) -> str:
    """A docstring as rich text (see the module)."""

    def colored(match: re.Match[str]) -> str:
        return f'<span style="color: {_hue(match[1], colors)}">{match[0]}</span>'

    parts: list[str] = []
    for index, part in enumerate(html.escape(part) for part in text.split("`")):
        if not index % 2:
            part = _CONTROL_WORDS.sub(
                lambda match: f'<span style="color: {colors.text}; font-weight: 600">{match[0]}</span>', part
            )
            parts.append(_ENTITY_WORDS.sub(colored, part))
        elif match := _ENTITY_CODE.match(part):
            parts.append(f'<code style="color: {_hue(match[1], colors)}">{part}</code>')
        else:
            parts.append(f"<code>{part}</code>")
    return "".join(parts)


def help_tail(colors: ThemeColors, default: str | None = None, link: str | None = None) -> str:
    """The end of a help, on a line of its own: a muted DEFAULT and the value as a chip, and the link."""
    parts: list[str] = []
    if default:
        value = html.escape(default)
        if len(default) <= WHOLE_DEFAULT:
            value = value.replace(" ", "&nbsp;")
        parts.append(
            f'<span style="color: {colors.text_muted}; font-size: small; font-weight: 700">DEFAULT</span>&nbsp;'
            f'<code style="background-color: {chip_color(colors)}; color: {colors.text}">&nbsp;{value}&nbsp;</code>'
        )
    if link:
        parts.append(
            f'<a href="{html.escape(link)}" style="color: {colors.accent}">'
            f"{LEARN_MORE.replace(' ', '&nbsp;')}&nbsp;↗</a>"
        )
    return ("&nbsp;" * 5).join(parts)


def help_html(text: str, mode: str, link: str | None = None, default: str | None = None) -> str:
    """The help of an option in the theme `mode`: the text, then on a line of its own the default and the link."""
    colors = colors_of(mode)
    tail = help_tail(colors, default, link)
    if not text:
        return tail
    return help_text(text, colors) + (f'<div style="margin-top: {GAP}px">{tail}</div>' if tail else "")
