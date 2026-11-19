"""
The slots under the drawing of the device: a bar of the states (live, with their overrides), a card per slot with its
stack (the candidates in order, their conditions as chips, a green dot on the one the device shows), and an inspector
for the candidate picked: what it shows, when, the options of its place, its channel and where else that is used, and
the controls of the slot.
"""

import dataclasses
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut, QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.config.values import default_encoder
from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.channels import CHANNEL_TYPES, uses
from xtouch_daemon.gui.domain.demos import GROUPS, group_of
from xtouch_daemon.gui.domain.schema import Kind, Option, look_options
from xtouch_daemon.gui.domain.simulate import Inputs, WhatIf, presence_text
from xtouch_daemon.gui.domain.slot_stacks import (
    EMPTY,
    Row,
    StepKind,
    choice_groups,
    controls_text,
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
)
from xtouch_daemon.gui.qt.fields.condition import ConditionEdit
from xtouch_daemon.gui.qt.fields.depth import scroll_shadows
from xtouch_daemon.gui.qt.fields.meter import meter_row
from xtouch_daemon.gui.qt.fields.option_row import OptionRow, add_groups, align_titles
from xtouch_daemon.gui.qt.fields.popover import Entry, show_popover
from xtouch_daemon.gui.qt.pages.base import Audio, Page, Sideways, Stack, button, card, row, scrolled, set_text
from xtouch_daemon.gui.qt.pages.slot_cards import StackList
from xtouch_daemon.gui.qt.theme.style import current_colors, set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space
from xtouch_daemon.gui.qt.window.splitter import PaneSplitter
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import Request, SetMode, SetOverride, SlotsState, SlotView, Snapshot
from xtouch_daemon.slots.model import AUTO, BUILT_IN, DEFAULT, DEVICES
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


def _clear(bar: QHBoxLayout) -> None:
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
    ):
        """
        `show_channel` opens a channel on the page Channels, `twin_slots` tells the slots of the virtual twin of the
        window (the preview in the GUI), `shows_twin` whether the drawing shows it, and `simulate_unavailable` why
        Simulate can't run.
        """
        super().__init__(editor, audio)
        self.snapshot = snapshot
        self.request = request
        self.show_channel = show_channel
        self.twin_slots = twin_slots
        self.simulate_unavailable = simulate_unavailable
        self.shows_twin = shows_twin
        self.slot = 1
        """The slot picked (1 for the leftmost one)."""
        self.candidate: int | None = None
        """The candidate of the slot the inspector shows, None for none."""
        self.shown_live: object = None
        self.what_if: WhatIf | None = None
        """What Simulate shows, None while the cards show what the daemon tells."""
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
        self.what_if_bar = QHBoxLayout()
        self.what_if_bar.setSpacing(Space.S)
        self.what_if_row = row(self.what_if_bar)
        self.what_if_row.hide()
        bars.addWidget(self.what_if_row)
        bars.addWidget(self.device_note)
        self.device_note.hide()
        bars.addStretch()
        top.addWidget(Sideways(row(bars)), 1)
        self.simulate_button = button("flask-outline", "Simulate")
        set_role(self.simulate_button, "segment", "variant")
        self.simulate_button.setCheckable(True)
        self.simulate_button.setToolTip(SIMULATE_TIP)
        self.simulate_button.clicked.connect(lambda checked: self.simulate(WhatIf() if checked else None))
        # first: it stays where it is while the what-ifs take the place of the states
        top.insertWidget(0, self.simulate_button)
        top.insertSpacing(1, Space.S)
        self.bar = row(top)
        """Simulate and the states, or the what-ifs: in the row of the window above the page (see `MainWindow`)."""
        self.state_buttons: dict[str, QToolButton] = {}
        cards = QWidget()
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
        shows and where it is now, and what `[controls]` claims; a bar in the color of how it is doing.
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
        self.show_box = QComboBox()
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
        self.place = Stack()
        inspector.addWidget(self.place)
        self.place_forms: dict[tuple[str, frozenset[str], bool], tuple[QWidget, list[OptionRow]]] = {}
        """The forms of the options of a place, by strip type and the options it takes: built once, then reused."""
        self.place_rows: list[OptionRow] = []
        """The rows of the form shown."""
        self.channel = label("", "hint", wrap=True)
        """What the candidate shows, and where it is now: as the help (`code`, the colors of states and channels)."""
        self.channel.setTextFormat(Qt.TextFormat.RichText)
        status.addWidget(self.channel)
        self.channel_button = button("pencil-outline", "Edit the channel")
        self.channel_button.clicked.connect(lambda: self.show_channel(self._candidate_row().show))
        status.addWidget(self.channel_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.controls = label("", "hint", wrap=True)
        self.controls.setTextFormat(Qt.TextFormat.RichText)
        status.addWidget(self.controls)
        inspector.addStretch()
        self.inspector_scroll = scrolled(self.inspector)
        self.splitter = PaneSplitter("slots", self.card_scroll, self.inspector_scroll)
        self.layout_.addWidget(self.splitter, 1)
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
        remove = flat_button("delete-outline", "Remove the candidate picked")
        remove.clicked.connect(lambda: self.remove(slot))
        header.addWidget(remove)
        layout.addWidget(row(header))
        stack = StackList()
        stack.currentRowChanged.connect(lambda index: self._picked(slot, index))
        stack.reordered.connect(lambda order, current: self.reorder(slot, order, current))
        layout.addWidget(stack)
        self.lists.append(stack)
        self.card_frames.append(frame)
        self.cards.addWidget(frame)

    # -- showing --------------------------------------------------------------------------------------------------

    def show_document(self, change: Change) -> None:
        if change.scope is Scope.VALUE and change.path[:1] == ("slots",):
            # an option of the place, from a row of the inspector: it shows it already
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
            elif slot != self.slot:
                stack.setCurrentRow(-1)
            stack.blockSignals(False)
            problems = self.editor.validation.at("slots", str(slot)) + self.editor.validation.at("controls", str(slot))
            set_role(self.card_frames[slot - 1], bool(problems), "problem")
            self.card_frames[slot - 1].setToolTip("\n".join(str(problem) for problem in problems))

    def _show_inspector(self) -> None:
        stack = rows(self.document.values, self.slot)
        if self.candidate is not None and self.candidate >= len(stack):
            self.candidate = len(stack) - 1 if stack else None
        self._show_why()
        controls = controls_text(self.document.values, self.slot)
        if controls:
            text = f"`[controls]` claims parts of slot {self.slot}: " + "; ".join(controls) + "."
        elif not stack:
            text = (
                f"Slot {self.slot} has no candidate: it shows `auto`, the next application that plays or person of "
                "the voice chat. Add a candidate (+ on its card) to show a channel here, e.g. an output."
            )
        elif self.candidate is None:
            text = "Pick a candidate to edit it. The first one whose condition holds is shown; + adds one at the end."
        else:
            text = ""
        set_text(self.controls, _help(text))
        self.controls.setVisible(bool(text))
        self._show_crumbs(stack)
        for widget in (self.show_box, self.when_edit):
            widget.parentWidget().setVisible(self.candidate is not None)  # pyright: ignore[reportOptionalMemberAccess]
        for widget in (self.channel, self.show_help, self.when_help):
            widget.setVisible(self.candidate is not None)
        self.place.setVisible(False)
        self.place_rows = []
        if self.candidate is None:
            set_text(self.title, f"Slot {self.slot}")
            self.channel_button.hide()
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
        self.channel_button.setVisible(isinstance(channel, dict))
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
        if strip is not None:
            # a pool of applications of your own has no `pick` encoder
            own = pool_kind(self.document.values, candidate.show) == "apps" and candidate.show not in BUILT_IN
            form, self.place_rows = self._place_form(
                strip, place_options(candidate.show, self.document.values), pick=not own
            )
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
        live = self.shown_slots()
        view = self._views().get(self.slot) if live is not None else None
        steps = why_steps(view.why) if view is not None else ()
        key = (live is not None, self.what_if is not None, self.shows_twin(), steps)
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
        view = self._views().get(self.slot)
        shown = view.candidate if view is not None else None
        # the candidate it came to, which has nothing for it: the strip is dark
        dark = view is not None and view.pool is not None and view.member is None
        key = (self.slot, tuple((row.show, row.when) for row in stack), self.candidate, shown, dark)
        if key == self.shown_crumbs:
            return
        self.shown_crumbs = key
        _clear(self.crumbs)
        for index, candidate in enumerate(stack):
            self.crumbs.addWidget(label("›", "hint"))
            crumb = QToolButton()
            set_role(crumb, Entity.CHANNEL.value, "entity")
            mark = ("○ " if dark else "● ") if index == shown else ""
            crumb.setText(f"{mark}{index + 1}  {candidate.show}")
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
            crumb.clicked.connect(lambda _=False, index=index: self.lists[self.slot - 1].setCurrentRow(index))
            self.crumbs.addWidget(crumb)

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
                if option.name == "meter":
                    option_row = self._place_meter_row()
                elif option.kind == Kind.BUTTON:
                    option_row = self._place_button_row(option)
                else:
                    option_row = self._place_row(
                        dataclasses.replace(option, choices=tuple(c for c in option.choices if pick or c != "pick")),
                        # unset, the encoder does what its strip does by default
                        (lambda: default_encoder("apps" if not pick else strip)) if option.name == "encoder" else None,
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
        return rows(self.document.values, self.slot)[self.candidate].options.get(name)

    def _set_place_option(self, name: str, value: Any) -> None:
        """Sets an option of the place of the candidate picked (None: removes it)."""
        assert self.candidate is not None
        stack = rows(self.document.values, self.slot)
        candidate = stack[self.candidate]
        options = {key: each for key, each in candidate.options.items() if key != name}
        if value is not None:
            options[name] = value
        stack[self.candidate] = Row(candidate.show, candidate.when, options)
        self._put(self.slot, stack)

    def _place_edited(self, option_row: OptionRow, name: str) -> OptionRow:
        def edited() -> None:
            assert self.candidate is not None
            self.editor.edited(Change(Scope.VALUE, ("slots", str(self.slot), self.candidate, name)))

        option_row.edited.connect(edited)
        return option_row

    def _place_row(self, option: Option, placeholder: Callable[[], str] | None = None) -> OptionRow:
        """A row for an option of the place of the candidate picked, whichever it is when it is shown or edited."""
        name = option.name
        option_row = OptionRow(
            option,
            lambda: self._place_option(name),
            lambda value: self._set_place_option(name, value),
            placeholder=placeholder,
        )
        return self._place_edited(option_row, name)

    def _place_meter_row(self) -> OptionRow:
        """`meter` and `meter_point` of the place as one choice; unset, those of the channel."""
        option_row = meter_row(self._place_option, self._set_place_option, lambda: "the channel's")
        return self._place_edited(option_row, "meter")

    def _place_button_row(self, option: Option) -> OptionRow:
        """
        A button of the place: only what its LED shows (and for Select whether it does something); what a button does
        belongs to the channel. Unset, the channel's.
        """
        parts = ("press", "led") if option.name == "select" else ("led",)
        button = option.title
        help_text = f"What the LED of {button} shows at this place; unset, what it shows on the channel." + (
            ' `press = "off"`: Select does nothing here.' if option.name == "select" else ""
        )
        option = dataclasses.replace(
            option, help=help_text, columns=tuple(c for c in option.columns if c.name in parts)
        )
        option_row = self._place_row(option)
        option_row.buttons.inherited = "the channel's"
        return option_row

    def show_problems(self, validation: Validation) -> None:
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
            state_button.setIcon(QIcon() if state is None else dot_icon(state.value, hue))
            state_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            state_button.setIconSize(DOT_ICON)
            state_button.setText(f"{self.document.get(('state', name, 'label')) or name}{override}  ▾")
            tip = f"{name}: {state.source or 'off'}" if state is not None else name
            state_button.setToolTip(f"{tip}\n\nClick for its override, or to simulate it the other way.")
        self._show_cards()
        self._show_why()

    def _views(self) -> dict[int, SlotView]:
        slots = self.shown_slots()
        return {view.slot: view for view in slots.slots} if slots is not None else {}

    # -- simulate ------------------------------------------------------------------------------------------------

    def simulate(self, what_if: WhatIf | None) -> None:
        """Shows what the slots would show in `what_if`; None goes back to what the daemon tells."""
        config = self.editor.validation.config
        if config is None or (what_if is not None and self.simulate_unavailable() is not None):
            what_if = None
        self.what_if = what_if
        self.simulate_button.setChecked(what_if is not None)
        self.state_bar_row.setVisible(what_if is None)
        self.what_if_row.setVisible(what_if is not None)
        self.device_note.setVisible(what_if is not None)
        if config is not None and what_if is not None:
            self._show_what_if_bar(Inputs.of(config.slots), what_if)
        self.shown_live = None
        self.show_live(self.snapshot())
        self.simulated.emit()

    def _show_what_if_bar(self, inputs: Inputs, what_if: WhatIf) -> None:
        _clear(self.what_if_bar)
        self.what_if_bar.addWidget(label("What if", "hint"))
        mode = QComboBox()
        mode.addItems(inputs.modes)
        mode.setCurrentText(what_if.mode)
        mode.setToolTip("The mode")
        mode.currentTextChanged.connect(lambda name: self.simulate(dataclasses.replace(what_if, mode=name)))
        self.what_if_bar.addWidget(mode)
        for name, flip, checked in (
            *((name, False, name in what_if.on) for name in inputs.states),
            *((name, True, name in what_if.flipped) for name in inputs.presence),
        ):
            toggle = QPushButton(presence_text(name) if flip else name)
            set_role(toggle, "segment", "variant")
            toggle.setCheckable(True)
            toggle.setChecked(checked)
            toggle.clicked.connect(lambda _=False, name=name, flip=flip: self.simulate(what_if.toggled(name, flip)))
            self.what_if_bar.addWidget(toggle)
        # members of the pools: a call with so many people, so many applications that play, devices plugged in
        counts: list[tuple[str, int, str, Callable[[int], WhatIf]]] = [
            ("people", what_if.people, "The people in the voice chat", lambda n: what_if.counted(people=n)),
            ("apps", what_if.apps, "The applications that play", lambda n: what_if.counted(apps=n)),
        ]
        if DEVICES in inputs.presence:
            counts.append(
                ("devices", what_if.devices, "Outputs without a channel", lambda n: what_if.counted(devices=n))
            )
        for text, value, tip, counted in counts:
            count = QSpinBox()
            indent_text(count)
            count.setRange(0, 2 * protocol.STRIPS)
            count.setValue(value)
            count.setSuffix(f" {text}")
            count.setToolTip(tip)
            count.valueChanged.connect(lambda n, counted=counted: self.simulate(counted(n)))
            self.what_if_bar.addWidget(count)

    # -- picking --------------------------------------------------------------------------------------------------

    def select_slot(self, slot: int) -> None:
        """A strip of the drawing was clicked: its card, with the candidate the device shows."""
        view = self._views().get(slot)
        count = len(rows(self.document.values, slot))
        self.slot = slot
        self.candidate = view.candidate if view is not None and view.candidate is not None else 0 if count else None
        self._show_cards()
        self._show_inspector()
        stack = self.lists[slot - 1]
        stack.setFocus()
        self.card_scroll.ensureWidgetVisible(self.card_frames[slot - 1])

    def _picked(self, slot: int, index: int) -> None:
        if index < 0:
            return
        for other, stack in enumerate(self.lists, start=1):
            if other != slot:
                stack.blockSignals(True)
                stack.clearSelection()
                stack.setCurrentRow(-1)
                stack.blockSignals(False)
        self.slot, self.candidate = slot, index
        self._show_inspector()

    def _candidate_row(self) -> Row:
        assert self.candidate is not None
        return rows(self.document.values, self.slot)[self.candidate]

    # -- editing --------------------------------------------------------------------------------------------------

    def _put(self, slot: int, stack: list[Row]) -> None:
        value = stack_value(stack)
        if value is None:
            self.document.unset(("slots", str(slot)))
        else:
            self.document.set(("slots", str(slot)), value)

    def _write(self, slot: int, stack: list[Row], candidate: int | None) -> None:
        self._put(slot, stack)
        self.slot, self.candidate = slot, candidate
        self.editor.edited(Change(Scope.SLOTS, ("slots", str(slot))))

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
        stack = rows(self.document.values, self.slot)
        # options that the new place does not take go
        allowed = place_options(candidate.show, self.document.values)
        stack[self.candidate] = Row(
            candidate.show, candidate.when, {key: value for key, value in candidate.options.items() if key in allowed}
        )
        self._write(self.slot, stack, self.candidate)

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


def _help(text: str) -> str:
    """`text` as the help shows it (see `help_text`), its lines as lines."""
    return "<br>".join(help_text(line) for line in text.split("\n"))
