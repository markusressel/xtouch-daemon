"""
The page States: the modes, then the other states, with their sources or `when`, delays and `persist`; what the
daemon says about each right now (since when, from which source), its override (a mode: picked by hand), and where it
is used.
"""

import re
from collections.abc import Callable
from html import escape
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.clipboard import Tables, parse_tables, tables_text
from xtouch_daemon.gui.domain.schema import options
from xtouch_daemon.gui.domain.slots_document import OptionPath, Validation
from xtouch_daemon.gui.domain.sources import patterns
from xtouch_daemon.gui.domain.states import OVERRIDES, describe_live, live_state, ordered, state_uses
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import Suggest, flat_button, help_label, label
from xtouch_daemon.gui.qt.fields.condition import ConditionEdit
from xtouch_daemon.gui.qt.fields.depth import scroll_shadows
from xtouch_daemon.gui.qt.fields.menu import attach_menu, describe, with_icon
from xtouch_daemon.gui.qt.fields.option_row import OptionRow, align_titles, divider, text_width
from xtouch_daemon.gui.qt.fields.rich_items import DOT_ROLE, DotItemDelegate
from xtouch_daemon.gui.qt.fields.used_by import UsedBy
from xtouch_daemon.gui.qt.pages.base import Audio, Page, button, card, row, scrolled, set_text
from xtouch_daemon.gui.qt.theme.icons import icon, set_icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space
from xtouch_daemon.gui.qt.window.splitter import PaneSplitter
from xtouch_daemon.live.messages import Request, SetMode, SetOverride, Snapshot
from xtouch_daemon.slots.model import DEFAULT, StateConfig

_ID = re.compile(r"[a-z0-9_]+")
"""What a state can be called."""
SOURCES = {
    "apps": "An application plays",
    "recording": "An application records",
    "voice_chat": "You are in the voice chat",
    "processes": "A process runs",
    "devices": "A device is there",
    "channels": "A channel is present",
    "homeassistant": "A switch in Home Assistant is on",
    "command": "A program of your own says on",
}
"""The sources of a state, in the words of the menu Add source."""
SOURCE_DETAILS = {
    "apps": "You list the applications, e.g. `@games`.",
    "recording": "You list the applications, e.g. `@voip` for an open microphone.",
    "voice_chat": "On during a call, e.g. in a channel of Mumble.",
    "processes": "You list the names of the programs, e.g. `@steam-games`.",
    "devices": "You list outputs or inputs, e.g. a USB headset that is plugged in.",
    "channels": "You list channels of the file, e.g. one for a device that comes and goes.",
    "homeassistant": "A switch for the state in Home Assistant turns it on. Needs `[mqtt]`.",
    "command": "A program prints `on` while the state should be, e.g. a check of your VPN.",
}
"""What each source of the menu Add source asks for, under its words."""
SOURCE_ICONS = {
    "apps": "play-circle-outline",
    "recording": "record-circle-outline",
    "voice_chat": "headset",
    "processes": "cog-outline",
    "devices": "headphones",
    "channels": "tune-vertical",
    "homeassistant": "home-assistant",
    "command": "console",
}
"""The icons of the sources in the menu Add source."""
MODE_ICON = "view-dashboard-outline"
STATE_ICON = "toggle-switch-outline"
SWITCHES = frozenset({"voice_chat", "homeassistant"})
"""Sources that are a switch: added, they are on."""
MODE_ONLY = ("label", "priority")
DELAYS = ("delay_on", "delay_off", "persist")
KIND_HELP = (
    "One mode is on at a time: the one with the highest priority whose sources are on. Any number of states can be on."
)
ON_WHILE_HELP = "Sources are what goes on at the computer. A condition combines other states and modes."
WHEN_HELP = "On while this condition of other states and modes holds."


def _set(value: Any) -> bool:
    """Whether a source has a value: a list with something in it, or a switch that is on."""
    return value is not None and value is not False and value != [] and value != ()


def _check(group: QButtonGroup, index: int) -> None:
    button = group.button(index)
    assert button is not None
    if not button.isChecked():
        button.setChecked(True)


TEMPLATES: tuple[tuple[str, str, bool, dict[str, Any], str], ...] = (
    (
        "In a call",
        "call",
        False,
        {"voice_chat": True, "recording": ["@voip"], "delay_off": 5},
        "A state: on while you are in the voice chat or an application for calls records.",
    ),
    (
        "Gaming",
        "gaming",
        True,
        {"label": "Gaming", "processes": ["@steam-games"]},
        "A mode: on while a game of Steam runs. The LCDs show Gaming when it comes.",
    ),
)
"""The starting points in the menu Add: text, id, whether a mode, the options, and what it is."""
KINDS = (
    ("Mode", True, "One mode is on at a time. Slots and controls can change with it, e.g. for a game."),
    ("State", False, "Any number of states can be on at once. A slot can show a channel only while one is on."),
)
"""The kinds in the menu Add: text, whether a mode, and what it is."""


class StatesPage(Page):
    def __init__(
        self,
        editor: Editor,
        audio: Audio,
        snapshot: Callable[[], Snapshot | None],
        request: Callable[[Request], bool],
    ):
        """`request` sends a request to the daemon (an override, a mode picked); False without a daemon."""
        super().__init__(editor, audio)
        self.snapshot = snapshot
        self.request = request
        self.selection: str | None = None
        """The name of the state the form shows, None while there is none."""
        self.arranged: str | None = None
        """The state the form was last arranged for: another one closes the delays again and forgets added sources."""
        self.shown_values: tuple[bool, ...] | None = None
        """The values of the states the list shows."""
        header = QHBoxLayout()
        header.addWidget(label("States", "section"))
        header.addStretch()
        self.layout_.addWidget(row(header))
        self.layout_.addWidget(
            help_label(
                "What slots show depends on them: a mode at a time (the one with the highest priority whose sources "
                "are on), and any number of states.",
                "hint",
                docs.page_link("states"),
            )
        )
        side = QVBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(160)
        set_role(self.list, "side")
        self.list.setItemDelegate(DotItemDelegate(self.list))
        # the lines fit the width (or are cut short): no scrolling sideways
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_shadows(self.list)
        self.list.currentItemChanged.connect(self._picked)
        side.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.add_button = button("plus", "Add")
        self.add_menu = QMenu(self.add_button)
        """What Add offers: a mode, a state, and the usual ones to start from."""
        menu = self.add_menu
        menu.addSection("Kinds")
        for text, mode, detail in KINDS:
            action = menu.addAction(text)
            assert action is not None
            describe(with_icon(action, MODE_ICON if mode else STATE_ICON), detail, Entity.STATE)
            action.triggered.connect(lambda _=False, mode=mode: self.add(mode))
        menu.addSection("Starting points")
        for text, name, mode, preset, detail in TEMPLATES:
            action = menu.addAction(text)
            assert action is not None
            describe(with_icon(action, MODE_ICON if mode else STATE_ICON), detail, Entity.STATE)
            action.triggered.connect(lambda _=False, name=name, mode=mode, preset=preset: self.add(mode, name, preset))
        attach_menu(self.add_button, menu)
        self.duplicate_button = button("content-copy", "Duplicate")
        self.duplicate_button.setToolTip("Add a copy, with an id after its own (Ctrl+D)")
        self.duplicate_button.clicked.connect(self.duplicate_entry)
        self.remove_button = button("delete-outline", "Remove", "error", "danger")
        self.remove_button.setToolTip("Remove the state or mode (Del)")
        self.remove_button.clicked.connect(self.remove)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.duplicate_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        side.addLayout(buttons)
        inspector = QVBoxLayout()
        inspector.setSpacing(Space.M)
        title = QHBoxLayout()
        self.title = label("", "section")
        title.addWidget(self.title)
        self.id_edit = QLineEdit()
        self.id_edit.setToolTip("The id: it names the state in conditions, Home Assistant and `xtouch-daemon mode`")
        self.id_edit.setMaximumWidth(200)
        self.id_edit.editingFinished.connect(self._rename)
        title.addWidget(self.id_edit)
        title.addStretch()
        inspector.addWidget(row(title))
        self.used = UsedBy()
        """Where it is used: the slots as small strips (a click shows one), then the rest."""
        inspector.addWidget(self.used)
        live = QHBoxLayout()
        self.live = label("", wrap=True)
        live.addWidget(self.live, 1)
        self.overrides = QButtonGroup(self)
        self.override_buttons: dict[str, QPushButton] = {}
        for value in OVERRIDES:
            segment = QPushButton(value)
            set_role(segment, "segment", "variant")
            segment.setCheckable(True)
            segment.clicked.connect(lambda _=False, value=value: self.override(value))
            self.overrides.addButton(segment)
            self.override_buttons[value] = segment
            live.addWidget(segment)
        inspector.addWidget(row(live))
        inspector.addWidget(self.problem)
        self.form, layout = card()
        self._build_form(layout)
        inspector.addWidget(self.form)
        self.empty = label(
            "No states yet. A state is when something matters: slots can show a channel only while it is on "
            '("voip if call"). Add makes one; "In a call" and "Gaming" in its menu start from the usual '
            "ones. Slots work without any.",
            "hint",
            wrap=True,
        )
        inspector.addWidget(self.empty)
        inspector.addStretch()
        pane = QWidget()
        pane.setLayout(inspector)
        inspector.setContentsMargins(0, 0, Space.S, 0)
        self.splitter = PaneSplitter("states", row(side), scrolled(pane))
        self.layout_.addWidget(self.splitter, 1)
        self._show()

    def _build_form(self, layout: QVBoxLayout) -> None:
        """
        The form of a state, in the order of the questions: a state or a mode (a mode has a label and a priority),
        on while its sources are on or while a condition holds (never both), and the delays and the override.
        """
        self._titles: list[QLabel] = []
        """The names of the fields that are no `OptionRow`, in the same column (see `_align`)."""
        self._under: list[QLabel] = []
        """What goes under those fields, from where the fields start."""
        found = {option.name: option for option in options(StateConfig)}
        suggest: dict[str, Suggest] = {
            "apps": lambda: patterns(self.audio()),
            "recording": lambda: patterns(self.audio()),
        }

        def option_row(name: str) -> OptionRow:
            return self._row(found[name], lambda name: ("state", self.selection or "", name), suggest.get(name))

        self.kind = self._segments(
            layout, "Kind", ("State", "Mode"), lambda index: self._set_mode(index == 1), KIND_HELP
        )
        self.mode_rows = [option_row("label"), option_row("priority")]
        for widget in self.mode_rows:
            layout.addWidget(widget)
        layout.addWidget(divider())
        self.on_while = self._segments(
            layout, "On while", ("Sources", "Condition"), lambda index: self._set_composed(index == 1), ON_WHILE_HELP
        )
        self.sources_box = QWidget()
        sources = QVBoxLayout(self.sources_box)
        sources.setContentsMargins(0, 0, 0, 0)
        sources.setSpacing(Space.XS)
        self.sources_hint = label("", "hint", wrap=True)
        sources.addWidget(self.sources_hint)
        self.source_rows: dict[str, QWidget] = {}
        for name in SOURCES:
            line = QHBoxLayout()
            source = option_row(name)
            # ✕ removes it
            source.resettable = False
            line.addWidget(source, 1)
            remove = flat_button("delete-outline", "Remove this source")
            remove.clicked.connect(lambda _=False, name=name: self._remove_source(name))
            line.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
            holder = row(line)
            self.source_rows[name] = holder
            sources.addWidget(holder)
        add = QHBoxLayout()
        self.add_source = button("plus", "Add source")
        self.source_menu = QMenu(self.add_source)
        """The sources the state does not have yet."""
        attach_menu(self.add_source, self.source_menu)
        add.addWidget(self.add_source)
        add.addStretch()
        sources.addWidget(row(add))
        layout.addWidget(self.sources_box)
        self.condition_box = QWidget()
        condition = QVBoxLayout(self.condition_box)
        condition.setContentsMargins(0, 0, 0, 0)
        condition.setSpacing(Space.XS)
        line = QHBoxLayout()
        title = label("Condition")
        self._titles.append(title)
        line.addWidget(title)
        self.when_edit = ConditionEdit(present=False)
        self.when_edit.setPlaceholderText("e.g. call and not gaming")
        self.when_edit.editingFinished.connect(self._edit_when)
        line.addWidget(self.when_edit, 1)
        condition.addWidget(row(line))
        self.when_error = label("", "error", wrap=True)
        self._under.append(self.when_error)
        self.when_error.hide()
        condition.addWidget(self.when_error)
        when_help = help_label(WHEN_HELP, "help", docs.guide_link("conditions"))
        self._under.append(when_help)
        condition.addWidget(when_help)
        layout.addWidget(self.condition_box)
        layout.addWidget(divider())
        self.delays_button = QToolButton()
        self.delays_button.setText("Delays and overrides")
        self.delays_button.setCheckable(True)
        self.delays_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.delays_button.setAutoRaise(True)
        self.delays_button.toggled.connect(self._show_delays)
        layout.addWidget(self.delays_button)
        self.delay_rows = [option_row("delay_on"), option_row("delay_off"), option_row("persist")]
        for widget in self.delay_rows:
            layout.addWidget(widget)
        self._align()
        self.added: set[str] = set()
        """Sources added to the state shown that have no value yet."""
        self.composed: dict[str, bool] = {}
        """States set to Condition (or Sources) that have neither a condition nor sources yet."""

    def _align(self) -> None:
        """One column of names for the form, as wide as its longest name."""
        width = align_titles(self.option_rows, least=max(text_width(title) for title in self._titles))
        for title in self._titles:
            title.setFixedWidth(width)
        for under in self._under:
            under.setContentsMargins(width + Space.S, 0, 0, 0)

    def _segments(
        self, layout: QVBoxLayout, title: str, texts: tuple[str, ...], picked: Callable[[int], None], help: str
    ) -> QButtonGroup:
        """A row of buttons of which one is checked, like the field of a choice, with help under it."""
        line = QHBoxLayout()
        line.setSpacing(Space.S)
        name = label(title)
        self._titles.append(name)
        line.addWidget(name)
        group = QButtonGroup(self)
        for index, text in enumerate(texts):
            segment = QPushButton(text)
            set_role(segment, "segment", "variant")
            segment.setCheckable(True)
            group.addButton(segment, index)
            line.addWidget(segment)
        line.addStretch()
        group.idClicked.connect(picked)
        layout.addWidget(row(line))
        hint = help_label(help, "help")
        self._under.append(hint)
        layout.addWidget(hint)
        return group

    def _arrange(self) -> None:
        """Shows the parts of the form that fit the state shown: mode or not, sources or a condition."""
        name = self.selection
        if name is None:
            return
        state: dict[str, Any] = self.states.get(name) or {}  # pyright: ignore[reportAssignmentType]
        mode = bool(state.get("mode"))
        _check(self.kind, 1 if mode else 0)
        for widget in self.mode_rows:
            widget.setVisible(mode)
        composed = "when" in state or self.composed.get(name, False)
        _check(self.on_while, 1 if composed else 0)
        self.sources_box.setVisible(not composed)
        self.condition_box.setVisible(composed)
        shown = [source for source in SOURCES if _set(state.get(source)) or source in self.added]
        for source, holder in self.source_rows.items():
            holder.setVisible(source in shown)
        set_text(
            self.sources_hint,
            "On while any of these is on."
            if shown
            else "No sources yet: it is on only while you turn it on. Add source adds one.",
        )
        self.source_menu.clear()
        for source, text in SOURCES.items():
            if source not in shown:
                action = self.source_menu.addAction(text)
                assert action is not None
                describe(with_icon(action, SOURCE_ICONS[source]), SOURCE_DETAILS[source])
                action.triggered.connect(lambda _=False, source=source: self._add_source(source))
        self.add_source.setVisible(len(shown) < len(SOURCES))

    def _show_delays(self, shown: bool) -> None:
        set_icon(self.delays_button, "chevron-down" if shown else "chevron-right")
        for widget in self.delay_rows:
            widget.setVisible(shown)

    @property
    def states(self) -> dict[str, object]:
        return self.document.get(("state",), {})

    def show_document(self, change: Change) -> None:
        if change.touches(Scope.STATES):
            self._show()
        else:
            self._show_list()
            self._arrange()

    def select(self, name: str) -> None:
        self.selection = name
        self._show()

    def _show(self) -> None:
        names = ordered(self.states)
        if self.selection not in names:
            self.selection = names[0] if names else None
        self._show_list()
        name = self.selection
        for widget in (self.form, self.id_edit, self.used, self.live, self.duplicate_button, self.remove_button):
            widget.setVisible(name is not None)
        self.empty.setVisible(name is None)
        if name is None:
            set_text(self.title, "")
            for segment in self.override_buttons.values():
                segment.hide()
            self._show_rest([])
            return
        mode = bool(self.document.get(("state", name, "mode")))
        set_text(self.title, "Mode" if mode else "State")
        self.id_edit.setText(name)
        where = state_uses(self.document.values, name)
        self.used.show_uses(where, "No slot or control asks about it yet.")
        self._load_rows(self.rows)
        if name != self.arranged:
            # another state: its delays open if it has any, sources added to the last one are gone
            self.arranged = name
            self.added = set()
            self.delays_button.setChecked(
                any(self.document.get(("state", name, delay)) is not None for delay in DELAYS)
            )
            self._show_delays(self.delays_button.isChecked())
        others = [other for other in self.states if other != name]
        self.when_edit.set_names([*others, DEFAULT], [])
        self.when_edit.setText(str(self.document.get(("state", name, "when")) or ""))
        self._arrange()
        self.show_live(self.snapshot())
        self.show_problems(self.editor.validation)

    def _show_list(self) -> None:
        snapshot = self.snapshot()
        self.list.blockSignals(True)
        self.list.clear()
        for name in ordered(self.states):
            mode = bool(self.document.get(("state", name, "mode")))
            live = live_state(snapshot, name)
            text = f"{self.document.get(('state', name, 'label')) or name}\n{'mode' if mode else 'state'}"
            if self.editor.validation.at("state", name):
                text += "  ⚠"
            item = QListWidgetItem(icon("view-dashboard-outline" if mode else "toggle-switch-outline"), text)
            item.setData(Qt.ItemDataRole.UserRole, name)
            # the dot after the name, drawn by `DotItemDelegate`
            item.setData(DOT_ROLE, None if live is None else live.value)
            self.list.addItem(item)
            if name == self.selection:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def show_live(self, snapshot: Snapshot | None) -> None:
        """What the daemon says about the state, and its override (of a mode: whether it was picked by hand)."""
        values = tuple(state.value for state in snapshot.slots.states) if snapshot and snapshot.slots else None
        if values != self.shown_values:
            # the dots of the list, only when a value changed (the live view tells 20 times a second)
            self.shown_values = values
            self._show_list()
        name = self.selection
        if name is None:
            return
        state = live_state(snapshot, name)
        set_text(self.live, describe_live(state))
        mode = bool(self.document.get(("state", name, "mode")))
        picked = snapshot.slots.mode_pick if snapshot is not None and snapshot.slots is not None else None
        # none is checked while another mode is picked: an exclusive group keeps one
        self.overrides.setExclusive(False)
        for value, segment in self.override_buttons.items():
            segment.setVisible(state is not None and (not mode or value != "off"))
            if mode:
                current = "on" if picked == name else "auto" if picked is None else None
            else:
                current = state.override if state is not None else None
            segment.setChecked(value == current)
        self.overrides.setExclusive(True)
        self.override_buttons["on"].setText("pick" if mode else "on")

    def _picked(self, item: QListWidgetItem | None) -> None:
        # the list is filled with its signals blocked: an item is picked
        assert item is not None
        self.select(item.data(Qt.ItemDataRole.UserRole))

    def show_problems(self, validation: Validation) -> None:
        if self.selection is None:
            return
        path: OptionPath = ("state", self.selection)
        names = {option_row.option.name for option_row in self.rows} | {"when"}
        when = [problem.message for problem in validation.at(*path, "when")]
        set_text(self.when_error, "\n".join(when))
        self.when_error.setVisible(bool(when))
        set_role(self.when_edit, bool(when), "problem")
        self._show_rest(
            [
                problem.message if len(problem.path) == 2 else str(problem)
                for problem in validation.at(*path)
                if len(problem.path) == 2 or problem.path[2] not in names
            ]
        )
        for option_row in self.rows:
            option_row.show_problems(validation.at(*path, option_row.option.name))

    # -- editing --------------------------------------------------------------------------------------------------

    def add(self, mode: bool, name: str | None = None, options: dict[str, Any] | None = None) -> None:
        self.select(self.editor.add_state(mode, name, options))

    def remove(self) -> None:
        assert self.selection is not None
        self.editor.remove_state(self.selection)

    def _picked_table(self) -> Tables:
        """The state picked, as tables to copy; none without one."""
        if self.selection is None:
            return {}
        return {"state": {self.selection: self.document.get(("state", self.selection)) or {}}}

    def _add(self, tables: Tables) -> int:
        """Adds the states, picks the first one; how many."""
        added = self.editor.add_tables(tables)
        if added:
            self.select(added[0][1])
        return len(added)

    # -- the entries, for the menu Edit ---------------------------------------------------------------------------

    ENTRIES = "states"

    def entries_focused(self) -> bool:
        return self.list.hasFocus()

    def copy_entry(self) -> str | None:
        tables = self._picked_table()
        return tables_text(tables) if tables else None

    def paste_entries(self, text: str) -> int:
        return self._add(parse_tables(text, ("state",)))

    def duplicate_entry(self) -> bool:
        return self._add(self._picked_table()) > 0

    def remove_entry(self) -> bool:
        if self.selection is None:
            return False
        self.remove()
        return True

    def rename_entry(self) -> bool:
        if self.selection is None:
            return False
        self.id_edit.setFocus()
        self.id_edit.selectAll()
        return True

    def override(self, value: str) -> None:
        """Asks the daemon to override the state, or to pick the mode (`auto`: the rules decide again)."""
        name = self.selection
        assert name is not None
        if self.document.get(("state", name, "mode")):
            self.request(SetMode(name if value == "on" else "auto"))
        else:
            self.request(SetOverride(name, value))

    def _set_mode(self, mode: bool) -> None:
        """A mode, or a state: a state has no label and no priority, so they go."""
        name = self.selection
        assert name is not None
        if mode:
            self.document.set(("state", name, "mode"), True)
        else:
            for option in ("mode", *MODE_ONLY):
                self.document.unset(("state", name, option))
        self.editor.edited(Change(Scope.STATES))

    def _set_composed(self, composed: bool) -> None:
        """On while a condition holds, or while sources are on: what the other way had goes, after a question."""
        name = self.selection
        assert name is not None
        state: dict[str, Any] = self.states.get(name) or {}  # pyright: ignore[reportAssignmentType]
        dropped = [source for source in SOURCES if source in state] if composed else ["when"] * ("when" in state)
        if dropped and not self._confirm_switch(composed, state, dropped):
            self._arrange()
            return
        self.composed[name] = composed
        self.added = set()
        for option in dropped:
            self.document.unset(("state", name, option))
        if dropped:
            self.editor.edited(Change(Scope.STATES))
        else:
            self._arrange()
        if composed:
            self.when_edit.setFocus()

    def _confirm_switch(self, composed: bool, state: dict[str, Any], dropped: list[str]) -> bool:
        """
        Whether to switch between sources and a condition: a state is on by one or the other, so what the state had
        the other way goes.
        """
        if composed:
            title = "Condition instead of sources"
            items = "".join(f"<li>{SOURCES[source]}</li>" for source in dropped)
            text = (
                "A state follows its sources or a condition, not both. A condition removes its sources:"
                f"<ul>{items}</ul>"
            )
        else:
            title = "Sources instead of a condition"
            text = (
                "A state follows its sources or a condition, not both. Sources remove its condition "
                f"<code>{escape(str(state['when']))}</code>."
            )
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self)
        box.setTextFormat(Qt.TextFormat.RichText)
        switch = box.addButton("Remove and switch", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is switch

    def _add_source(self, source: str) -> None:
        name = self.selection
        assert name is not None
        if source in SWITCHES:
            # a switch is the source once it is on: nothing else to fill in
            self.document.set(("state", name, source), True)
            self.editor.edited(Change(Scope.VALUE, ("state", name, source)))
            self._load_rows(self.rows)
        else:
            self.added.add(source)
        self._arrange()

    def _remove_source(self, source: str) -> None:
        name = self.selection
        assert name is not None
        self.added.discard(source)
        if self.document.get(("state", name, source)) is not None:
            self.document.unset(("state", name, source))
            self.editor.edited(Change(Scope.VALUE, ("state", name, source)))
            self._load_rows(self.rows)
        self._arrange()

    def _edit_when(self) -> None:
        name = self.selection
        if name is None:
            return
        when = self.when_edit.text().strip()
        if when == (self.document.get(("state", name, "when")) or ""):
            return
        self.composed[name] = True
        if when:
            self.document.set(("state", name, "when"), when)
        else:
            self.document.unset(("state", name, "when"))
        self.editor.edited(Change(Scope.VALUE, ("state", name, "when")))

    def _rename(self) -> None:
        name = self.selection
        new = self.id_edit.text()
        if name is None or new == name:
            return
        if not _ID.fullmatch(new) or new in self.states or new == "default":
            set_role(self.id_edit, True, "problem")
            return
        set_role(self.id_edit, False, "problem")
        self.selection = new
        self.editor.rename_state(name, new)
