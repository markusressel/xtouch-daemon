"""
The lines of the list of suggestions under a field (devices, applications, people, entities): what the user would
see of a `Suggestion`, as rich text with what matches what was typed highlighted, and the lines for a typed text.
"""

import html
from collections.abc import Callable
from typing import Any

from xtouch_daemon.gui.domain import sources
from xtouch_daemon.gui.domain.entities import domain_icon
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt.theme.tokens import ThemeColors

type Suggest = Callable[[], tuple[Suggestion, ...]]
type ColumnSuggest = Callable[[dict[str, Any]], tuple[Suggestion, ...]]
type TableSuggest = dict[str, ColumnSuggest]

NO_SUGGESTIONS = "The sound server has none right now"
"""What the list says without any, for most options: they come from the sound server."""
NO_SUGGESTIONS_OF: dict[str, str] = {
    "person": "Nobody is in the voice chat right now, or the daemon does not run",
}
"""What it says for the options whose suggestions come from somewhere else, by name."""


def highlighted(text: str, query: str, color: str) -> str:
    """`text` as rich text, with the parts that match `query` (see `sources.spans`) bold in `color`."""
    parts: list[str] = []
    at = 0
    for start, end in sources.spans(text, query):
        parts.append(html.escape(text[at:start]))
        parts.append(f'<b style="color: {color}">{html.escape(text[start:end])}</b>')
        at = end
    parts.append(html.escape(text[at:]))
    return "".join(parts)


def suggestion_html(suggestion: Suggestion, query: str, colors: ThemeColors) -> str:
    """
    A line of the list: what it is (the detail) and where it is known from, and below it the name that goes into the
    option, with the parts that match `query` highlighted.
    """
    origin = suggestion.origin or ("" if suggestion.present else "not there now")
    tag = f'&nbsp;&nbsp;<span style="color: {colors.text_muted}">· {html.escape(origin)}</span>' if origin else ""
    name = highlighted(suggestion.value, query, colors.accent)
    if not suggestion.detail:
        return f"<code>{name}</code>{tag}"
    detail = highlighted(suggestion.detail, query, colors.accent)
    return f'{detail}{tag}<br><code style="color: {colors.text_muted}">{name}</code>'


def lines(
    found: tuple[Suggestion, ...], query: str, colors: ThemeColors, nothing: str, icons: bool = False
) -> dict[str, Any]:
    """The lines of the list for the suggestions that fit `query`; `nothing` says why a list is empty."""
    rows = [
        {
            "value": suggestion.value,
            "html": suggestion_html(suggestion, query, colors),
            "tip": (suggestion.tip or suggestion.detail or suggestion.value)
            + ("\n\nDelete forgets it." if suggestion.forget is not None else ""),
            "preset": suggestion.preset,
            "forget": suggestion.forget is not None,
            "present": suggestion.present,
            "icon": domain_icon(suggestion.value) if icons else "",
        }
        for suggestion in found
    ]
    return {"rows": rows, "empty": nothing if not query else f"Nothing known matches {query!r}"}
