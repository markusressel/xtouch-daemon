"""
The slots under the drawing of the device: a bar of the states (live, with their overrides), a card per slot with its
stack (the candidates in order, their conditions as chips, a green dot on the one the device shows), and an inspector
for the slot picked and its candidate picked: what it shows, when, the options of its place, its channel and where else
that is used, and the controls of the slot. With no slot picked, an overview of all slots takes the inspector's place.
"""

import dataclasses
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QEvent, QObject, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QMouseEvent, QPainter, QPen, QPixmap, QShortcut, QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.channels import CHANNEL_TYPES, uses
from xtouch_daemon.gui.domain.clipboard import candidates_text, parse_candidates
from xtouch_daemon.gui.domain.demos import GROUPS, group_of
from xtouch_daemon.gui.domain.places import Origin, Source, inherited, inherited_part, origin, place_help
from xtouch_daemon.gui.domain.schema import Kind, Option, look_options
from xtouch_daemon.gui.domain.simulate import Inputs, WhatIf, is_present, presence_tip, state_tip
from xtouch_daemon.gui.domain.slot_stacks import (
    EMPTY,
    Row,
    StepKind,
    choice_groups,
    member_summary,
    place_options,
    pool_kind,
    pool_strip,
    pool_text,
    reasons,
    rows,
    stack_value,
    targets,
    why_steps,
)
from xtouch_daemon.gui.domain.slots_document import Validation
from xtouch_daemon.gui.domain.states import OVERRIDES, ordered
from xtouch_daemon.gui.domain.status import Reason, Status, Tone
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import (
    DOT_ICON,
    dot_icon,
    entity_label,
    flat_button,
    help_label,
    help_text,
    indent_text,
    label,
    set_help,
)
from xtouch_daemon.gui.qt.fields.chips import FlowLayout
from xtouch_daemon.gui.qt.fields.choice import Choice
from xtouch_daemon.gui.qt.fields.condition import ConditionEdit
from xtouch_daemon.gui.qt.fields.depth import scroll_shadows
from xtouch_daemon.gui.qt.fields.meter import meter_row
from xtouch_daemon.gui.qt.fields.option_row import OptionRow, add_groups, align_titles
from xtouch_daemon.gui.qt.fields.popover import Entry, show_popover
from xtouch_daemon.gui.qt.motion import fading, reveal
from xtouch_daemon.gui.qt.pages.base import Audio, Page, Sideways, Stack, button, card, edged, row, scrolled, set_text
from xtouch_daemon.gui.qt.pages.slot_cards import NODE_ICON, StackList, node_icon
from xtouch_daemon.gui.qt.pages.slot_controls import SlotControls
from xtouch_daemon.gui.qt.theme.style import current_colors, current_mode, set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space
from xtouch_daemon.gui.qt.window.splitter import PaneSplitter
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import Request, SetMode, SetOverride, SlotsState, SlotView, Snapshot
from xtouch_daemon.slots.model import APPS, AUTO, BUILT_IN, DEFAULT, DEVICES, PEOPLE
from xtouch_daemon.slots.why import where

SHOWS_HELP = (
    "What the slot shows while this candidate wins: a channel, a pool (`apps`, `people`, `auto`, ...) or `-` for a "
    "dark strip. A pool with none left for the slot leaves it to the candidate below (a pool or `-`)."
)
"""The help under Shows (see Writing help in `AGENTS.md`)."""
WHEN_HELP = (
    "The slot shows this candidate while the condition holds and no candidate above it does. Empty means always. "
    "It takes states, modes, `present`, `and`, `or`, `not` and parentheses, e.g. `call and not gaming`."
)
"""The help under When."""


def _lay_out(window: QWidget) -> None:
    """Places the widgets of `window` now, from the top down, rather than when the event loop gets to it."""
    for layout in [window.layout(), *(widget.layout() for widget in window.findChildren(QWidget))]:
        if layout is not None:
            layout.activate()


def _clear(bar: QLayout) -> None:
    """Removes the widgets of a bar (it has nothing else)."""
    while (item := bar.takeAt(0)) is not None:
        widget = item.widget()
        assert widget is not None
        # off the screen at once: deleted later, it would stay where it was until then
        widget.hide()
        widget.deleteLater()


SIMULATE_TIP = (
    "What the slots would show in other modes and states, with the changes, where the preview shows: in the GUI or on "
    "the device (Esc ends it)"
)


class SlotsPanel(Page):
    simulated = pyqtSignal(arguments=[])
    """Simulate started, changed or ended: the virtual twin runs `what_if` (see `TwinSession`), or ends."""
    slot_picked = pyqtSignal(int, arguments=["slot"])
    """A slot was picked (1 for the leftmost one), 0 for none: the drawing selects its strip."""

    def __init__(
        self,
        editor: Editor,
        audio: Audio,
        snapshot: Callable[[], Snapshot | None],
        request: Callable[[Request], bool],
        show_channel: Callable[[str], None],
        twin_slots: Callable[[], SlotsState | None] = lambda: None,
        simulate_unavailable: Callable[[], Reason | None] = lambda: None,
        shows_twin: Callable[[], bool] = lambda: False,
        show_pool: Callable[[str], None] = lambda _: None,
    ):
        """
        `show_channel` opens a channel on the page Channels, `show_pool` a pool there, `twin_slots` tells the slots of
        the virtual twin of the window (the preview in the GUI), `shows_twin` whether the drawing shows it, and
        `simulate_unavailable` why Simulate can't run.
        """
        super().__init__(editor, audio)
        self.snapshot = snapshot
        self.request = request
        self.show_channel = show_channel
        self.show_pool = show_pool
        self.twin_slots = twin_slots
        self.simulate_unavailable = simulate_unavailable
        self.shows_twin = shows_twin
        self.slot: int | None = None
        """The slot picked (1 for the leftmost one), None for none: then the overview shows instead of the inspector."""
        self.candidate: int | None = None
        """The candidate of the slot the inspector shows, None for none."""
        self.end = False
        """The row of the slot that is no candidate is picked: the dark end of its rail, or `auto` of an empty slot."""
        self.shown_live: object = None
        self.what_if: WhatIf | None = None
        """What Simulate shows, None while the cards show what the daemon tells."""
        self.what_if_start: WhatIf | None = None
        """Where Simulate started: reality, as the daemon told it then (see `WhatIf.of_live`)."""
        self.device_note = label("", "hint")
        self.layout_.setContentsMargins(0, Space.S, 0, 0)
        end = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        end.activated.connect(lambda: self.simulate(None))
        top = QHBoxLayout()
        bars = QHBoxLayout()
        self.state_bar = QHBoxLayout()
        self.state_bar.setSpacing(Space.S)
        self.state_bar_row = row(self.state_bar)
        bars.addWidget(self.state_bar_row)
        bars.addWidget(self.device_note)
        self.device_note.hide()
        bars.addStretch()
        top.addWidget(Sideways(row(bars)), 1)
        self.simulate_button = button("flask-outline", "Simulate")
        set_role(self.simulate_button, "segment", "variant")
        self.simulate_button.setCheckable(True)
        self.simulate_button.setToolTip(SIMULATE_TIP)
        self.simulate_button.clicked.connect(lambda checked: self.simulate(self._now() if checked else None))
        # first: it stays where it is while the what-ifs take the place of the states
        top.insertWidget(0, self.simulate_button)
        top.insertSpacing(1, Space.S)
        self.bar = row(top)
        """Simulate and the states, or the what-ifs: in the row of the window above the page (see `MainWindow`)."""
        self.state_buttons: dict[str, QToolButton] = {}
        cards = QWidget()
        # a click below the cards picks nothing (see `eventFilter`)
        cards.installEventFilter(self)  # pyright: ignore[reportArgumentType]
        self.cards_area = cards
        self.cards = QVBoxLayout(cards)
        self.cards.setSpacing(Space.S)
        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.card_scroll.setWidget(cards)
        scroll_shadows(self.card_scroll)
        self.lists: list[StackList] = []
        self.card_frames: list[QFrame] = []
        self.card_contents: list[tuple[list[Row], int | None, dict[int, str], bool, tuple[str, str] | None] | None] = [
            None
        ] * protocol.STRIPS
        """What each card shows: its candidates, the one the device shows, and why those above it did not win."""
        for slot in range(1, protocol.STRIPS + 1):
            self._card(slot)
        self.cards.addStretch()
        self.inspector, inspector = card()
        crumbs = QHBoxLayout()
        crumbs.setSpacing(Space.XS)
        self.title = label("", "section")
        set_role(self.title, Entity.SLOT.value, "entity")
        crumbs.addWidget(self.title)
        self.crumbs = QHBoxLayout()
        """The candidates of the slot as a path, the one picked highlighted, the one it shows with a dot."""
        self.crumbs.setSpacing(Space.XS)
        crumbs.addLayout(self.crumbs)
        crumbs.addStretch()
        inspector.addWidget(row(crumbs))
        self.shown_crumbs: tuple[object, ...] | None = None
        self.status_box = QFrame()
        """
        What goes on, at the top: why the slot shows what it shows (while the daemon tells it), what the candidate
        shows and where it is now; a bar in the color of how it is doing.
        """
        set_role(self.status_box, "popover_row")
        status = QVBoxLayout(self.status_box)
        status.setContentsMargins(Space.M, Space.S, Space.S, Space.S)
        status.setSpacing(Space.S)
        self.why = QWidget()
        """Why the slot shows what it shows (`xtouch-daemon why <slot>`), a step a line."""
        self.why_rows = QGridLayout(self.why)
        self.why_rows.setContentsMargins(0, 0, 0, 0)
        self.why_rows.setHorizontalSpacing(Space.S)
        self.why_rows.setVerticalSpacing(Space.XS)
        self.why_rows.setColumnStretch(2, 1)
        self.shown_steps: tuple[object, ...] | None = None
        status.addWidget(self.why)
        inspector.addWidget(self.status_box)
        what = QHBoxLayout()
        what.addWidget(label("Shows"))
        self.show_box = Choice()
        self.show_box.setEditable(True)
        self.show_box.setToolTip("A channel, a pool (`auto`) or `-` for nothing")
        self.show_box.activated.connect(lambda _: self._edit_show())
        self.show_box.lineEdit().editingFinished.connect(self._edit_show)  # pyright: ignore[reportOptionalMemberAccess]
        what.addWidget(self.show_box, 1)
        inspector.addWidget(row(what))
        self.show_help = help_label(SHOWS_HELP, "help", docs.guide_link("slots"))
        inspector.addWidget(self.show_help)
        when = QHBoxLayout()
        when.addWidget(label("When"))
        self.when_edit = ConditionEdit()
        self.when_edit.setPlaceholderText("always")
        self.when_edit.editingFinished.connect(self._edit_when)
        when.addWidget(self.when_edit, 1)
        inspector.addWidget(row(when))
        self.when_help = help_label(WHEN_HELP, "help", docs.guide_link("conditions"))
        inspector.addWidget(self.when_help)
        inspector.addWidget(self.problem)
        self.place_header = QWidget()
        """Above the form of the place: its title, and where the parts of what it shows are set."""
        header = QVBoxLayout(self.place_header)
        header.setContentsMargins(0, Space.M, 0, 0)
        header.setSpacing(Space.XS)
        self.place_title = label("", "section")
        header.addWidget(self.place_title)
        parts = QHBoxLayout()
        parts.setSpacing(Space.S)
        self.place_parts = help_label("", "help")
        parts.addWidget(self.place_parts, 1)
        self.channel_button = button("pencil-outline", "Edit the channel")
        """Opens the channel (or the pool) the candidate shows on the page Channels."""
        self.channel_button.clicked.connect(self._edit_origin)
        parts.addWidget(self.channel_button, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(row(parts))
        inspector.addWidget(self.place_header)
        self.place = Stack()
        inspector.addWidget(self.place)
        self.place_origin: Origin | None = None
        """Where the place of the candidate picked takes what it leaves unset."""
        self.place_forms: dict[tuple[str, frozenset[str], bool], tuple[QWidget, list[OptionRow]]] = {}
        """The forms of the options of a place, by strip type and the options it takes: built once, then reused."""
        self.place_rows: list[OptionRow] = []
        """The rows of the form shown."""
        self.channel = label("", "hint", wrap=True)
        """What the candidate shows, and where it is now: as the help (`code`, the colors of states and channels)."""
        self.channel.setTextFormat(Qt.TextFormat.RichText)
        status.addWidget(self.channel)
        self.hint = label("", "hint", wrap=True)
        """What to do next: pick a candidate, or add one."""
        self.hint.setTextFormat(Qt.TextFormat.RichText)
        status.addWidget(self.hint)
        self.slot_controls = SlotControls(editor)
        """The controls of the slot (`[controls]`), whatever it shows."""
        inspector.addWidget(self.slot_controls)
        inspector.addStretch()
        # room between the card and the scroll bar, which sits at the right edge of the window
        self.inspector_scroll = scrolled(_inset(self.inspector))
        self.overview, overview = card()
        """With no slot picked: a line for each slot, what it shows and its problems; a click picks the slot."""
        overview.addWidget(label("Slots", "section"))
        overview.addWidget(label("Pick a slot or a candidate to edit it.", "hint", wrap=True))
        self.overview_lines = QVBoxLayout()
        self.overview_lines.setSpacing(Space.XS)
        overview.addWidget(row(self.overview_lines))
        overview.addStretch()
        self.shown_overview: tuple[object, ...] | None = None
        self.overview_scroll = scrolled(_inset(self.overview))
        self.right = Stack()
        """The inspector while a slot is picked, else the overview."""
        self.right.add(self.inspector_scroll)
        self.right.add(self.overview_scroll)
        self.splitter = PaneSplitter("slots", self.card_scroll, self.right)
        panel = QFrame()
        set_role(panel, "card")
        self.what_if_panel = panel
        self.what_if_bar = FlowLayout(panel, Space.L)
        self.what_if_bar.setContentsMargins(Space.M, Space.S, Space.M, Space.S)
        self.what_if_row = QWidget()
        """What Simulate can change, in groups that wrap: the mode, the states, the channels, the pools."""
        holder = QVBoxLayout(self.what_if_row)
        # its edges those of the panes below: on the left the cards, on the right the card of the right pane
        holder.setContentsMargins(self.cards.contentsMargins().left(), 0, 0, 0)
        holder.addWidget(panel)
        self.what_if_row.hide()
        self.layout_.addWidget(self.what_if_row)
        self.layout_.addWidget(self.splitter, 1)
        edged(self)
        self.what_if_row.setContentsMargins(0, 0, INSET, 0)
        self._show()

    def _card(self, slot: int) -> None:
        frame, layout = card()
        layout.setContentsMargins(Space.M, Space.S, Space.M, Space.S)
        layout.setSpacing(Space.XS)
        header = QHBoxLayout()
        header.addWidget(entity_label(f"Slot {slot}", Entity.SLOT))
        header.addStretch()
        add = flat_button("plus", "Add a candidate (at the end; Ctrl+Up moves it up)")
        add.clicked.connect(lambda: self.add(slot))
        header.addWidget(add)
        remove = flat_button("delete-outline", "Remove the candidate picked (Del)")
        remove.clicked.connect(lambda: self.remove(slot))
        header.addWidget(remove)
        layout.addWidget(row(header))
        stack = StackList()
        stack.currentRowChanged.connect(lambda index: self._picked(slot, index))
        stack.reordered.connect(lambda order, current: self.reorder(slot, order, current))
        layout.addWidget(stack)
        self.lists.append(stack)
        # a click on the card beside its candidates picks the slot alone (see `eventFilter`)
        frame.installEventFilter(self)  # pyright: ignore[reportArgumentType]
        self.card_frames.append(frame)
        self.cards.addWidget(frame)

    # -- showing --------------------------------------------------------------------------------------------------

    def show_document(self, change: Change) -> None:
        if change.scope is Scope.VALUE and change.path[:1] in (("slots",), ("controls",)):
            # an option of the place or of the controls, from a row of the inspector: it shows it already
            self._show_cards()
        else:
            self._show()

    def _show(self) -> None:
        config = self.editor.validation.config
        if self.what_if is not None and config is None:
            self.simulate(None)
        self._show_simulate_button()
        self._show_state_bar()
        self._show_cards()
        self._show_inspector()

    def _show_simulate_button(self) -> None:
        """Simulate needs a file without problems and a daemon with a twin for it; the button says what is missing."""
        config = self.editor.validation.config
        reason = self.simulate_unavailable()
        if config is None:
            tip = "Only for a file without problems"
        elif reason is not None:
            tip = f"{reason.why}\n\n{SIMULATE_TIP}"
        else:
            tip = SIMULATE_TIP
        self.simulate_button.setEnabled((config is not None and reason is None) or self.what_if is not None)
        self.simulate_button.setToolTip(tip)

    def _show_state_bar(self) -> None:
        _clear(self.state_bar)
        self.state_buttons = {}
        for name in ordered(self.document.get(("state",), {})):
            state_button = QToolButton()
            set_role(state_button, Entity.STATE.value, "entity")
            # the label until the daemon tells the state (see `show_live`)
            state_button.setText(str(self.document.get(("state", name, "label")) or name))
            state_button.clicked.connect(lambda _=False, name=name: self._show_state(name))
            self.state_bar.addWidget(state_button)
            self.state_buttons[name] = state_button
        self.shown_live = None
        self.show_live(self.snapshot())

    def _show_cards(self) -> None:
        live = self._views()
        for slot, stack in enumerate(self.lists, start=1):
            stack.blockSignals(True)
            view = live.get(slot)
            candidates = rows(self.document.values, slot)
            shown_candidate = view.candidate if view is not None else None
            member = member_summary(view, self.audio(), self.shown_slots())
            # a pool with nothing to hand out (or no candidate at all): none of them shows, the strip is dark
            dark = view is not None and (view.candidate is None or (view.pool is not None and view.member is None))
            if dark:
                shown_candidate = None
            reached = len(candidates) if dark else shown_candidate
            why = reasons(candidates, reached, view.why if view is not None else (), self.document.values)
            contents = (candidates, shown_candidate, why, dark, member)
            if self.card_contents[slot - 1] != contents:
                # built again only when a candidate, the one shown or a reason changed: every build lays out the card
                self.card_contents[slot - 1] = contents
                stack.fill(candidates, shown_candidate, why, self.document.values, dark, member)
            if slot == self.slot and self.candidate is not None and self.candidate < stack.count():
                stack.setCurrentRow(self.candidate)
            elif slot == self.slot and self.end:
                # gone when the strip shows something again
                self.end = stack.end_row() >= 0
                stack.setCurrentRow(stack.end_row())
            elif slot != self.slot:
                stack.setCurrentRow(-1)
            stack.blockSignals(False)
            problems = self.editor.validation.at("slots", str(slot)) + self.editor.validation.at("controls", str(slot))
            set_role(self.card_frames[slot - 1], bool(problems), "problem")
            set_role(self.card_frames[slot - 1], slot == self.slot, "picked")
            self.card_frames[slot - 1].setToolTip("\n".join(str(problem) for problem in problems))

    def _show_inspector(self) -> None:
        if self.slot is None:
            self.right.show_part(self.overview_scroll)
            self._show_overview()
            return
        self.right.show_part(self.inspector_scroll)
        stack = rows(self.document.values, self.slot)
        if self.candidate is not None and self.candidate >= len(stack):
            self.candidate = len(stack) - 1 if stack else None
        self._show_why()
        self.slot_controls.show_slot(self.slot)
        if not stack:
            text = (
                f"Slot {self.slot} has no candidate: it shows `auto`, the next application that plays or person of "
                "the voice chat. Add a candidate (+ on its card) to show a channel here, e.g. an output."
            )
        elif self.end:
            text = (
                "The strip is dark: none of the candidates has anything to show now. + adds a candidate at the end, "
                "e.g. an output, which is always there."
            )
        elif self.candidate is None:
            text = "Pick a candidate to edit it. The first one whose condition holds is shown; + adds one at the end."
        else:
            text = ""
        set_text(self.hint, _help(text))
        self.hint.setVisible(bool(text))
        self._show_crumbs(stack)
        for widget in (self.show_box, self.when_edit):
            widget.parentWidget().setVisible(self.candidate is not None)  # pyright: ignore[reportOptionalMemberAccess]
        for widget in (self.channel, self.show_help, self.when_help):
            widget.setVisible(self.candidate is not None)
        self.place.setVisible(False)
        self.place_header.setVisible(False)
        self.place_rows = []
        self.place_origin = None
        if self.candidate is None:
            set_text(self.title, f"Slot {self.slot}")
            self.show_problems(self.editor.validation)
            return
        candidate = stack[self.candidate]
        set_text(self.title, f"Slot {self.slot}")
        self.show_box.blockSignals(True)
        self.show_box.clear()
        for title, names in choice_groups(self.document.values):
            if title and names:
                # a title of a group: it can't be picked
                self.show_box.addItem(title)
                model = self.show_box.model()
                assert isinstance(model, QStandardItemModel)
                header = model.item(self.show_box.count() - 1)
                assert header is not None
                header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.show_box.addItems(names)
        self.show_box.setCurrentText(candidate.show)
        self.show_box.blockSignals(False)
        self.when_edit.set_names([*self.document.values.get("state", {}), DEFAULT], targets(self.document.values))
        self.when_edit.setText(candidate.when)
        channel = self.document.get(("channel", candidate.show))
        if isinstance(channel, dict):
            kind = CHANNEL_TYPES.get(str(channel.get("type")))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            elsewhere = [use for use in uses(self.document.values, candidate.show) if use != f"slot {self.slot}"]
            text = (
                f"Channel {candidate.show} ({kind.title if kind else '?'}). "
                + (f"Also used in: {', '.join(elsewhere)}." if elsewhere else "Used nowhere else.")
                + self._channel_why(candidate.show)
            )
            set_text(self.channel, _help(text))
            strip = kind.strip if kind else None
        else:
            text = (
                "Nothing: the strip is dark."
                if candidate.show == EMPTY
                else pool_text(self.document.values, candidate.show) + self._channel_why(candidate.show)
            )
            set_text(self.channel, _help(text))
            strip = pool_strip(candidate.show, self.document.values)
        self.place_origin = origin(self.document.values, candidate.show)
        if self.place_origin is not None:
            self._show_place_header(self.place_origin)
        # the channels of a pool of channels bring their own look: its place has none
        if strip is not None and self.place_origin is not None and self.place_origin.source is not Source.CHANNELS:
            # a pool of applications of your own has no `pick` encoder
            own = pool_kind(self.document.values, candidate.show) == "apps" and candidate.show not in BUILT_IN
            form, self.place_rows = self._place_form(
                strip, place_options(candidate.show, self.document.values), pick=not own
            )
            self._fit_place_rows(self.place_origin)
            self.place.show_part(form)
            self.place.setVisible(True)
            self._load_rows(self.place_rows)
        self.show_problems(self.editor.validation)

    def _channel_why(self, name: str) -> str:
        slots = self.shown_slots()
        if slots is None:
            return ""
        # the sentence before it names the channel or pool already, the box says whether it is now or what if
        now = where(slots, name)
        return f"\n{now[:1].upper()}{now[1:]}."

    def _show_why(self) -> None:
        """
        Why the slot shows what it shows, a step a line: ✗ a candidate passed over and why, → what it shows (○ dark),
        ● held. The bar of the box: green while it shows something, neutral while dark or while nothing tells.
        """
        if self.slot is None:
            return
        live = self.shown_slots()
        view = self._views().get(self.slot) if live is not None else None
        steps = why_steps(view.why) if view is not None else ()
        # the colors of the marks are those of the theme: a new one draws them again
        key = (live is not None, self.what_if is not None, self.shows_twin(), steps, current_mode())
        if key == self.shown_steps:
            return
        self.shown_steps = key
        while (item := self.why_rows.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                widget.hide()
                widget.deleteLater()
        self.why.setVisible(live is not None)
        if live is None:
            set_role(self.status_box, Tone.NEUTRAL.value, "tone")
            return
        heading = "What if" if self.what_if is not None else "Preview" if self.shows_twin() else "Now"
        self.why_rows.addWidget(label(heading, "hint"), 0, 0, 1, 3)
        if not steps:
            self.why_rows.addWidget(label(f"The daemon tells nothing about slot {self.slot}.", "hint"), 1, 0, 1, 3)
        colors = current_colors()
        marks = {
            StepKind.PASSED: ("✗", colors.text_muted),
            StepKind.HELD: ("●", colors.tone_warn),
            StepKind.SHOWN: ("→", colors.tone_good),
            StepKind.DARK: ("○", colors.text_muted),
        }
        for line, step in enumerate(steps, start=1):
            mark, color = marks[step.kind]
            sign = label(mark)
            sign.setStyleSheet(f"color: {color}; font-weight: bold;")
            self.why_rows.addWidget(sign, line, 0, Qt.AlignmentFlag.AlignTop)
            subject = label(step.subject)
            final = step.kind in (StepKind.SHOWN, StepKind.DARK)
            subject.setStyleSheet("font-weight: bold;" if final else f"color: {colors.text_muted};")
            self.why_rows.addWidget(subject, line, 1, Qt.AlignmentFlag.AlignTop)
            if step.reason:
                reason = label("", "hint", wrap=True)
                reason.setTextFormat(Qt.TextFormat.RichText)
                reason.setText(help_text(step.reason))
                self.why_rows.addWidget(reason, line, 2)
        shows = bool(steps) and steps[-1].kind == StepKind.SHOWN
        set_role(self.status_box, (Tone.GOOD if shows else Tone.NEUTRAL).value, "tone")

    def _show_crumbs(self, stack: list[Row]) -> None:
        """
        `Slot 3 › 1 games › 2 apps › 3 people`: the candidates in their order, the one picked highlighted, the one
        the slot shows with a dot; a click picks one.
        """
        view = self._views().get(self._slot)
        shown = view.candidate if view is not None else None
        # the candidate it came to, which has nothing for it: the strip is dark
        dark = view is not None and view.pool is not None and view.member is None
        # the end of the rail, while the strip is dark (see `StackList.fill`)
        end = stack and self.lists[self._slot - 1].end_row() >= 0
        # the theme too: the dot is painted in its color
        key = (self.slot, tuple((row.show, row.when) for row in stack), self.candidate, shown, dark, end, self.end)
        key += (current_mode(),)
        if key == self.shown_crumbs:
            return
        self.shown_crumbs = key
        _clear(self.crumbs)
        for index, candidate in enumerate(stack):
            self.crumbs.addWidget(label("›", "hint"))
            crumb = QToolButton()
            set_role(crumb, Entity.CHANNEL.value, "entity")
            _mark(crumb, ("○" if dark else "●") if index == shown else "")
            crumb.setText(f"{index + 1}  {candidate.show}")
            crumb.setCheckable(True)
            crumb.setChecked(index == self.candidate)
            crumb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            when = f"when {candidate.when}" if candidate.when else "always"
            more = (
                ("; the slot came to it, and it has none left" if dark else "; the slot shows it")
                if index == shown
                else ""
            )
            crumb.setToolTip(f"Candidate {index + 1} of {len(stack)}: {when} → {candidate.show}{more}")
            crumb.clicked.connect(lambda checked, index=index: self._crumb_clicked(index, checked))
            self.crumbs.addWidget(crumb)
        if end:
            self.crumbs.addWidget(label("›", "hint"))
            crumb = QToolButton()
            # what the slot shows, like a candidate: nothing
            set_role(crumb, Entity.CHANNEL.value, "entity")
            _mark(crumb, "●")
            crumb.setText("dark")
            crumb.setCheckable(True)
            crumb.setChecked(self.end)
            crumb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            crumb.setToolTip("None of the candidates has anything to show now, so the strip is dark")
            crumb.clicked.connect(lambda checked: self._crumb_clicked(self.lists[self._slot - 1].end_row(), checked))
            self.crumbs.addWidget(crumb)

    def _crumb_clicked(self, row: int, checked: bool) -> None:
        """A crumb picks its row of the card; the one picked, clicked again, picks the slot alone."""
        if checked:
            self.lists[self._slot - 1].setCurrentRow(row)
        else:
            self.pick_slot(self._slot)

    def _place_form(self, strip: str, allowed: frozenset[str], pick: bool = True) -> tuple[QWidget, list[OptionRow]]:
        """The form of the options of a place of `strip`, for the candidate picked; `pick`: the encoder may pick."""
        key = (strip, allowed, pick)
        if key not in self.place_forms:
            form = QWidget()
            layout = QVBoxLayout(form)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(Space.XS)
            # at a place every option is optional: the channel has its own
            option_rows: list[OptionRow] = []
            groups: dict[str, list[QWidget]] = {}
            for option in look_options(strip, allowed):
                if option.name == "meter_point":
                    # one choice with `meter`
                    continue
                # no default of its own: unset, it is as where the place takes it from (see `_fit_place_rows`)
                option = dataclasses.replace(option, default=None)
                if option.name == "meter":
                    option_row = self._place_meter_row(pick)
                elif option.kind == Kind.BUTTON:
                    option_row = self._place_button_row(option)
                else:
                    option_row = self._place_row(
                        dataclasses.replace(option, choices=tuple(c for c in option.choices if pick or c != "pick")),
                        pick,
                    )
                option_rows.append(option_row)
                groups.setdefault(group_of(option.name), []).append(option_row)
            titles = dict(GROUPS)
            add_groups(layout, [(titles[group], groups[group]) for group, _ in GROUPS if group in groups])
            align_titles(option_rows)
            self.place_forms[key] = form, option_rows
        return self.place_forms[key]

    def _place_option(self, name: str) -> Any:
        """An option of the place of the candidate picked."""
        assert self.candidate is not None
        return rows(self.document.values, self._slot)[self.candidate].options.get(name)

    def _set_place_option(self, name: str, value: Any) -> None:
        """Sets an option of the place of the candidate picked (None: removes it)."""
        assert self.candidate is not None
        stack = rows(self.document.values, self._slot)
        candidate = stack[self.candidate]
        options = {key: each for key, each in candidate.options.items() if key != name}
        if value is not None:
            options[name] = value
        stack[self.candidate] = Row(candidate.show, candidate.when, options)
        self._put(self._slot, stack)

    def _place_edited(self, option_row: OptionRow, name: str) -> OptionRow:
        def edited() -> None:
            assert self.candidate is not None
            self.editor.edited(Change(Scope.VALUE, ("slots", str(self.slot), self.candidate, name)))

        option_row.edited.connect(edited)
        return option_row

    def _inherited(self, name: str, pick: bool = True) -> str:
        """What an option the place of the candidate picked leaves unset takes, as a word ("" where it is not known)."""
        place = self.place_origin
        return (inherited(place, name, pick) if place is not None else None) or ""

    def _place_row(self, option: Option, pick: bool = True) -> OptionRow:
        """A row for an option of the place of the candidate picked, whichever it is when it is shown or edited."""
        name = option.name
        option_row = OptionRow(
            option,
            lambda: self._place_option(name),
            lambda value: self._set_place_option(name, value),
            placeholder=lambda: self._inherited(name, pick),
        )
        return self._place_edited(option_row, name)

    def _place_meter_row(self, pick: bool) -> OptionRow:
        """`meter` and `meter_point` of the place as one choice; unset, those of the channel or the pool."""
        option_row = meter_row(self._place_option, self._set_place_option, lambda: self._inherited("meter", pick))
        return self._place_edited(option_row, "meter")

    def _place_button_row(self, option: Option) -> OptionRow:
        """
        A button of the place: only what its LED shows (and for Select whether it does something); what a button does
        belongs to the channel. Unset, as on the channel or in the pool.
        """
        parts = ("press", "led") if option.name == "select" else ("led",)
        option = dataclasses.replace(option, columns=tuple(c for c in option.columns if c.name in parts))
        option_row = self._place_row(option)
        name = option.name

        def placeholder(part: str) -> str:
            place = self.place_origin
            assert place is not None
            value = inherited_part(place, name, part)
            return f"{place.prefix}: {value}" if value else place.prefix

        option_row.buttons.inherited = placeholder
        return option_row

    def _show_place_header(self, place: Origin) -> None:
        """The title of the form of the place, and where the parts of what it shows are set, with a way there."""
        set_text(self.place_title, f"Look in slot {self.slot}")
        set_help(self.place_parts, place.parts)
        self.channel_button.setText("Edit the channel" if place.source is Source.CHANNEL else "Edit the pool")
        self.place_header.setVisible(True)

    def _fit_place_rows(self, place: Origin) -> None:
        """The rows of a form of a place, shared by what shows on a strip of a type: their help for this one."""
        for option_row in self.place_rows:
            option_row.inherited = place.prefix
            name = option_row.option.name
            # a switch and the colors show the value they take unset as if it were set: the help says it too
            value = self._inherited(name) if option_row.option.kind in (Kind.SWITCH, Kind.COLOR) else None
            set_help(option_row.help, place_help(place, name, self._slot, value), docs.guide_link("slots"))
            option_row.help.show()
            option_row.reset.setToolTip(place.back)

    def _edit_origin(self) -> None:
        """Opens the channel or the pool the candidate picked shows on the page Channels."""
        place = self.place_origin
        assert place is not None
        if place.source is Source.CHANNEL:
            self.show_channel(place.show)
        else:
            self.show_pool(place.show)

    def show_problems(self, validation: Validation) -> None:
        self.slot_controls.show_problems(validation)
        if self.slot is None:
            self._show_overview()
            return
        if self.candidate is None:
            self._show_rest([str(problem) for problem in validation.at("slots", str(self.slot))])
            return
        here = validation.at("slots", str(self.slot), self.candidate)
        names = {option_row.option.name for option_row in self.place_rows}
        self._show_rest([problem.message for problem in here if problem.path[3:4] not in [(name,) for name in names]])
        for option_row in self.place_rows:
            option_row.show_problems(validation.at("slots", str(self.slot), self.candidate, option_row.option.name))

    def shown_slots(self, snapshot: Snapshot | None = None) -> SlotsState | None:
        """What the cards show: the slots of what the drawing shows, the twin's or the device's."""
        snapshot = snapshot if snapshot is not None else self.snapshot()
        if self.shows_twin():
            return self.twin_slots()
        return snapshot.slots if snapshot is not None else None

    def show_place(self, note: str) -> None:
        """Where Simulate shows (the place of the preview): the note in its bar."""
        if note != self.device_note.text():
            # the twin's slots instead of the device's, or back
            self.shown_live = None
        self.device_note.setText(note)

    def show_live(self, snapshot: Snapshot | None) -> None:
        """
        The states in the bar (the device's: the bar picks its mode and overrides), and the dot on the candidates the
        drawing shows (the device's, or the preview's), when they changed.
        """
        self._show_simulate_button()
        slots = self.shown_slots(snapshot)
        real = snapshot.slots if snapshot is not None else None
        live = (
            (
                *((state.name, state.value, state.override) for state in real.states),
                real.mode_pick,
            )
            if real is not None
            else None,
            tuple(view.candidate for view in slots.slots) if slots is not None else None,
        )
        if live == self.shown_live:
            return
        self.shown_live = live
        picked = real.mode_pick if real is not None else None
        states = {state.name: state for state in real.states} if real is not None else {}
        hue = getattr(current_colors(), Entity.STATE)
        for name, state_button in self.state_buttons.items():
            state = states.get(name)
            override = "" if state is None or state.override == "auto" else f" ({state.override})"
            if picked == name:
                override = " (picked)"
            # the dot (on or off) once the daemon tells the state
            state_button.setProperty("on", None if state is None else state.value)
            ratio = state_button.devicePixelRatioF()
            state_button.setIcon(QIcon() if state is None else dot_icon(state.value, hue, ratio))
            state_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            state_button.setIconSize(DOT_ICON)
            state_button.setText(f"{self.document.get(('state', name, 'label')) or name}{override}  ▾")
            tip = f"{name}: {state.source or 'off'}" if state is not None else name
            state_button.setToolTip(f"{tip}\n\nClick for its override, or to simulate it the other way.")
        self._show_cards()
        self._show_why()
        if self.slot is None:
            self._show_overview()
        else:
            # the dot on the candidate shown, and the end of the rail while the strip is dark
            self._show_crumbs(rows(self.document.values, self.slot))

    def _views(self) -> dict[int, SlotView]:
        slots = self.shown_slots()
        return {view.slot: view for view in slots.slots} if slots is not None else {}

    # -- simulate ------------------------------------------------------------------------------------------------

    def _now(self) -> WhatIf:
        """Reality as a what-if, as the daemon tells it: where Simulate starts."""
        snapshot = self.snapshot()
        return WhatIf.of_live(snapshot.slots if snapshot is not None else None)

    def simulate(self, what_if: WhatIf | None) -> None:
        """Shows what the slots would show in `what_if`; None goes back to what the daemon tells."""
        config = self.editor.validation.config
        if config is None or (what_if is not None and self.simulate_unavailable() is not None):
            what_if = None
        if what_if is None or self.what_if is None:
            # where it starts: reality, as the daemon tells it when it opens
            self.what_if_start = self._now() if what_if is not None else None
        self.what_if = what_if
        self.simulate_button.setChecked(what_if is not None)
        # nothing drawn until all is in its place: else the rows would show for a moment at their old heights, and the
        # what-ifs before they wrap
        window = self.window()
        window.setUpdatesEnabled(False)
        try:
            if config is not None and what_if is not None:
                # a change of a what-if fades; the bar that opens grows (see `gui/qt/motion.py`)
                with fading(self.what_if_panel):
                    self._show_what_if_bar(Inputs.of(config.slots), what_if)
            reveal(self.state_bar_row, what_if is None)
            reveal(self.what_if_row, what_if is not None)
            reveal(self.device_note, what_if is not None)
            self.shown_live = None
            self.show_live(self.snapshot())
            _lay_out(window)
        finally:
            window.setUpdatesEnabled(True)
        self.simulated.emit()

    def _show_what_if_bar(self, inputs: Inputs, what_if: WhatIf) -> None:
        _clear(self.what_if_bar)
        mode = Choice()
        # as wide as its longest mode
        set_role(mode, "true", "narrow")
        mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        mode.addItems(inputs.modes)
        mode.setCurrentText(what_if.mode)
        mode.setToolTip("The mode")
        mode.currentTextChanged.connect(lambda name: self.simulate(dataclasses.replace(what_if, mode=name)))
        self._what_if_group("Mode", [mode])
        if inputs.states:
            self._what_if_group("States", [self._toggle(what_if, name, False) for name in inputs.states])
        if inputs.channels:
            self._what_if_group("Channels", [self._toggle(what_if, name, True) for name in inputs.channels])
        # the built-in pools by how many members they have (0: empty), the others present or absent
        counts: dict[str, tuple[int, str, Callable[[int], WhatIf]]] = {
            PEOPLE: (what_if.people, "people in the voice chat", lambda n: what_if.counted(people=n)),
            APPS: (what_if.apps, "applications that play", lambda n: what_if.counted(apps=n)),
        }
        if DEVICES in inputs.presence:
            counts[DEVICES] = (what_if.devices, "outputs without a channel", lambda n: what_if.counted(devices=n))
        pools: list[QWidget] = [self._count(name, *counts[name]) for name in counts]
        pools += [self._toggle(what_if, name, True) for name in inputs.presence if name in inputs.pools - counts.keys()]
        self._what_if_group("Pools", pools)

    def _what_if_group(self, title: str, widgets: list[QWidget]) -> None:
        """A group of the what-ifs: its title over its controls."""
        group = QWidget()
        column = QVBoxLayout(group)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(Space.XS)
        column.addWidget(label(title.upper(), "group"))
        line = QHBoxLayout()
        line.setSpacing(Space.S)
        for widget in widgets:
            line.addWidget(widget)
        column.addLayout(line)
        self.what_if_bar.addWidget(group)
        # shown now: Qt would show it only once the event loop gets to it, so the bar would first be laid out without it
        group.show()

    def _count(self, name: str, value: int, what: str, counted: Callable[[int], WhatIf]) -> QWidget:
        """A built-in pool and how many members it has: a dot (● with members) and its name, and the number."""
        pool = QWidget()
        line = QHBoxLayout(pool)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(Space.XS)
        dot = QLabel()
        ratio = dot.devicePixelRatioF()
        dot.setPixmap(node_icon(bool(value), current_colors().text_muted, ratio).pixmap(NODE_ICON, ratio))
        dot.setProperty("lit", bool(value))
        line.addWidget(dot)
        line.addWidget(label(name))
        count = QSpinBox()
        indent_text(count)
        count.setRange(0, 2 * protocol.STRIPS)
        count.setValue(value)
        # a number of two digits: narrower than the spin boxes of the forms
        set_role(count, "true", "narrow")
        count.setFixedWidth(Space.XXL * 2 + Space.S)
        count.setToolTip(f"How many {what}; 0: the pool {name} is empty")
        count.valueChanged.connect(lambda n: self.simulate(counted(n)))
        line.addWidget(count)
        pool.setObjectName(name)
        return pool

    def _toggle(self, what_if: WhatIf, name: str, flip: bool) -> QPushButton:
        """
        A state (on or off), or with `flip` the presence of a channel or pool: a dot says which it is in the what-if,
        a frame in the accent color that it differs from reality (checked).
        """
        flipped = name in (what_if.flipped if flip else what_if.on)
        lit = is_present(name, flipped) if flip else flipped
        toggle = QPushButton(name)
        set_role(toggle, "what-if", "variant")
        toggle.setCheckable(True)
        toggle.setChecked(what_if.differs(self.what_if_start or WhatIf(), name, flip))
        # the node of the candidates on the cards: green and filled while on, a ring while off
        toggle.setIcon(node_icon(lit, current_colors().text_muted, toggle.devicePixelRatioF()))
        toggle.setIconSize(NODE_ICON)
        toggle.setProperty("lit", lit)
        toggle.setToolTip(presence_tip(name, flipped) if flip else state_tip(name, flipped))
        toggle.clicked.connect(lambda _=False: self.simulate(what_if.toggled(name, flip)))
        return toggle

    # -- picking --------------------------------------------------------------------------------------------------

    def select_slot(self, slot: int) -> None:
        """
        A strip of the drawing was clicked: its card, with the candidate the device shows, or the end of the rail
        while the strip is dark.
        """
        view = self._views().get(slot)
        count = len(rows(self.document.values, slot))
        candidate = view.candidate if view is not None and view.candidate is not None else 0 if count else None
        stack = self.lists[slot - 1]
        end = stack.end_row() >= 0
        self._pick(slot, None if end else candidate, end)
        stack.setFocus()
        self.card_scroll.ensureWidgetVisible(self.card_frames[slot - 1])
        # up and down only: a card wider than the pane would scroll to its right end, cutting off its conditions
        self.card_scroll.horizontalScrollBar().setValue(0)  # pyright: ignore[reportOptionalMemberAccess]

    def pick_slot(self, slot: int) -> None:
        """The card of a slot was clicked beside its candidates: the slot alone, with no candidate."""
        self._pick(slot, None)
        # the keys of the menu Edit go to its card (paste); as a click, the list doesn't pick its first candidate
        self.lists[slot - 1].setFocus(Qt.FocusReason.MouseFocusReason)

    def unpick(self) -> None:
        """Nothing picked: no card is outlined, none has a row highlighted, the overview shows."""
        self._pick(None, None)

    def _pick(self, slot: int | None, candidate: int | None, end: bool = False) -> None:
        self.slot, self.candidate, self.end = slot, candidate, end
        for each in self.lists:
            each.blockSignals(True)
            each.clearSelection()
            each.setCurrentRow(-1)
            each.blockSignals(False)
        self._show_cards()
        self._show_inspector()
        self.slot_picked.emit(slot or 0)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        """A click on a card beside its candidates picks its slot alone; one below the cards picks nothing."""
        if a1 is not None and a1.type() == QEvent.Type.MouseButtonPress:
            assert isinstance(a1, QMouseEvent)
            if a1.button() == Qt.MouseButton.LeftButton:
                if a0 in self.card_frames:
                    self.pick_slot(self.card_frames.index(a0) + 1)  # pyright: ignore[reportArgumentType]
                    return True
                if a0 is self.cards_area:
                    self.unpick()
                    return True
        return False

    def _show_overview(self) -> None:
        """A line for each slot: what it shows now (while the daemon tells it), its candidates and its problems."""
        live = self.shown_slots()
        views = self._views()
        lines: list[tuple[int, str, Tone, str]] = []
        for slot in range(1, protocol.STRIPS + 1):
            count = len(rows(self.document.values, slot))
            problems = len(
                self.editor.validation.at("slots", str(slot)) + self.editor.validation.at("controls", str(slot))
            )
            candidates = f"{count} candidate{'s' if count != 1 else ''}" if count else "no candidate: `auto`"
            parts = [candidates]
            tone = Tone.NEUTRAL
            view = views.get(slot) if live is not None else None
            steps = why_steps(view.why) if view is not None else ()
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
            lines.append((slot, text[:1].upper() + text[1:], tone, current_mode()))
        key = tuple(lines)
        if key == self.shown_overview:
            return
        self.shown_overview = key
        while (item := self.overview_lines.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                widget.hide()
                widget.deleteLater()
        for slot, text, tone, _ in lines:
            self.overview_lines.addWidget(_OverviewLine(slot, text, tone, lambda slot=slot: self.pick_slot(slot)))

    def _picked(self, slot: int, index: int) -> None:
        if index < 0:
            return
        for other, stack in enumerate(self.lists, start=1):
            if other != slot:
                stack.blockSignals(True)
                stack.clearSelection()
                stack.setCurrentRow(-1)
                stack.blockSignals(False)
        end = index == self.lists[slot - 1].end_row()
        self.slot, self.candidate, self.end = slot, None if end else index, end
        self._show_cards()
        self._show_inspector()
        self.slot_picked.emit(slot)

    @property
    def _slot(self) -> int:
        """The slot picked, where only a slot picked gets: the inspector, the candidate picked."""
        assert self.slot is not None
        return self.slot

    def _candidate_row(self) -> Row:
        assert self.candidate is not None
        return rows(self.document.values, self._slot)[self.candidate]

    # -- editing --------------------------------------------------------------------------------------------------

    def _put(self, slot: int, stack: list[Row]) -> None:
        value = stack_value(stack)
        if value is None:
            self.document.unset(("slots", str(slot)))
        else:
            self.document.set(("slots", str(slot)), value)

    def _write(self, slot: int, stack: list[Row], candidate: int | None) -> None:
        self._put(slot, stack)
        self.slot, self.candidate, self.end = slot, candidate, False
        self.editor.edited(Change(Scope.SLOTS, ("slots", str(slot))))
        self.slot_picked.emit(slot)

    def add(self, slot: int) -> None:
        """A new candidate at the end of the stack: `auto` (Ctrl+Up moves it up)."""
        stack = rows(self.document.values, slot)
        stack.append(Row(AUTO))
        self._write(slot, stack, len(stack) - 1)

    def remove(self, slot: int) -> None:
        """Removes the candidate picked in the slot (the last one when none is)."""
        stack = rows(self.document.values, slot)
        if not stack:
            return
        index = self.candidate if slot == self.slot and self.candidate is not None else len(stack) - 1
        del stack[index]
        self._write(slot, stack, min(index, len(stack) - 1) if stack else None)

    def reorder(self, slot: int, order: list[int], current: int) -> None:
        stack = rows(self.document.values, slot)
        self._write(slot, [stack[index] for index in order], current)

    def _insert(self, slot: int, candidates: list[Row]) -> int:
        """Puts candidates after the one picked in the slot (at the end when none is), picks the first; how many."""
        if not candidates:
            return 0
        stack = rows(self.document.values, slot)
        index = self.candidate + 1 if slot == self.slot and self.candidate is not None else len(stack)
        stack[index:index] = candidates
        self._write(slot, stack, index)
        return len(candidates)

    # -- the entries, for the menu Edit ---------------------------------------------------------------------------

    ENTRIES = "candidates"

    def _focused_slot(self) -> int | None:
        """The slot whose card has the focus, None for none."""
        return next((slot for slot, stack in enumerate(self.lists, start=1) if stack.hasFocus()), None)

    def _focused_candidate(self) -> Row | None:
        """The candidate picked in the card that has the focus, None for none."""
        if self._focused_slot() != self.slot or self.candidate is None:
            return None
        return self._candidate_row()

    def entries_focused(self) -> bool:
        return self._focused_slot() is not None

    def copy_entry(self) -> str | None:
        candidate = self._focused_candidate()
        return candidates_text([candidate]) if candidate is not None else None

    def paste_entries(self, text: str) -> int:
        slot = self._focused_slot()
        return self._insert(slot, parse_candidates(text)) if slot is not None else 0

    def duplicate_entry(self) -> bool:
        candidate = self._focused_candidate()
        return candidate is not None and self._insert(self._slot, [candidate]) > 0

    def remove_entry(self) -> bool:
        if self._focused_candidate() is None:
            return False
        self.remove(self._slot)
        return True

    def rename_entry(self) -> bool:
        """A candidate has no id: the focus goes to what it shows."""
        if self._focused_candidate() is None:
            return False
        self.show_box.setFocus()
        self.show_box.lineEdit().selectAll()  # pyright: ignore[reportOptionalMemberAccess]
        return True

    def _edit_show(self) -> None:
        candidate = self._candidate_row()
        show = self.show_box.currentText().strip()
        if show and show != candidate.show:
            self._replace(Row(show, candidate.when, candidate.options))

    def _edit_when(self) -> None:
        candidate = self._candidate_row()
        when = self.when_edit.text().strip()
        if when != candidate.when:
            self._replace(Row(candidate.show, when, candidate.options))

    def _replace(self, candidate: Row) -> None:
        assert self.candidate is not None
        stack = rows(self.document.values, self._slot)
        # options that the new place does not take go
        allowed = place_options(candidate.show, self.document.values)
        stack[self.candidate] = Row(
            candidate.show, candidate.when, {key: value for key, value in candidate.options.items() if key in allowed}
        )
        self._write(self._slot, stack, self.candidate)

    def _show_state(self, name: str) -> None:
        """
        The state `name` as the daemon tells it, its override (real: the device and Home Assistant follow it) and
        what the slots would show with it the other way (Simulate: nothing changes).
        """
        snapshot = self.snapshot()
        slots = snapshot.slots if snapshot is not None else None
        state = next((state for state in slots.states if state.name == name), None) if slots is not None else None
        anchor = self.state_buttons[name]
        if slots is None or state is None:
            unknown = Entry("", text="The daemon doesn't tell this state yet.")
            show_popover(anchor, name, [unknown])
            return
        value = Status("on", Tone.GOOD) if state.value else Status("off", Tone.NEUTRAL)
        why = state.source or "none of its sources is on"
        entries = [Entry("", value, f"{why[:1].upper()}{why[1:]}.")]
        if state.mode:
            picked = slots.mode_pick == name
            override = Status("picked by hand", Tone.WARN) if picked else Status("by the rules", Tone.NEUTRAL)
            actions = (("Back to the rules", lambda: self.override(name, "auto")),) if picked else ()
            if slots.mode != name:
                actions += ((f"Pick {name}", lambda: self.override(name, "on")),)
            text = "Real: the device and Home Assistant follow a mode picked by hand until the rules want another one."
        else:
            override = Status(state.override, Tone.NEUTRAL if state.override == "auto" else Tone.WARN)
            actions = tuple(
                (
                    f"Override: {choice}" if choice != "auto" else "Back to auto",
                    lambda choice=choice: self.override(name, choice),
                )
                for choice in OVERRIDES
                if choice != state.override
            )
            text = "Real: the device and Home Assistant follow an override until it is back on `auto`."
        entries.append(Entry("Override", override, text, actions))
        what_if = WhatIf.of_live(slots)
        if state.mode:
            mode = DEFAULT if slots.mode == name else name
            what_if = dataclasses.replace(what_if, mode=mode)
            simulate = "Simulate no mode" if mode == DEFAULT else f"Simulate {name} as the mode"
        else:
            what_if = what_if.toggled(name, flip=False)
            simulate = f"Simulate it {'off' if state.value else 'on'}"
        entries.append(
            Entry(
                "Simulate",
                text="What the slots would show with it the other way, without changing anything.",
                actions=((simulate, lambda: self.simulate(what_if)),),
            )
        )
        show_popover(anchor, name, entries)

    def override(self, name: str, value: str) -> None:
        """Asks the daemon to override a state, or to pick a mode (`auto`: the rules decide again)."""
        if self.document.get(("state", name, "mode")):
            self.request(SetMode(name if value == "on" else "auto"))
        else:
            self.request(SetOverride(name, value))


class _OverviewLine(QFrame):
    """A slot in the overview: its name, what it shows and its problems; a bar in the color of how it is doing."""

    def __init__(self, slot: int, text: str, tone: Tone, picked: Callable[[], None]) -> None:
        super().__init__()
        self.picked = picked
        set_role(self, "popover_row")
        set_role(self, tone.value, "tone")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Pick slot {slot}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(Space.M, Space.XS, Space.S, Space.XS)
        layout.setSpacing(Space.S)
        layout.addWidget(entity_label(f"Slot {slot}", Entity.SLOT))
        description = label("", "hint", wrap=True)
        description.setTextFormat(Qt.TextFormat.RichText)
        description.setText(help_text(text))
        layout.addWidget(description, 1)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        assert a0 is not None
        if a0.button() == Qt.MouseButton.LeftButton:
            self.picked()


INSET = Space.L
"""Room on the right of the card of the right pane, for its scroll bar."""


def _inset(widget: QWidget) -> QWidget:
    """`widget` with room on its right for the scroll bar of its pane (`INSET`)."""
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, INSET, 0)
    layout.addWidget(widget)
    return holder


def _help(text: str) -> str:
    """`text` as the help shows it (see `help_text`), its lines as lines."""
    return "<br>".join(help_text(line) for line in text.split("\n"))


def _mark(crumb: QToolButton, mark: str) -> None:
    """
    The dot of a crumb: ● what the slot shows, ○ where it came to and has nothing; "" for none. A painted icon, not a
    character: the button centers an icon on its text, a font puts a ● wherever its glyph sits.
    """
    crumb.setProperty("mark", mark)
    if not mark:
        return
    metrics = crumb.fontMetrics()
    size = metrics.height()
    diameter = round(size * 0.45)
    ratio = crumb.devicePixelRatioF()
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(current_colors().text)
    circle = QRectF((size - diameter) / 2, (size - diameter) / 2, diameter, diameter)
    if mark == "●":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
    else:
        painter.setPen(QPen(color, 1.2))
        circle.adjust(0.6, 0.6, -0.6, -0.6)
    painter.drawEllipse(circle)
    painter.end()
    crumb.setIcon(QIcon(pixmap))
    crumb.setIconSize(QSize(size, size))
    crumb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
