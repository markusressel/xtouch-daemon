"""
What the fields share: labels and help texts, suggestions from the sound server (completers and menus), small
buttons.
"""

import html
import re
from collections.abc import Callable, Mapping

from PyQt6.QtCore import QSize, QStringListModel, Qt
from PyQt6.QtGui import QAction, QPainter, QPaintEvent
from PyQt6.QtWidgets import (
    QCompleter,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QToolButton,
    QWidget,
)

from xtouch_daemon.config.presets import Kind as PresetKind
from xtouch_daemon.gui.domain.sources import Suggestion, preset_suggestions
from xtouch_daemon.gui.domain.status import Status
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.style import current_colors, set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Radius

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

CHIP_HEIGHT = 2 * Radius.PILL

LABEL_WIDTH = 144
"""The width of the names of the options, so the fields line up (on the 8 px grid)."""


def label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        set_role(widget, role)
    widget.setWordWrap(wrap)
    return widget


class ElidedLabel(QLabel):
    """
    A line of text that changes while the window is open (a status, a path): it takes the room it gets and ends in …
    where it does not fit, so a longer text never makes the window wider or a bar taller. Without a tip of its own
    (`own_tip`), the tip is the whole text while it is cut.
    """

    def __init__(self, text: str = "", role: str = "", elide: Qt.TextElideMode = Qt.TextElideMode.ElideRight):
        super().__init__(text)
        if role:
            set_role(self, role)
        self.elide = elide
        self.own_tip = False

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def setToolTip(self, tip: str | None) -> None:
        self.own_tip = bool(tip)
        super().setToolTip(tip)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        rect = self.contentsRect()
        shown = self.fontMetrics().elidedText(self.text(), self.elide, rect.width())
        if not self.own_tip:
            super().setToolTip(self.text() if shown != self.text() else "")
        style = self.style()
        assert style is not None
        style.drawItemText(
            QPainter(self), rect, int(self.alignment()), self.palette(), self.isEnabled(), shown, self.foregroundRole()
        )


def entity_label(text: str, entity: Entity, chip: bool = False) -> QLabel:
    """A state, a channel or a slot (or what stands for one) in its color; as a chip, on a tint of it."""
    widget = label(text, "chip" if chip else "")
    set_role(widget, entity.value, "entity")
    return widget


def discard(layout: QLayout, widget: QWidget) -> None:
    """
    Takes `widget` out of `layout` and off the screen at once: `deleteLater` alone leaves it there until the event
    loop deletes it, so the layout would make room for the old widget and its replacement in between.
    """
    layout.removeWidget(widget)
    widget.hide()
    widget.deleteLater()


def show_status(pill: QLabel, status: Status) -> None:
    """A status in a pill: its text, its tone as the color, and its tip."""
    pill.setText(status.text)
    pill.setToolTip(status.tip)
    set_role(pill, status.tone.value, "tone")


_ENTITY_WORDS = re.compile(r"\b(states?|modes?|channels?|pools?|slots?)\b", re.IGNORECASE)
"""The words for the things of the configuration, in their colors in the help."""
_ENTITY_CODE = re.compile(r"\[?(state|mode|channel|pool|people|slots?|controls)\b")
"""Their sections and paths in `code`, e.g. `[state.gaming]` or `channel.out`."""
_ENTITY_OF = {
    "state": Entity.STATE,
    "mode": Entity.STATE,
    "channel": Entity.CHANNEL,
    "pool": Entity.CHANNEL,
    "people": Entity.CHANNEL,
    "slot": Entity.SLOT,
    "controls": Entity.SLOT,
}


def _entity(word: str) -> Entity:
    word = word.lower()
    return _ENTITY_OF[word if word in _ENTITY_OF else word.removesuffix("s")]


def help_text(text: str) -> str:
    """
    Help from a docstring, with `code` in a monospace font, and the states, channels and slots it is about in their
    colors (see `Entity`): the words, and their sections in `code`.
    """
    colors = current_colors()

    def colored(match: re.Match[str]) -> str:
        return f'<span style="color: {getattr(colors, _entity(match[1]).value)}">{match[0]}</span>'

    parts: list[str] = []
    for index, part in enumerate(html.escape(part) for part in text.split("`")):
        if not index % 2:
            parts.append(_ENTITY_WORDS.sub(colored, part))
        elif match := _ENTITY_CODE.match(part):
            parts.append(f'<code style="color: {getattr(colors, _entity(match[1]).value)}">{part}</code>')
        else:
            parts.append(f"<code>{part}</code>")
    return "".join(parts)


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
    widget = label("", role, wrap=True)
    widget.setTextFormat(Qt.TextFormat.RichText)
    widget.setOpenExternalLinks(True)
    set_help(widget, text, link)
    return widget


_HELP_PROPERTY = "help_source"


def set_help(widget: QLabel, text: str, link: str | None = None) -> None:
    """
    Shows help from a docstring (see `help_html`) in `widget`, and keeps it to draw it again in the colors of
    another theme (see `refresh_help`). The same help again does nothing: it would lay out the window again.
    """
    if widget.property(_HELP_PROPERTY) == (text, link):
        return
    widget.setProperty(_HELP_PROPERTY, (text, link))
    widget.setText(help_html(text, link))


def refresh_help(root: QWidget) -> None:
    """Draws the help in `root` (see `set_help`) again, in the colors of the theme applied since."""
    for widget in root.findChildren(QLabel):
        source = widget.property(_HELP_PROPERTY)
        if source is not None:
            widget.setText(help_html(*source))


def flat_button(icon: str, tip: str, parent: QWidget | None = None) -> QToolButton:
    button = QToolButton(parent)
    set_icon(button, icon)
    button.setToolTip(tip)
    button.setAutoRaise(True)
    set_role(button, "flat", "variant")
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
