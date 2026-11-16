"""
What the fields share: labels and help texts, suggestions from the sound server (completers and menus), small
buttons.
"""

import html
from collections.abc import Callable, Mapping

from PyQt6.QtCore import QStringListModel, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QCompleter,
    QLabel,
    QLineEdit,
    QMenu,
    QToolButton,
    QWidget,
)

from xtouch_daemon.config.presets import Kind as PresetKind
from xtouch_daemon.gui.domain.sources import Suggestion, preset_suggestions
from xtouch_daemon.gui.domain.status import Status
from xtouch_daemon.gui.qt import theme

type Suggest = Callable[[], tuple[Suggestion, ...]]
"""What the sound server has now for an option, asked for every time it is needed."""
type ColumnSuggest = Callable[[dict[str, str | int]], tuple[Suggestion, ...]]
"""What the sound server has now for a column of a table, given the other values of its line (e.g. its card)."""
type TableSuggest = Mapping[str, ColumnSuggest]
"""The suggestions for the columns of a table that have some, by name."""

NO_SUGGESTIONS = "The sound server has none right now"
"""What the menu of suggestions says without any, for most options: they come from the sound server."""
NO_SUGGESTIONS_OF: dict[str, str] = {
    "person": "Nobody is in the voice chat right now, or the daemon does not run",
}
"""What it says for the options whose suggestions come from somewhere else, by name."""

CHIP_HEIGHT = 2 * theme.Radius.PILL

LABEL_WIDTH = 144
"""The width of the names of the options, so the fields line up (on the 8 px grid)."""


def label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        theme.set_role(widget, role)
    widget.setWordWrap(wrap)
    return widget


def show_status(pill: QLabel, status: Status) -> None:
    """A status in a pill: its text, its tone as the color, and its tip."""
    pill.setText(status.text)
    pill.setToolTip(status.tip)
    theme.set_role(pill, status.tone.value, "tone")


def help_text(text: str) -> str:
    """Help from a docstring, with `code` in a monospace font."""
    parts = [html.escape(part) for part in text.split("`")]
    return "".join(f"<code>{part}</code>" if i % 2 else part for i, part in enumerate(parts))


LEARN_MORE = "Learn more"


def help_html(text: str, link: str | None = None) -> str:
    """Help from a docstring, and a link to where the documentation explains more."""
    more = f'<a href="{html.escape(link)}">{LEARN_MORE}</a>' if link else ""
    return " ".join(part for part in (help_text(text), more) if part)


def help_label(text: str, role: str, link: str | None = None) -> QLabel:
    """
    A label with help from a docstring, and a link to the documentation, opened in the browser; always rich text, as
    Qt would show text without tags as it is.
    """
    widget = label(help_html(text, link), role, wrap=True)
    widget.setTextFormat(Qt.TextFormat.RichText)
    widget.setOpenExternalLinks(True)
    return widget


def flat_button(icon: str, tip: str, parent: QWidget | None = None) -> QToolButton:
    button = QToolButton(parent)
    theme.set_icon(button, icon)
    button.setToolTip(tip)
    button.setAutoRaise(True)
    theme.set_role(button, "flat", "variant")
    return button


def completer(edit: QLineEdit, suggest: Suggest) -> QCompleter:
    """Completes what the sound server has, by any part of it."""
    model = QStringListModel(edit)
    result = QCompleter(model, edit)
    result.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    result.setFilterMode(Qt.MatchFlag.MatchContains)
    edit.setCompleter(result)
    edit.textEdited.connect(lambda _: model.setStringList([suggestion.value for suggestion in suggest()]))
    return result


MENU_TIP = "Pick from what the sound server has now"
PRESETS_MENU_TIP = "Pick a preset, or from what the sound server has now"


def suggestion_menu(
    parent: QWidget,
    suggest: Suggest,
    pick: Callable[[str], None],
    empty: str,
    tip: str = MENU_TIP,
) -> QToolButton:
    """
    A button with a menu of what the sound server has now; picking one calls `pick` with its value. Presets come
    first, under a heading of their own, with what they stand for as their tooltips.
    """
    button = flat_button("menu-down", tip, parent)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QMenu(button)
    menu.setToolTipsVisible(True)
    button.setMenu(menu)

    def fill() -> None:
        menu.clear()
        suggestions = suggest()
        if not suggestions:
            action = QAction(empty, menu)
            action.setEnabled(False)
            menu.addAction(action)
        named = [suggestion for suggestion in suggestions if suggestion.preset]
        others = [suggestion for suggestion in suggestions if not suggestion.preset]
        for heading, group in (("Presets", named), ("Names", others)):
            if named and group:
                menu.addSection(heading)
            for suggestion in group:
                text = f"{suggestion.value}    {suggestion.detail}" if suggestion.detail else suggestion.value
                action = QAction(text, menu)
                action.setToolTip(suggestion.tip or text)
                action.triggered.connect(lambda _=False, value=suggestion.value: pick(value))
                menu.addAction(action)

    menu.aboutToShow.connect(fill)
    return button


def with_presets(kind: PresetKind, suggest: Suggest | None) -> Suggest:
    """The presets of a list of names of the kind, and then the suggestions of the sound server."""
    return lambda: preset_suggestions(kind) + (suggest() if suggest is not None else ())
