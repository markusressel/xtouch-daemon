"""
The page States: the modes, then the other states, with their sources or `when`, delays and `persist`; what the
daemon says about each right now (since when, from which source), its override (a mode: picked by hand), and where it
is used.
"""

import re
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.schema import options
from xtouch_daemon.gui.domain.slots_document import OptionPath, Validation
from xtouch_daemon.gui.domain.sources import patterns
from xtouch_daemon.gui.domain.states import OVERRIDES, describe_live, live_state, ordered, state_uses
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import Suggest, help_label, label
from xtouch_daemon.gui.qt.pages.base import Audio, Page, button, card, row, scrolled, set_text
from xtouch_daemon.gui.qt.theme.icons import icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.gui.qt.window.splitter import PaneSplitter
from xtouch_daemon.live.messages import Request, SetMode, SetOverride, Snapshot
from xtouch_daemon.slots.model import StateConfig

_ID = re.compile(r"[a-z0-9_]+")
"""What a state can be called."""


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
        self.list.currentItemChanged.connect(self._picked)
        side.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.add_button = button("plus", "Add")
        menu = QMenu(self.add_button)
        for text, mode in (("Mode", True), ("State", False)):
            action = menu.addAction(icon("view-dashboard-outline" if mode else "toggle-switch-outline"), text)
            assert action is not None
            action.triggered.connect(lambda _=False, mode=mode: self.add(mode))
        self.add_button.setMenu(menu)
        self.remove_button = button("delete-outline", "Remove", "error", "danger")
        self.remove_button.clicked.connect(self.remove)
        buttons.addWidget(self.add_button)
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
        self.used = label("", "hint", wrap=True)
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
        suggest: dict[str, Suggest] = {
            "apps": lambda: patterns(self.audio()),
            "recording": lambda: patterns(self.audio()),
        }
        for option in options(StateConfig):
            layout.addWidget(
                self._row(option, lambda name: ("state", self.selection or "", name), suggest.get(option.name))
            )
        inspector.addWidget(self.form)
        self.empty = label("No states yet: Add makes one.", "hint")
        inspector.addWidget(self.empty)
        inspector.addStretch()
        pane = QWidget()
        pane.setLayout(inspector)
        inspector.setContentsMargins(0, 0, Space.S, 0)
        self.splitter = PaneSplitter("states", row(side), scrolled(pane))
        self.layout_.addWidget(self.splitter, 1)
        self._show()

    @property
    def states(self) -> dict[str, object]:
        return self.document.get(("state",), {})

    def show_document(self, change: Change) -> None:
        if change.touches(Scope.STATES):
            self._show()
        else:
            self._show_list()

    def select(self, name: str) -> None:
        self.selection = name
        self._show()

    def _show(self) -> None:
        names = ordered(self.states)
        if self.selection not in names:
            self.selection = names[0] if names else None
        self._show_list()
        name = self.selection
        for widget in (self.form, self.id_edit, self.used, self.live, self.remove_button):
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
        set_text(self.used, f"Used by: {', '.join(where)}" if where else "No slot or control asks about it yet.")
        self._load_rows(self.rows)
        self.show_live(self.snapshot())
        self.show_problems(self.editor.validation)

    def _show_list(self) -> None:
        snapshot = self.snapshot()
        self.list.blockSignals(True)
        self.list.clear()
        for name in ordered(self.states):
            mode = bool(self.document.get(("state", name, "mode")))
            live = live_state(snapshot, name)
            value = "" if live is None else "  ●" if live.value else "  ○"
            text = f"{self.document.get(('state', name, 'label')) or name}{value}\n{'mode' if mode else 'state'}"
            if self.editor.validation.at("state", name):
                text += "  ⚠"
            item = QListWidgetItem(icon("view-dashboard-outline" if mode else "toggle-switch-outline"), text)
            item.setData(Qt.ItemDataRole.UserRole, name)
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
        names = {option_row.option.name for option_row in self.rows}
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

    def add(self, mode: bool) -> None:
        self.select(self.editor.add_state(mode))

    def remove(self) -> None:
        assert self.selection is not None
        self.editor.remove_state(self.selection)

    def override(self, value: str) -> None:
        """Asks the daemon to override the state, or to pick the mode (`auto`: the rules decide again)."""
        name = self.selection
        assert name is not None
        if self.document.get(("state", name, "mode")):
            self.request(SetMode(name if value == "on" else "auto"))
        else:
            self.request(SetOverride(name, value))

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
