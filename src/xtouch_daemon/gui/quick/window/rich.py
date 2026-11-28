"""
Texts with markup for QML: the help of the widgets (`code`, and the words for states, channels and slots in their
colors) in the colors of the theme QML shows, and the tip of a pill as it shows under the mouse. The rules are those
of `gui.qt.fields.basics.help_text`, which paints with the colors of the theme of the widgets.
"""

import html
from collections.abc import Callable, Mapping

from PyQt6.QtGui import QColor

from xtouch_daemon.gui.qt.fields.basics import _CONTROL_WORDS, _ENTITY_CODE, _ENTITY_WORDS, _entity  # pyright: ignore[reportPrivateUsage]

Colors = Mapping[str, QColor]
"""The colors of a theme, as `Theme.colors` has them."""


def _hex(colors: Colors, name: str) -> str:
    return QColor(colors[name]).name()


def help_html(text: str, colors: Colors) -> str:
    """`text` with `code` in a monospace font and the words of the configuration in their colors."""
    parts: list[str] = []
    for index, part in enumerate(html.escape(part) for part in text.split("`")):
        if not index % 2:
            part = _CONTROL_WORDS.sub(
                lambda match: f'<span style="color: {_hex(colors, "text")}; font-weight: 600">{match[0]}</span>', part
            )
            part = _ENTITY_WORDS.sub(
                lambda match: f'<span style="color: {_hex(colors, _entity(match[1]).value)}">{match[0]}</span>', part
            )
            parts.append(part)
        elif match := _ENTITY_CODE.match(part):
            parts.append(f'<code style="color: {_hex(colors, _entity(match[1]).value)}">{part}</code>')
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
