"""
What the fields share: labels and help texts, suggestions from the sound server (completers and menus), small
buttons.
"""

import html
import math
import re
from collections.abc import Callable, Mapping

from PyQt6.QtCore import QPointF, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPaintEvent, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QLabel,
    QLayout,
    QStyle,
    QStyleOption,
    QToolButton,
    QWidget,
)

from xtouch_daemon.config.presets import Kind as PresetKind
from xtouch_daemon.gui.domain.sources import Suggestion, preset_suggestions
from xtouch_daemon.gui.domain.status import Status
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.style import current_colors, set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Radius, Space

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


def indent_text(spin: QAbstractSpinBox) -> QAbstractSpinBox:
    """
    A spin box with its text where the other fields have theirs: the style sheet's padding does not reach the line
    edit in it, which would draw the text at the border.
    """
    edit = spin.lineEdit()
    if edit is not None:
        edit.setTextMargins(Space.S, 0, 0, 0)
    return spin


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
        painter = QPainter(self)
        # the background and border of its role (a pill), as the label would draw them
        option = QStyleOption()
        option.initFrom(self)
        style.drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        style.drawItemText(
            painter, rect, int(self.alignment()), self.palette(), self.isEnabled(), shown, self.foregroundRole()
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


def show_status(pill: QLabel, status: Status, more: bool = False) -> None:
    """
    A status in a pill: its text, its tone as the color, and its tip. `more`: a click opens what it means in full (a
    popover, see `fields.popover`), which ▾ tells; its tip then says only that.
    """
    pill.setText(f"{status.text}  ▾" if more else status.text)
    # the first paragraph shows in the footer while the mouse is on it (see `HoverTips`)
    pill.setToolTip(f"{status.tip.split(chr(10) * 2)[0]}\n\nClick for details." if more else status.tip)
    set_role(pill, status.tone.value, "tone")


_ENTITY_WORDS = re.compile(r"\b(states?|modes?|channels?|pools?|slots?|people|persons?|applications?)\b", re.IGNORECASE)
"""
The words for the things of the configuration, in their colors in the help: people and applications are what the
pools hand out to the slots, so they have the color of the channels. The documentation colors the same words
(docs/javascripts/entities.js): keep the two in line.
"""
_CONTROL_WORDS = re.compile(r"\b(?:Select|Mute|Solo|Rec)\b|\b(?:faders?|encoders?|LCDs?|LED rings?)\b")
"""
The controls of the device, in the color of the text and a heavier weight, apart from the muted help around them
(the hues are taken: states, channels, slots, presence, the accent and the tones).
"""
_ENTITY_CODE = re.compile(r"\[?(state|mode|channel|pool|people|person|apps|devices|present|slots?|controls)\b")
"""
Their sections and paths in `code`, e.g. `[state.gaming]` or `channel.out`, the pools and the condition of presence.
Not `auto`: it is also the value of an override.
"""
_ENTITY_OF = {
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


def _entity(word: str) -> Entity:
    word = word.lower()
    return _ENTITY_OF[word if word in _ENTITY_OF else word.removesuffix("s")]


def help_text(text: str) -> str:
    """
    Help from a docstring, with `code` in a monospace font, the states, channels and slots it is about in their
    colors (see `Entity`): the words, and their sections in `code`; the controls of the device stand out.
    """
    colors = current_colors()

    def colored(match: re.Match[str]) -> str:
        return f'<span style="color: {getattr(colors, _entity(match[1]).value)}">{match[0]}</span>'

    parts: list[str] = []
    for index, part in enumerate(html.escape(part) for part in text.split("`")):
        if not index % 2:
            part = _CONTROL_WORDS.sub(
                lambda match: f'<span style="color: {colors.text}; font-weight: 600">{match[0]}</span>', part
            )
            parts.append(_ENTITY_WORDS.sub(colored, part))
        elif match := _ENTITY_CODE.match(part):
            parts.append(f'<code style="color: {getattr(colors, _entity(match[1]).value)}">{part}</code>')
        else:
            parts.append(f"<code>{part}</code>")
    return "".join(parts)


LEARN_MORE = "Learn more"
WHOLE_DEFAULT = 24
"""The longest default kept on one line: a longer one wraps like the text."""


CHIP_SHARE = 0.14
"""How much of the text color the background of a value in help has, over the card: a chip in both themes."""


def _chip_color() -> str:
    """A solid color (rich text takes no transparency): the card with a little of the text over it."""
    colors = current_colors()
    card, text = QColor(colors.raised), QColor(colors.text)
    mixed = QColor(
        *(round(a + (b - a) * CHIP_SHARE) for a, b in zip(card.getRgb()[:3], text.getRgb()[:3], strict=True))
    )
    return mixed.name()


def help_tail(default: str | None = None, link: str | None = None) -> str:
    """
    The end of a help, on a line of its own under the text: what an unset option takes (a muted DEFAULT and the
    value as a chip) and the link to the documentation, each kept whole where the text wraps.
    """
    colors = current_colors()
    parts: list[str] = []
    if default:
        value = html.escape(default)
        if len(default) <= WHOLE_DEFAULT:
            # kept whole where the text wraps; a longer one wraps rather than run out of the window
            value = value.replace(" ", "&nbsp;")
        parts.append(
            f'<span style="color: {colors.text_muted}; font-size: small; font-weight: 700">DEFAULT</span>&nbsp;'
            f'<code style="background-color: {_chip_color()}; color: {colors.text}">&nbsp;{value}&nbsp;</code>'
        )
    if link:
        parts.append(f'<a href="{html.escape(link)}">{LEARN_MORE.replace(" ", "&nbsp;")}&nbsp;↗</a>')
    # Qt draws an em space narrow: plain spaces that don't break keep the two apart
    return ("&nbsp;" * 5).join(parts)


def help_html(text: str, link: str | None = None, default: str | None = None) -> str:
    """
    Help from a docstring, then on a line of its own what an unset option takes and a link to the documentation (see
    `help_tail`): in the same place under every field, not wherever the text happens to end.
    """
    tail = help_tail(default, link)
    if not text:
        return tail
    # a little apart from the text, so the two don't run together
    return help_text(text) + (f'<div style="margin-top: {Space.XS}px">{tail}</div>' if tail else "")


def help_label(text: str, role: str, link: str | None = None, default: str | None = None) -> QLabel:
    """
    A label with help from a docstring, and a link to the documentation, opened in the browser; always rich text, as
    Qt would show text without tags as it is.
    """
    widget = label("", role, wrap=True)
    widget.setTextFormat(Qt.TextFormat.RichText)
    widget.setOpenExternalLinks(True)
    set_help(widget, text, link, default)
    return widget


_HELP_PROPERTY = "help_source"


def set_help(widget: QLabel, text: str, link: str | None = None, default: str | None = None) -> None:
    """
    Shows help from a docstring (see `help_html`) in `widget`, and keeps it to draw it again in the colors of
    another theme (see `refresh_help`). The same help again does nothing: it would lay out the window again.
    """
    if widget.property(_HELP_PROPERTY) == (text, link, default):
        return
    widget.setProperty(_HELP_PROPERTY, (text, link, default))
    widget.setText(help_html(text, link, default))


def refresh_help(root: QWidget) -> None:
    """Draws the help in `root` (see `set_help`) again, in the colors of the theme applied since."""
    for widget in root.findChildren(QLabel):
        source = widget.property(_HELP_PROPERTY)
        if source is not None:
            widget.setText(help_html(*source))


DOT = 8
"""The size of the dot of a state: filled while it is on, a ring while off."""


def paint_dot(painter: QPainter, center: QPointF, on: bool, color: str) -> None:
    """The dot of a state, drawn rather than a glyph: the font has none, and the fallback's sit below the middle."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.5))
    painter.setBrush(QBrush(QColor(color)) if on else QBrush(Qt.BrushStyle.NoBrush))
    radius = DOT / 2 - 0.75
    painter.drawEllipse(center, radius, radius)
    painter.restore()


DOT_ICON = QSize(DOT + Space.XS, DOT)
"""The size of `dot_icon`: the dot, and room before the text after it."""


def dot_icon(on: bool, color: str, ratio: float) -> QIcon:
    """
    The dot of a state as an icon of `DOT_ICON`, e.g. before the text of a button; `ratio` is the device pixel ratio of
    the widget it is for (`devicePixelRatioF()`), so it is sharp at any scale.
    """
    pixmap = QPixmap(math.ceil(DOT_ICON.width() * ratio), math.ceil(DOT_ICON.height() * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_dot(painter, QPointF(DOT / 2, DOT / 2), on, color)
    painter.end()
    return QIcon(pixmap)


def flat_button(icon: str, tip: str, parent: QWidget | None = None) -> QToolButton:
    button = QToolButton(parent)
    set_icon(button, icon)
    button.setToolTip(tip)
    button.setAutoRaise(True)
    set_role(button, "flat", "variant")
    return button


def with_presets(kind: PresetKind, suggest: Suggest | None) -> Suggest:
    """The presets of a list of names of the kind, and then the suggestions of the sound server."""
    return lambda: preset_suggestions(kind) + (suggest() if suggest is not None else ())
