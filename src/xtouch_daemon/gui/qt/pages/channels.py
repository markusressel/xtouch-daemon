"""
The page Channels: the channels of the file, `[pool.auto]` and `[people]` in a list (type, label, tags and where each
is used), and the form of the one selected, with Add, Duplicate and Remove.
"""

import re
import time
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMenu, QVBoxLayout, QWidget

from xtouch_daemon.audio.model import Direction
from xtouch_daemon.config.buttons import ButtonSetup, default_setup
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.strip import STRIP_TYPE_MEANINGS
from xtouch_daemon.config.values import ENCODERS, default_encoder
from xtouch_daemon.gui.domain import docs, sources
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.channels import BUILT_IN_POOLS, CHANNEL_TYPES, channel_options, pool_options, uses
from xtouch_daemon.gui.domain.clipboard import Tables, parse_tables, tables_text
from xtouch_daemon.gui.domain.demos import GROUPS, PREVIEWED, Part, Strip, group_of, scene
from xtouch_daemon.gui.domain.schema import Kind, Option, options
from xtouch_daemon.gui.domain.slots_document import OptionPath, Validation
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.domain.voip import participants
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import Suggest, TableSuggest, help_label, label, set_help
from xtouch_daemon.gui.qt.fields.depth import scroll_shadows
from xtouch_daemon.gui.qt.fields.devices import device_row
from xtouch_daemon.gui.qt.fields.meter import meter_row
from xtouch_daemon.gui.qt.fields.option_row import NARROW_BELOW, OptionRow, add_rows, align_titles
from xtouch_daemon.gui.qt.fields.rich_items import LINES_ROLE, EntityItemDelegate, Lines
from xtouch_daemon.gui.qt.fields.used_by import UsedBy
from xtouch_daemon.gui.qt.pages.base import Audio, Flip, Page, Stack, button, card, row, scrolled, set_text
from xtouch_daemon.gui.qt.preview.part_view import PartPreview
from xtouch_daemon.gui.qt.theme.icons import icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space
from xtouch_daemon.gui.qt.window.splitter import PaneSplitter
from xtouch_daemon.live.messages import ForgetDevice, KnownDevice, Request, Snapshot
from xtouch_daemon.slots.model import BUILT_IN, AppsPoolConfig, PeoplePoolConfig, PoolConfig

APPS = ("pool", "apps")
PEOPLE = ("pool", "people")
AUTO = ("pool", "auto")
HEADER_CHANNELS = ("header", "channels")
HEADER_POOLS = ("header", "pools")
"""The titles of the two groups of the list: they are no channels or pools."""
CUSTOM_POOL = "pool.custom"
"""The key of the form of a pool of your own: a list of channels. Pools of applications and of people add their kind."""
CUSTOM_APPS_POOL = f"{CUSTOM_POOL}.apps"
CUSTOM_PEOPLE_POOL = f"{CUSTOM_POOL}.people"
POOLS = tuple(("pool", name) for name, *_ in BUILT_IN_POOLS)
"""The built-in pools: their options and look."""
_ID = re.compile(r"[a-z0-9_]+")


DIRECTIONS = (Direction.OUTPUT, Direction.INPUT)
POOL_KINDS = {
    CUSTOM_POOL: "A pool of channels: it hands the first of its channels that is there to the first slot that names "
    "it, the next one to the next slot.",
    CUSTOM_APPS_POOL: "A pool of applications: each application of the group that plays gets a slot of its own, while "
    "a slot names the pool.",
    CUSTOM_PEOPLE_POOL: "A pool of people: each of the listed people of the voice chat gets a slot of its own, while "
    "a slot names the pool.",
}
"""What a pool of your own is, by the key of its form."""


class ChannelsPage(Page):
    def __init__(
        self,
        editor: Editor,
        audio: Audio,
        snapshot: Callable[[], Snapshot | None],
        known: Callable[[], tuple[KnownDevice, ...]] = lambda: (),
        send: Callable[[Request], bool] = lambda request: False,
    ):
        """`known` tells the devices the daemon remembers, `send` sends a request to it (to forget one)."""
        super().__init__(editor, audio)
        self.snapshot = snapshot
        self.known = known
        self.send = send
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
        set_role(self.list, "side")
        # the lines fit the width (or are cut short): no scrolling sideways
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        menu.addSeparator()
        pool_action = menu.addAction(icon("format-list-bulleted"), "Pool of channels")
        assert pool_action is not None
        pool_action.setToolTip("Hands the first present channel of a list to the first slot, the next one to the next")
        pool_action.triggered.connect(lambda _=False: self.add_pool())
        for kind, title, tip in (
            ("apps", "Pool of applications", "Gives each application of a group that plays its own slot"),
            ("people", "Pool of people", "Gives each of the listed people of the voice chat their own slot"),
        ):
            action = menu.addAction(icon("format-list-bulleted"), title)
            assert action is not None
            action.setToolTip(tip)
            action.triggered.connect(lambda _=False, kind=kind: self.add_pool(kind))
        menu.aboutToShow.connect(self._list_devices)
        self.add_button.setMenu(menu)
        self.duplicate_button = button("content-copy", "Duplicate")
        self.duplicate_button.setToolTip("Add a copy, with an id after its own (Ctrl+D)")
        self.duplicate_button.clicked.connect(self.duplicate)
        self.remove_button = button("delete-outline", "Remove", "error", "danger")
        self.remove_button.setToolTip("Remove the channel or pool (Del)")
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
        self.about = help_label("", "hint")
        """What the type of the channel is, which the options below are about (e.g. the meter of an output)."""
        self.inspector.addWidget(self.about)
        self.used = UsedBy()
        """Where it is used: the slots as small strips (a click shows one), then the rest."""
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
        self._form(CUSTOM_POOL, options(PoolConfig), lambda name: (*self.selection, name), "auto")
        self._form(CUSTOM_APPS_POOL, options(AppsPoolConfig), lambda name: (*self.selection, name), "auto")
        self._form(CUSTOM_PEOPLE_POOL, options(PeoplePoolConfig), lambda name: (*self.selection, name), "voip")
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
        by_name = {option.name: option for option in form_options}
        for group, title in GROUPS:
            options = [option for option in form_options if group_of(option.name) == group]
            if not options:
                continue
            frame, layout = card()
            layout.addWidget(label(title, "section"))
            body = Flip(0)
            if group in PREVIEWED:
                part: Part = group  # pyright: ignore[reportAssignmentType]: PREVIEWED holds parts only
                previews[part] = PartPreview(part)
                # beside the options while they have the room of a row with its name beside the field
                body.wide = previews[part].sizeHint().width() + Space.L + NARROW_BELOW
                body.box.addWidget(previews[part], 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            fields = QVBoxLayout()
            widgets: list[QWidget] = []
            for option in options:
                if option.name == "meter_point":
                    # one choice with `meter`, see `_meter_row`
                    continue
                if option.name == "meter":
                    widgets.append(self._meter_row(path, strip, rows))
                    continue
                if option.name == "choices" and "device" in by_name:
                    # one list with `device`, see `_device_row`
                    continue
                if option.name == "device" and "choices" in by_name:
                    widgets.append(self._device_row(by_name, path, strip, table_suggest.get("choices"), rows))
                    continue
                option_row = self._row(
                    option,
                    path,
                    table_suggest.get(option.name) or suggest.get(option.name),
                    placeholders.get(option.name),
                    docs.option_link("strip", option.name, strip),
                    rows,
                )
                if option.kind == Kind.BUTTON:
                    self._button_row(option_row, option.name, path, strip)
                widgets.append(option_row)
            add_rows(fields, widgets)
            body.box.addLayout(fields, 1)
            layout.addWidget(body)
            cards.addWidget(frame)
        # one column of names for the whole form: the fields of all cards line up
        align_titles(rows)
        self.form_rows[key] = rows
        self.form_widgets[key] = form
        self.form_previews[key] = previews
        self.form_values[key] = lambda: {option.name: self._resolved(path, option) for option in form_options}
        self.form_strips[key] = strip

    def _meter_row(self, path: Callable[[str], OptionPath], strip: str, rows: list[OptionRow]) -> OptionRow:
        """
        `meter` and `meter_point` as one choice: where the meter takes the level, or off. Unset, both take their
        defaults (the meter on, at `behavior.meter_point`).
        """

        def put(name: str, value: Any) -> None:
            if value is None:
                self.document.unset(path(name))
            else:
                self.document.set(path(name), value)

        option_row = meter_row(
            lambda name: self.document.get(path(name)),
            put,
            lambda: str(self.document.get(("behavior", "meter_point"), "pre_fader")),
            docs.option_link("strip", "meter_point", strip),
        )
        option_row.edited.connect(lambda: self.editor.edited(Change(Scope.VALUE, path("meter"))))
        rows.append(option_row)
        return option_row

    def _device_row(
        self,
        by_name: dict[str, Option],
        path: Callable[[str], OptionPath],
        strip: str,
        suggest: TableSuggest | None,
        rows: list[OptionRow],
    ) -> OptionRow:
        """`device` and `choices` as one list: the names alone, or the tables once an entry has more (see `devices`)."""

        def put(name: str, value: Any) -> None:
            if value is None:
                self.document.unset(path(name))
            else:
                self.document.set(path(name), value)

        option_row = device_row(
            by_name["device"],
            by_name["choices"],
            lambda name: self.document.get(path(name)),
            put,
            suggest,
            docs.option_link("strip", "device", strip),
        )
        option_row.edited.connect(lambda: self.editor.edited(Change(Scope.VALUE, path("device"))))
        rows.append(option_row)
        return option_row

    def _button_row(self, option_row: OptionRow, name: str, path: Callable[[str], OptionPath], strip: str) -> None:
        """A button shows what the strip type does without its table, and offers the modes and states there are."""

        def defaults() -> ButtonSetup:
            return default_setup(
                name,  # pyright: ignore[reportArgumentType]: a button option is named like its button
                strip,
                devices=bool(self.document.get(path("device")) or self.document.get(path("choices"))),
                profiles=bool(self.document.get(path("profiles"))),
                launch=self.document.get(path("launch")) is not None,
            )

        def modes_and_states() -> list[str]:
            states: dict[str, Any] = self.document.get(("state",), {})
            modes = [f"mode:{state}" for state, options in states.items() if options.get("mode")]
            return [*(["cycle_modes", *modes, "mode:default"] if modes else []), *(f"toggle:{s}" for s in states)]

        option_row.buttons.defaults = defaults
        option_row.buttons.extra = modes_and_states
        option_row.load()

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
            "channels": self._channel_suggestions,
        }
        table_suggest: dict[str, TableSuggest] = {}
        placeholders: dict[str, Callable[[], str]] = {
            # bindings: done by the GUI (the encoder of a custom channel sets the fader's value)
            "encoder": lambda: default_encoder(strip) if strip in ENCODERS else "the value of the fader",
            "min_volume": lambda: "0",
            "max_volume": lambda: f"{self.document.get(('behavior', 'max_volume'), 130)} (behavior)",
            # one entry per part: the program first, then each argument
            "launch": lambda: "none: Select starts nothing; the program, then each argument",
        }
        if strip in ("output", "input"):
            direction = Direction(strip)
            suggest["profiles"] = lambda: sources.profiles(self.audio(), direction)
            table_suggest["choices"] = {
                "device": lambda _line: self._devices(direction),
                "card": lambda _line: sources.cards(self.audio()),
                "profile": lambda line: sources.card_profiles(self.audio(), str(line.get("card", ""))),
            }
        return suggest, table_suggest, placeholders

    def _devices(self, direction: Direction) -> tuple[Suggestion, ...]:
        """The devices there are, those of other profiles and those the daemon remembers."""
        return sources.devices(self.audio(), direction, self.known(), time.time(), self._forget)

    def _forget(self, device: KnownDevice) -> None:
        self.send(ForgetDevice(device.name, device.direction))

    def _channel_suggestions(self) -> tuple[Suggestion, ...]:
        """What a pool of channels can list: the channels by id, and the tags (`#tag`) of the channels."""
        found = [Suggestion(name, str(channel.get("type"))) for name, channel in self.channels.items()]
        tags = sorted({tag for channel in self.channels.values() for tag in channel.get("tags", ())})
        return (*found, *(Suggestion(f"#{tag}", "every channel with this tag") for tag in tags))

    # -- showing --------------------------------------------------------------------------------------------------

    @property
    def rows(self) -> list[OptionRow]:
        return self.form_rows[self._form_key()]

    def _form_key(self) -> str:
        if self.selection in POOLS:
            return f"pool.{self.selection[1]}"
        if self.selection[0] == "pool":
            kind = self.document.get((*self.selection, "kind"), None)
            return f"{CUSTOM_POOL}.{kind}" if kind in ("apps", "people") else CUSTOM_POOL
        return str(self.document.get((*self.selection, "type"), "apps"))

    @property
    def channels(self) -> dict[str, Any]:
        return self.document.get(("channel",), {})

    @property
    def custom_pools(self) -> dict[str, Any]:
        """The pools of channels of the file (`[pool.<id>]` that is no built-in one)."""
        return {name: pool for name, pool in self.document.get(("pool",), {}).items() if name not in BUILT_IN}

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
        kind, name = self.selection[:2]
        if self.selection not in POOLS and name not in (self.channels if kind == "channel" else self.custom_pools):
            self.selection = POOLS[0]
        self._show_list()
        self.start.setVisible(not self.channels)
        key = self._form_key()
        is_channel = self.selection[0] == "channel"
        if is_channel:
            kind = CHANNEL_TYPES[key]
            set_text(self.title, kind.title)
            self.id_edit.setText(str(self.selection[1]))
        elif self.selection in POOLS:
            title = next(title for name, title, *_ in BUILT_IN_POOLS if name == self.selection[1])
            set_text(self.title, f"{title}: [pool.{self.selection[1]}]")
        else:
            kind = self.document.get((*self.selection, "kind"), None)
            set_text(
                self.title, {"apps": "Pool of applications", "people": "Pool of people"}.get(kind, "Pool of channels")
            )
            self.id_edit.setText(str(self.selection[1]))
        self._show_about(key)
        yours = self.selection not in POOLS
        self.id_edit.setVisible(yours)
        self.duplicate_button.setEnabled(yours)
        self.remove_button.setEnabled(yours)
        where = uses(self.document.values, str(self.selection[-1]))
        self.used.show_uses(where, "Not used by a slot, pool or state yet.")
        self.forms.show_part(self.form_widgets[key])
        self._load_rows(self.rows)
        for option_row in self.rows:
            if option_row.option.name == "profiles":
                # the older way to switch devices, kept for files that have it: `choices` does the same
                option_row.setVisible(bool(self.document.get((*self.selection, "profiles"))))
        self._show_previews()
        self.show_problems(self.editor.validation)

    def _show_about(self, key: str) -> None:
        """What the type of the channel (or the pool) is, with a link to where the documentation explains it."""
        if key in CHANNEL_TYPES:
            strip = CHANNEL_TYPES[key].strip
            set_help(self.about, STRIP_TYPE_MEANINGS.meanings[strip], docs.url(docs.STRIP_TYPES[strip]))
        elif self.selection in POOLS:
            what = next(what for name, _, _, what in BUILT_IN_POOLS if name == self.selection[1])
            set_help(self.about, f"A pool: {what}. Each member gets a slot of its own.", docs.page_link("channels"))
        else:
            set_help(self.about, POOL_KINDS.get(key, POOL_KINDS[CUSTOM_POOL]), docs.page_link("channels"))

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
        for name, pool in self.custom_pools.items():
            kind = pool.get("kind")
            members = pool.get("match" if kind == "apps" else "people" if kind == "people" else "channels", ())
            if isinstance(members, str):
                members = (members,)
            what = ", ".join(str(member) for member in members) or "nothing yet"
            what = f"applications: {what}" if kind == "apps" else f"people: {what}" if kind == "people" else what
            entries.append((("pool", name), f"{name}\n{what}", "format-list-bulleted", f"[pool.{name}]"))
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
        names = {name for option_row in self.rows for name in option_row.names}
        path = self.selection
        self._show_rest(
            [
                problem.message if len(problem.path) == len(path) else str(problem)
                for problem in validation.at(*path)
                if len(problem.path) == len(path) or problem.path[len(path)] not in names
            ]
        )
        for option_row in self.rows:
            option_row.show_problems([problem for name in option_row.names for problem in validation.at(*path, name)])
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
        """A copy of the channel or pool of your own, with an id after its own."""
        self._add(self._picked_table())

    def add_pool(self, kind: str | None = None) -> None:
        self.select(("pool", self.editor.add_pool(kind)))

    def remove(self) -> None:
        if self.selection[0] == "pool":
            self.editor.remove_pool(str(self.selection[1]))
        else:
            self.editor.remove_channel(str(self.selection[1]))

    def _picked_table(self) -> Tables:
        """The channel or pool of your own picked, as tables to copy; none for a built-in pool."""
        if self.selection in POOLS:
            return {}
        section, name = self.selection[:2]
        return {str(section): {str(name): self.document.get(self.selection)}}

    def _add(self, tables: Tables) -> int:
        """Adds the tables, picks the first one; how many."""
        added = self.editor.add_tables(tables)
        if added:
            self.select(added[0])
        return len(added)

    # -- the entries, for the menu Edit ---------------------------------------------------------------------------

    ENTRIES = "channels or pools"

    def entries_focused(self) -> bool:
        return self.list.hasFocus()

    def copy_entry(self) -> str | None:
        tables = self._picked_table()
        return tables_text(tables) if tables else None

    def paste_entries(self, text: str) -> int:
        return self._add(parse_tables(text, ("channel", "pool")))

    def duplicate_entry(self) -> bool:
        return self._add(self._picked_table()) > 0

    def remove_entry(self) -> bool:
        if self.selection in POOLS:
            return False
        self.remove()
        return True

    def rename_entry(self) -> bool:
        if self.selection in POOLS:
            return False
        self.id_edit.setFocus()
        self.id_edit.selectAll()
        return True

    def _rename(self) -> None:
        name = str(self.selection[1])
        new = self.id_edit.text()
        if new == name:
            return
        if not _ID.fullmatch(new) or new in self.channels or new in self.custom_pools or new in BUILT_IN:
            set_role(self.id_edit, True, "problem")
            self.id_edit.setToolTip(f"{new!r} can't be the id: lowercase letters, digits and _, and not taken")
            return
        if self.selection[0] == "pool":
            self.selection = ("pool", new)
            self.editor.rename_pool(name, new)
            return
        self.selection = ("channel", new)
        self.editor.rename_channel(name, new)
