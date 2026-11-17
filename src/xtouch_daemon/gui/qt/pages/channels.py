"""
The page Channels: the channels of the file, `[pool.auto]` and `[people]` in a list (type, label, tags and where each
is used), and the form of the one selected, with Add, Duplicate and Remove.
"""

import re
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMenu, QVBoxLayout, QWidget

from xtouch_daemon.audio.model import Direction
from xtouch_daemon.config.values import default_encoder
from xtouch_daemon.gui.domain import docs, sources
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.channels import CHANNEL_TYPES, channel_options, people_options, pool_options, uses
from xtouch_daemon.gui.domain.schema import Option
from xtouch_daemon.gui.domain.slots_document import OptionPath, Validation
from xtouch_daemon.gui.domain.voip import participants
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import Suggest, TableSuggest, help_label, label
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.pages.base import Audio, Page, Stack, button, card, row, set_text
from xtouch_daemon.gui.qt.theme.icons import icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.live.messages import Snapshot

AUTO = ("pool", "auto")
PEOPLE = ("people",)
_ID = re.compile(r"[a-z0-9_]+")


class ChannelsPage(Page):
    def __init__(self, editor: Editor, audio: Audio, snapshot: Callable[[], Snapshot | None]):
        super().__init__(editor, audio)
        self.snapshot = snapshot
        self.selection: OptionPath = AUTO
        """What the form shows: `("channel", <id>)`, `AUTO` or `PEOPLE`."""
        header = QHBoxLayout()
        header.addWidget(label("Channels", "section"))
        header.addStretch()
        self.layout_.addWidget(row(header))
        self.layout_.addWidget(
            help_label(
                "What a strip can control. Slots show them (see Device), states can depend on them.",
                "hint",
                docs.page_link("channels"),
            )
        )
        body = QHBoxLayout()
        body.setSpacing(Space.L)
        side = QVBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        self.list.currentItemChanged.connect(self._picked)
        side.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.add_button = button("plus", "Add")
        menu = QMenu(self.add_button)
        for kind in CHANNEL_TYPES.values():
            action = menu.addAction(icon(kind.icon), kind.title)
            assert action is not None
            action.setToolTip(kind.help)
            action.triggered.connect(lambda _=False, name=kind.name: self.add(name))
        self.add_button.setMenu(menu)
        self.duplicate_button = button("content-copy", "Duplicate")
        self.duplicate_button.clicked.connect(self.duplicate)
        self.remove_button = button("delete-outline", "Remove", "error", "danger")
        self.remove_button.clicked.connect(self.remove)
        for widget in (self.add_button, self.duplicate_button, self.remove_button):
            buttons.addWidget(widget)
        buttons.addStretch()
        side.addLayout(buttons)
        body.addLayout(side)
        self.inspector = QVBoxLayout()
        self.inspector.setSpacing(Space.M)
        title = QHBoxLayout()
        self.title = label("", "section")
        title.addWidget(self.title)
        self.id_edit = QLineEdit()
        self.id_edit.setToolTip("The id: it names the channel in slots, conditions and Home Assistant")
        self.id_edit.setMaximumWidth(200)
        self.id_edit.editingFinished.connect(self._rename)
        title.addWidget(self.id_edit)
        title.addStretch()
        self.inspector.addWidget(row(title))
        self.used = label("", "hint", wrap=True)
        self.inspector.addWidget(self.used)
        self.inspector.addWidget(self.problem)
        self.forms = Stack()
        self.inspector.addWidget(self.forms)
        self.inspector.addStretch()
        body.addLayout(self.inspector, 1)
        self.layout_.addWidget(row(body), 1)
        self.form_rows: dict[str, list[OptionRow]] = {}
        self.form_widgets: dict[str, QWidget] = {}
        for kind in CHANNEL_TYPES:
            self._form(kind, channel_options(kind), lambda name: (*self.selection, name), kind)
        self._form("auto", pool_options(), lambda name: (*AUTO, name), "auto")
        self._form("people", people_options(), lambda name: (*PEOPLE, name), "voip")
        self._show()

    # -- building -------------------------------------------------------------------------------------------------

    def _form(self, key: str, form_options: tuple[Option, ...], path: Callable[[str], OptionPath], strip: str) -> None:
        frame, layout = card()
        rows: list[OptionRow] = []
        suggest, table_suggest, placeholders = self._helpers(strip)
        for option in form_options:
            layout.addWidget(
                self._row(
                    option,
                    path,
                    table_suggest.get(option.name) or suggest.get(option.name),
                    placeholders.get(option.name),
                    docs.option_link("strip", option.name, strip),
                    rows,
                )
            )
        self.form_rows[key] = rows
        self.form_widgets[key] = frame

    def _helpers(self, strip: str) -> tuple[dict[str, Suggest], dict[str, TableSuggest], dict[str, Callable[[], str]]]:
        """Suggestions and placeholders of the options of a strip type."""
        suggest: dict[str, Suggest] = {
            "match": lambda: sources.patterns(self.audio()),
            "exclude": lambda: sources.patterns(self.audio()),
            "person": lambda: participants(self.snapshot()),
        }
        table_suggest: dict[str, TableSuggest] = {}
        placeholders: dict[str, Callable[[], str]] = {
            "encoder": lambda: default_encoder(strip),
            "min_volume": lambda: "0",
            "max_volume": lambda: f"{self.document.get(('behavior', 'max_volume'), 130)} (behavior)",
            # one entry per part: the program first, then each argument
            "launch": lambda: "none: Select starts nothing; the program, then each argument",
        }
        if strip in ("output", "input"):
            direction = Direction(strip)
            suggest["device"] = lambda: sources.devices(self.audio(), direction)
            suggest["profiles"] = lambda: sources.profiles(self.audio(), direction)
            table_suggest["choices"] = {
                "device": lambda _line: sources.devices(self.audio(), direction),
                "card": lambda _line: sources.cards(self.audio()),
                "profile": lambda line: sources.card_profiles(self.audio(), str(line.get("card", ""))),
            }
            placeholders["device"] = lambda: f"none: the default {strip}"
        return suggest, table_suggest, placeholders

    # -- showing --------------------------------------------------------------------------------------------------

    @property
    def rows(self) -> list[OptionRow]:
        return self.form_rows[self._form_key()]

    def _form_key(self) -> str:
        if self.selection == AUTO:
            return "auto"
        if self.selection == PEOPLE:
            return "people"
        return str(self.document.get((*self.selection, "type"), "apps"))

    @property
    def channels(self) -> dict[str, Any]:
        return self.document.get(("channel",), {})

    def show_document(self, change: Change) -> None:
        if change.touches(Scope.CHANNELS):
            self._show()
        else:
            self._show_list()

    def select(self, selection: OptionPath) -> None:
        """Shows a channel (`("channel", <id>)`), `AUTO` or `PEOPLE`."""
        self.selection = selection
        self._show()

    def _show(self) -> None:
        if self.selection not in (AUTO, PEOPLE) and self.selection[1] not in self.channels:
            self.selection = AUTO
        self._show_list()
        key = self._form_key()
        is_channel = self.selection[0] == "channel"
        if is_channel:
            kind = CHANNEL_TYPES[key]
            set_text(self.title, kind.title)
            self.id_edit.setText(str(self.selection[1]))
        else:
            set_text(self.title, "Auto: [pool.auto]" if key == "auto" else "People: [people]")
        self.id_edit.setVisible(is_channel)
        self.duplicate_button.setEnabled(is_channel)
        self.remove_button.setEnabled(is_channel)
        name = "auto" if key == "auto" else str(self.selection[-1])
        where = uses(self.document.values, name) if key != "people" else ()
        set_text(self.used, f"Used by: {', '.join(where)}" if where else "Not used by a slot, pool or state yet.")
        self.used.setVisible(key != "people")
        self.forms.show_part(self.form_widgets[key])
        self._load_rows(self.rows)
        self.show_problems(self.editor.validation)

    def _show_list(self) -> None:
        """One line per channel, then auto and people; the selected one stays selected."""
        entries: list[tuple[OptionPath, str, str, str]] = []
        for name, channel in self.channels.items():
            kind = CHANNEL_TYPES.get(str(channel.get("type")))
            tags = ", ".join(channel.get("tags", ()))
            where = ", ".join(uses(self.document.values, name)) or "not used"
            text = f"{channel.get('label') or name}  ·  {name}" + (f"  [{tags}]" if tags else "") + f"\n{where}"
            entries.append((("channel", name), text, kind.icon if kind else "help", kind.title if kind else "?"))
        entries.append((AUTO, "Auto\nthe next application, and the people", "auto-fix", "[pool.auto]"))
        entries.append((PEOPLE, "People\nthe look and order of the people", "account-group", "[people]"))
        self.list.blockSignals(True)
        self.list.clear()
        for path, text, icon_name, tip in entries:
            item = QListWidgetItem(icon(icon_name), text)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(tip)
            if self.editor.validation.at(*path):
                item.setText(text + "  ⚠")
            self.list.addItem(item)
            if path == self.selection:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def _picked(self, item: QListWidgetItem | None) -> None:
        # the list is filled with its signals blocked: an item is picked
        assert item is not None
        self.select(item.data(Qt.ItemDataRole.UserRole))

    def show_problems(self, validation: Validation) -> None:
        names = {option_row.option.name for option_row in self.rows}
        path = self.selection
        self._show_rest(
            [
                problem.message if len(problem.path) == len(path) else str(problem)
                for problem in validation.at(*path)
                if len(problem.path) == len(path) or problem.path[len(path)] not in names
            ]
        )
        for option_row in self.rows:
            option_row.show_problems(validation.at(*path, option_row.option.name))
        set_role(self.id_edit, False, "problem")

    # -- editing --------------------------------------------------------------------------------------------------

    def add(self, channel_type: str) -> None:
        self.select(("channel", self.editor.add_channel(channel_type)))

    def duplicate(self) -> None:
        self.select(("channel", self.editor.duplicate_channel(str(self.selection[1]))))

    def remove(self) -> None:
        self.editor.remove_channel(str(self.selection[1]))

    def _rename(self) -> None:
        name = str(self.selection[1])
        new = self.id_edit.text()
        if new == name:
            return
        if not _ID.fullmatch(new) or new in self.channels or new in ("auto", "people"):
            set_role(self.id_edit, True, "problem")
            self.id_edit.setToolTip(f"{new!r} can't be the id: lowercase letters, digits and _, and not taken")
            return
        self.selection = ("channel", new)
        self.editor.rename_channel(name, new)
