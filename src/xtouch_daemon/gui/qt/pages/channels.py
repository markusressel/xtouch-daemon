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
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.values import default_encoder
from xtouch_daemon.gui.domain import docs, sources
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.channels import BUILT_IN_POOLS, CHANNEL_TYPES, channel_options, pool_options, uses
from xtouch_daemon.gui.domain.demos import GROUPS, PREVIEWED, Part, Strip, group_of, scene
from xtouch_daemon.gui.domain.schema import Option
from xtouch_daemon.gui.domain.slots_document import OptionPath, Validation
from xtouch_daemon.gui.domain.voip import participants
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import Suggest, TableSuggest, help_label, label
from xtouch_daemon.gui.qt.fields.depth import scroll_shadows
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.fields.rich_items import LINES_ROLE, EntityItemDelegate, Lines
from xtouch_daemon.gui.qt.pages.base import Audio, Page, Stack, button, card, row, scrolled, set_text
from xtouch_daemon.gui.qt.preview.part_view import PartPreview
from xtouch_daemon.gui.qt.theme.icons import icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space
from xtouch_daemon.gui.qt.window.splitter import PaneSplitter
from xtouch_daemon.live.messages import Snapshot
from xtouch_daemon.slots.model import BUILT_IN

APPS = ("pool", "apps")
PEOPLE = ("pool", "people")
AUTO = ("pool", "auto")
HEADER_CHANNELS = ("header", "channels")
HEADER_POOLS = ("header", "pools")
"""The titles of the two groups of the list: they are no channels or pools."""
POOLS = tuple(("pool", name) for name, *_ in BUILT_IN_POOLS)
"""The built-in pools: their options and look."""
_ID = re.compile(r"[a-z0-9_]+")


DIRECTIONS = (Direction.OUTPUT, Direction.INPUT)


class ChannelsPage(Page):
    def __init__(self, editor: Editor, audio: Audio, snapshot: Callable[[], Snapshot | None]):
        super().__init__(editor, audio)
        self.snapshot = snapshot
        first = next(iter(self.channels), None)
        self.selection: OptionPath = ("channel", first) if first is not None else POOLS[0]
        """What the form shows: `("channel", <id>)` or a built-in pool (`("pool", <id>)`)."""
        header = QHBoxLayout()
        header.addWidget(label("Channels", "section"))
        header.addStretch()
        self.layout_.addWidget(row(header))
        self.layout_.addWidget(
            help_label(
                "What a strip can control. Slots show them (see Slots), states can depend on them.",
                "hint",
                docs.page_link("channels"),
            )
        )
        self.start = help_label(
            "No channel in the file yet: every slot shows `auto`, the next application that plays. "
            'Add makes a channel: an output, an input, applications, a person or Home Assistant; "from the sound '
            'server" picks one of the devices there are now. A slot shows a channel once you name it on the page '
            "Slots.",
            "hint",
            docs.page_link("channels"),
        )
        self.layout_.addWidget(self.start)
        side = QVBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(160)
        self.list.setItemDelegate(EntityItemDelegate(self.list))
        scroll_shadows(self.list)
        self.listed: list[tuple[OptionPath, str, str, str]] = []
        """The lines of the list: (path, text, icon, tip)."""
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
        menu.addSeparator()
        self.device_menus = {
            direction: menu.addMenu(f"{direction.value.capitalize()} from the sound server") for direction in DIRECTIONS
        }
        menu.aboutToShow.connect(self._list_devices)
        self.add_button.setMenu(menu)
        self.duplicate_button = button("content-copy", "Duplicate")
        self.duplicate_button.clicked.connect(self.duplicate)
        self.remove_button = button("delete-outline", "Remove", "error", "danger")
        self.remove_button.clicked.connect(self.remove)
        for widget in (self.add_button, self.duplicate_button, self.remove_button):
            buttons.addWidget(widget)
        buttons.addStretch()
        side.addLayout(buttons)
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
        inspector = QWidget()
        inspector.setLayout(self.inspector)
        self.inspector.setContentsMargins(0, 0, Space.S, 0)
        self.splitter = PaneSplitter("channels", row(side), scrolled(inspector))
        self.layout_.addWidget(self.splitter, 1)
        self.form_rows: dict[str, list[OptionRow]] = {}
        self.form_widgets: dict[str, QWidget] = {}
        self.form_previews: dict[str, dict[Part, PartPreview]] = {}
        """The previews of the parts of each form."""
        self.form_values: dict[str, Callable[[], dict[str, Any]]] = {}
        """The values of the options of each form, unset ones at their defaults."""
        self.form_strips: dict[str, str] = {}
        """The strip type of each form."""
        for kind in CHANNEL_TYPES:
            self._form(kind, channel_options(kind), lambda name: (*self.selection, name), kind)
        for pool, *_ in BUILT_IN_POOLS:
            strip = "voip" if pool == "people" else "auto"
            self._form(f"pool.{pool}", pool_options(pool), lambda name, pool=pool: ("pool", pool, name), strip)
        self._show()

    # -- building -------------------------------------------------------------------------------------------------

    def _form(self, key: str, form_options: tuple[Option, ...], path: Callable[[str], OptionPath], strip: str) -> None:
        """
        The form of a type of channel (or of a built-in pool): a card per group of its options, in the order of the
        device, those about a part of the strip with a preview of what they do there.
        """
        form = QWidget()
        cards = QVBoxLayout(form)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(Space.M)
        rows: list[OptionRow] = []
        previews: dict[Part, PartPreview] = {}
        suggest, table_suggest, placeholders = self._helpers(strip)
        for group, title in GROUPS:
            options = [option for option in form_options if group_of(option.name) == group]
            if not options:
                continue
            frame, layout = card()
            layout.addWidget(label(title, "section"))
            body = QHBoxLayout()
            body.setSpacing(Space.L)
            if group in PREVIEWED:
                part: Part = group  # pyright: ignore[reportAssignmentType]: PREVIEWED holds parts only
                previews[part] = PartPreview(part)
                body.addWidget(previews[part], 0, Qt.AlignmentFlag.AlignTop)
            fields = QVBoxLayout()
            for option in options:
                fields.addWidget(
                    self._row(
                        option,
                        path,
                        table_suggest.get(option.name) or suggest.get(option.name),
                        placeholders.get(option.name),
                        docs.option_link("strip", option.name, strip),
                        rows,
                    )
                )
            body.addLayout(fields, 1)
            layout.addLayout(body)
            cards.addWidget(frame)
        self.form_rows[key] = rows
        self.form_widgets[key] = form
        self.form_previews[key] = previews
        self.form_values[key] = lambda: {option.name: self._resolved(path, option) for option in form_options}
        self.form_strips[key] = strip

    def _resolved(self, path: Callable[[str], OptionPath], option: Option) -> Any:
        """The value of an option in the document, or its default."""
        value = self.document.get(path(option.name))
        return option.default if value is None else value

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
        if self.selection in POOLS:
            return f"pool.{self.selection[1]}"
        return str(self.document.get((*self.selection, "type"), "apps"))

    @property
    def channels(self) -> dict[str, Any]:
        return self.document.get(("channel",), {})

    def show_document(self, change: Change) -> None:
        if change.touches(Scope.CHANNELS):
            self._show()
        else:
            self._show_list()
            self._show_previews()

    def _show_previews(self) -> None:
        """The previews of the form show what its values do."""
        key = self._form_key()
        config = self.editor.validation.config
        strip = Strip(self.form_strips[key], self.form_values[key](), config.behavior if config else BehaviorConfig())
        for part, preview in self.form_previews[key].items():
            preview.play(scene(part, strip))

    def select(self, selection: OptionPath) -> None:
        """Shows a channel (`("channel", <id>)`) or a built-in pool (`("pool", <id>)`)."""
        self.selection = selection
        self._show()

    def _show(self) -> None:
        if self.selection not in POOLS and self.selection[1] not in self.channels:
            self.selection = POOLS[0]
        self._show_list()
        self.start.setVisible(not self.channels)
        key = self._form_key()
        is_channel = self.selection[0] == "channel"
        if is_channel:
            kind = CHANNEL_TYPES[key]
            set_text(self.title, kind.title)
            self.id_edit.setText(str(self.selection[1]))
        else:
            title = next(title for name, title, *_ in BUILT_IN_POOLS if name == self.selection[1])
            set_text(self.title, f"{title}: [pool.{self.selection[1]}]")
        self.id_edit.setVisible(is_channel)
        self.duplicate_button.setEnabled(is_channel)
        self.remove_button.setEnabled(is_channel)
        where = uses(self.document.values, str(self.selection[-1]))
        set_text(self.used, f"Used by: {', '.join(where)}" if where else "Not used by a slot, pool or state yet.")
        self.forms.show_part(self.form_widgets[key])
        self._load_rows(self.rows)
        for option_row in self.rows:
            if option_row.option.name == "profiles":
                # the older way to switch devices, kept for files that have it: `choices` does the same
                option_row.setVisible(bool(self.document.get((*self.selection, "profiles"))))
        self._show_previews()
        self.show_problems(self.editor.validation)

    def _show_list(self) -> None:
        """A group of the channels, then one of the built-in pools; the selected one stays selected."""
        entries: list[tuple[OptionPath, str, str, str]] = [(HEADER_CHANNELS, "Channels: one strip each", "", "")]
        for name, channel in self.channels.items():
            kind = CHANNEL_TYPES.get(str(channel.get("type")))
            tags = ", ".join(channel.get("tags", ()))
            where = ", ".join(uses(self.document.values, name)) or "not used"
            text = (
                (f"{channel['label']}  ·  {name}" if channel.get("label") else name)
                + (f"  [{tags}]" if tags else "")
                + f"\n{where}"
            )
            entries.append((("channel", name), text, kind.icon if kind else "help", kind.title if kind else "?"))
        entries.append((HEADER_POOLS, "Pools: a member for each slot that names them", "", ""))
        for pool, title, icon_name, what in BUILT_IN_POOLS:
            entries.append((("pool", pool), f"{title}\n{what}", icon_name, f"[pool.{pool}]"))
        entries = [
            (path, text + "  ⚠" if path[0] != "header" and self.editor.validation.at(*path) else text, icon_name, tip)
            for path, text, icon_name, tip in entries
        ]
        self.list.blockSignals(True)
        if entries != self.listed:
            # filled again only when a line changed: every fill lays out the list (and its scroll bar) again
            self.listed = entries
            self.list.clear()
            for path, text, icon_name, tip in entries:
                if path[0] == "header":
                    # a title of a group: it can't be picked
                    item = QListWidgetItem(text)
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                else:
                    item = QListWidgetItem(icon(icon_name), text)
                    name, _, below = text.partition("\n")
                    item.setData(LINES_ROLE, Lines(name, Entity.CHANNEL, below))
                    item.setData(Qt.ItemDataRole.UserRole, path)
                    item.setToolTip(tip)
                self.list.addItem(item)
        for index, (path, *_) in enumerate(entries):
            if path == self.selection:
                self.list.setCurrentRow(index)
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

    def add(self, channel_type: str, options: dict[str, Any] | None = None) -> None:
        self.select(("channel", self.editor.add_channel(channel_type, options)))

    def _list_devices(self) -> None:
        """The outputs and inputs the sound server has now, each adds a channel for that device."""
        state = self.audio()
        for direction, menu in self.device_menus.items():
            menu.clear()
            devices = state.devices(direction)
            menu.setEnabled(bool(devices))
            menu.setToolTip("" if devices else "The sound server has none (or is not reachable)")
            for device in devices:
                action = menu.addAction(device.description)
                assert action is not None
                action.setToolTip(device.name)
                action.triggered.connect(
                    lambda _=False, kind=direction.value, name=device.name: self.add(kind, {"device": name})
                )

    def duplicate(self) -> None:
        self.select(("channel", self.editor.duplicate_channel(str(self.selection[1]))))

    def remove(self) -> None:
        self.editor.remove_channel(str(self.selection[1]))

    def _rename(self) -> None:
        name = str(self.selection[1])
        new = self.id_edit.text()
        if new == name:
            return
        if not _ID.fullmatch(new) or new in self.channels or new in BUILT_IN:
            set_role(self.id_edit, True, "problem")
            self.id_edit.setToolTip(f"{new!r} can't be the id: lowercase letters, digits and _, and not taken")
            return
        self.selection = ("channel", new)
        self.editor.rename_channel(name, new)
