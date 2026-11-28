"""
The page Channels for QML: the channels of the file and the pools (`[pool.apps]`, `[pool.people]`, ...) in a list with
their lines and marks (type, where it is used, problems, sound), and the form of the one picked, with Add, Duplicate
and Remove. Everything the page decides is here: what the list shows (`channels_list`), the forms and their previews
(`channels_forms`), which entry the Edit menu works on, the rename. QML shows it and animates it.

The window hooks in with `show_live(snapshot)` (the sound of the channels), `show_channel(name)` and `show_pool(name)`
(a slot opens its channel), and the context of the forms (`forms_of(app)`: the sound server, the daemon).
"""

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.channels import BUILT_IN_POOLS, CHANNEL_TYPES, uses
from xtouch_daemon.gui.domain.clipboard import Tables, parse_tables, tables_text
from xtouch_daemon.gui.domain.slots_document import OptionPath
from xtouch_daemon.gui.quick.forms.context import FormContext, forms_of
from xtouch_daemon.gui.quick.forms.form import Form
from xtouch_daemon.gui.quick.models import KeyedListModel
from xtouch_daemon.gui.quick.pages.base import PageBackend
from xtouch_daemon.gui.quick.pages.channels_forms import FORM_KEYS, ChannelForms
from xtouch_daemon.gui.quick.pages.channels_forms import form_key as key_for
from xtouch_daemon.gui.quick.pages.channels_list import (
    CUSTOM_POOL,
    NOT_USED,
    POOL_KINDS,
    POOLS,
    START,
    add_menu,
    custom_pools,
    key_of,
    list_rows,
    path_of,
)
from xtouch_daemon.gui.quick.pages.channels_support import ID, NO_ID, PaneShare, clipboard_text, set_clipboard_text
from xtouch_daemon.gui.quick.pages.sound import sounding
from xtouch_daemon.live.messages import Snapshot
from xtouch_daemon.slots.model import BUILT_IN

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.app import App

POOL_TITLES = {"apps": "Pool of applications", "people": "Pool of people"}


class ChannelsPage(PageBackend):
    """See the module. `selection` is `("channel", id)` or `("pool", id)`."""

    PREBUILD_AFTER_MS: int | None = 1000
    """Milliseconds after the page shows before the forms are made in the background (see `prebuild`); None: only when
    they show."""

    selectionChanged = pyqtSignal(arguments=[])
    inspectorChanged = pyqtSignal(arguments=[])
    prebuiltChanged = pyqtSignal(arguments=[])
    idProblemChanged = pyqtSignal(arguments=[])
    renameRequested = pyqtSignal(arguments=[])
    """The id of the entry picked should get the keyboard focus, its text selected (F2)."""

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.editor = app.editor
        self.context: FormContext = forms_of(app)
        self.forms = ChannelForms(self.context, self)
        self._pane = PaneShare("channels", self)
        self.selection: OptionPath = POOLS[0]
        first = next(iter(self.values.get("channel", {})), None)
        if first is not None:
            self.selection = ("channel", first)
        self._entries = KeyedListModel(self)
        self._inspector: dict[str, Any] = {}
        self._id_problem = ""
        self._list_focused = False
        self._prebuilt: list[str] = []
        self._queue: list[str] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._prebuild_next)
        self.editor.changed.connect(self._changed)
        self._show()

    # -- what QML reads -------------------------------------------------------------------------------------------

    @pyqtProperty(QObject, constant=True)
    def entries(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """The list: headers, channels and pools (`channels_list.list_rows`)."""
        return self._entries

    @pyqtProperty(QObject, constant=True)
    def tools(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """The helpers of the forms (help as rich text, used-by): what `UsedBy` needs."""
        return self.context

    @pyqtProperty(QObject, constant=True)
    def pane(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """The share of the width of the list, kept for the next start."""
        return self._pane

    @pyqtProperty(str, notify=selectionChanged)
    def current(self) -> str:  # pyright: ignore[reportRedeclaration]
        """The key of the entry picked (`channel:out`, `pool:apps`)."""
        return key_of(self.selection)

    @pyqtProperty(int, notify=selectionChanged)
    def currentIndex(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The row of the entry picked in the list."""
        keys = self._entries.keys()
        return keys.index(self.current) if self.current in keys else -1

    @pyqtProperty("QVariantMap", notify=inspectorChanged)
    def inspector(self) -> dict[str, Any]:  # pyright: ignore[reportRedeclaration]
        """What the right of the page shows of the entry picked: title, id, about, where it is used, its form."""
        return self._inspector

    @pyqtProperty("QStringList", constant=True)
    def formKeys(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        return list(FORM_KEYS)

    @pyqtProperty("QStringList", notify=prebuiltChanged)
    def prebuilt(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        """The keys of the forms made in the background so far."""
        return self._prebuilt

    @pyqtProperty(str, notify=idProblemChanged)
    def idProblem(self) -> str:  # pyright: ignore[reportRedeclaration]
        """Why the id typed can't be the id, "" while it can."""
        return self._id_problem

    @pyqtSlot(str, result=QObject)  # pyright: ignore[reportArgumentType]
    def formOf(self, key: str) -> Form:
        """The form of `key` (made the first time); `FormView` shows it."""
        return self.forms.form(key)

    @pyqtSlot(str, result=QObject)  # pyright: ignore[reportArgumentType]
    def partModel(self, part: str) -> QObject:
        """The preview of a part of the strip beside the options about it."""
        model = self.forms.partModel(part)
        self.forms.play(self.form_key)
        return model

    @property
    def values(self) -> dict[str, Any]:
        return self.editor.document.values

    @property
    def channels(self) -> dict[str, Any]:
        return self.values.get("channel", {})

    @property
    def form_key(self) -> str:
        return key_for(self.selection, self.values)

    # -- the document ---------------------------------------------------------------------------------------------

    def _changed(self, change: Change) -> None:
        if change.touches(Scope.CHANNELS):
            self._show()
        else:
            self._show_list()
            self._show_inspector()
        self.forms.play(self.form_key)
        self.editableChanged.emit()

    def _show(self) -> None:
        """After a change of the channels: the selection still there (or the first pool), the list, the form."""
        section, name = self.selection[:2]
        if self.selection not in POOLS and name not in (self.channels if section == "channel" else self.pools):
            self.selection = POOLS[0]
        self._show_list()
        self._show_inspector()
        self.selectionChanged.emit()
        self.forms.form(self.form_key).retarget(tuple(str(part) for part in self.selection))
        self.forms.play(self.form_key)
        self.editableChanged.emit()

    @property
    def pools(self) -> dict[str, Any]:
        return custom_pools(self.values)

    def _show_list(self) -> None:
        self._entries.show(list_rows(self.values, self.editor.validation))

    def _show_inspector(self) -> None:
        selection = self.selection
        key = self.form_key
        is_channel = selection[0] == "channel"
        mine = selection not in POOLS
        about, link = self._about(key)
        if is_channel:
            title = CHANNEL_TYPES[key].title
        elif not mine:
            title = (
                f"{next(title for name, title, *_ in BUILT_IN_POOLS if name == selection[1])}: [pool.{selection[1]}]"
            )
        else:
            title = POOL_TITLES.get(
                str(self.values.get("pool", {}).get(selection[1], {}).get("kind")), "Pool of channels"
            )
        inspector = {
            "kind": selection[0],
            "name": str(selection[1]),
            "title": title,
            "mine": mine,
            "about": about,
            "link": link,
            "where": list(uses(self.values, str(selection[-1]))),
            "none": NOT_USED,
            "formKey": key,
            "start": START if not self.channels else "",
            "startLink": docs.page_link("channels") or "",
            "hint": "What a strip can control. Slots show them (see Slots), states can depend on them.",
        }
        if inspector != self._inspector:
            self._inspector = inspector
            self.inspectorChanged.emit()

    def _about(self, key: str) -> tuple[str, str]:
        """What the type of the channel (or the pool) is, and where the documentation explains it."""
        if key in CHANNEL_TYPES:
            from xtouch_daemon.config.strip import STRIP_TYPE_MEANINGS

            strip = CHANNEL_TYPES[key].strip
            return STRIP_TYPE_MEANINGS.meanings[strip], docs.url(docs.STRIP_TYPES[strip])
        if self.selection in POOLS:
            what = next(what for name, _, _, what in BUILT_IN_POOLS if name == self.selection[1])
            return f"A pool: {what}. Each member gets a slot of its own.", docs.page_link("channels") or ""
        return POOL_KINDS.get(key, POOL_KINDS[CUSTOM_POOL]), docs.page_link("channels") or ""

    # -- picking --------------------------------------------------------------------------------------------------

    def select(self, selection: OptionPath) -> None:
        """Shows a channel (`("channel", <id>)`) or a pool (`("pool", <id>)`)."""
        self.selection = (str(selection[0]), str(selection[1]))
        self._set_id_problem("")
        self._show()

    @pyqtSlot(str)
    def pick(self, key: str) -> None:
        """An entry of the list was clicked (its key)."""
        if not key.startswith("header:"):
            self.select(path_of(key))

    @pyqtSlot(int)
    def step(self, direction: int) -> None:
        """The next (or previous) entry of the list: the arrow keys; the titles of the groups are skipped."""
        keys = [key for key in self._entries.keys() if not key.startswith("header:")]  # noqa: SIM118
        if self.current in keys:
            self.pick(keys[max(0, min(len(keys) - 1, keys.index(self.current) + direction))])

    def show_channel(self, name: str) -> None:
        """A slot opens its channel."""
        if name in self.channels:
            self.select(("channel", name))

    def show_pool(self, name: str) -> None:
        if name in BUILT_IN or name in self.pools:
            self.select(("pool", name))

    @pyqtSlot("QVariantList")
    def reveal(self, path: list[str]) -> None:
        """Shows the option at `path` (`["channel", "browser", "color"]`): picks its entry, focuses the row."""
        if len(path) < 2 or path[0] not in ("channel", "pool"):
            return
        section, name = str(path[0]), str(path[1])
        if (section, name) not in POOLS and name not in (self.channels if section == "channel" else self.pools):
            return
        self.select((section, name))
        if len(path) > 2:
            form = self.forms.form(self.form_key)
            QTimer.singleShot(0, lambda: form.reveal(str(path[2])))

    def show_live(self, snapshot: Snapshot | None) -> None:
        """The channels that have sound move in the list."""
        sounding().show(snapshot.sounding if snapshot is not None else ())

    # -- the forms in the background ------------------------------------------------------------------------------

    @pyqtSlot()
    def prebuild(self) -> None:
        """
        Makes the forms in the background, one each time the window has nothing else to do: those of the types in
        the file first. A form takes a moment to make; made before, it shows at once on the first click.
        """
        if self.PREBUILD_AFTER_MS is None or self._queue:
            return
        used = {str(channel.get("type", "apps")) for channel in self.channels.values() if isinstance(channel, dict)}
        self._queue = sorted(FORM_KEYS, key=lambda key: key not in used)
        self._timer.start(self.PREBUILD_AFTER_MS)

    def _prebuild_next(self) -> None:
        while self._queue and self._queue[0] in self._prebuilt:
            self._queue.pop(0)
        if not self._queue:
            return
        key = self._queue.pop(0)
        self.forms.form(key)
        self._prebuilt = [*self._prebuilt, key]
        self.prebuiltChanged.emit()
        self._timer.start(0)

    # -- adding and removing --------------------------------------------------------------------------------------

    @pyqtSlot(result="QVariantList")
    def addEntries(self) -> list[dict[str, Any]]:
        """The menu Add: the types, the devices of the sound server now, the pools."""
        return add_menu(self.context.audio())

    @pyqtSlot(str)
    def add(self, action: str) -> None:
        """An entry of the menu Add: `type:<type>`, `device:<output|input>:<name>`, `pool:<kind>`."""
        what, _, rest = action.partition(":")
        if what == "type":
            self.add_channel(rest)
        elif what == "device":
            kind, _, name = rest.partition(":")
            self.add_channel(kind, {"device": name})
        elif what == "pool":
            self.add_pool(rest or None)

    def add_channel(self, channel_type: str, options: dict[str, Any] | None = None) -> None:
        self.select(("channel", self.editor.add_channel(channel_type, options)))

    def add_pool(self, kind: str | None = None) -> None:
        self.select(("pool", self.editor.add_pool(kind)))

    @pyqtSlot()
    def remove(self) -> None:
        if self.selection in POOLS:
            return
        if self.selection[0] == "pool":
            self.editor.remove_pool(str(self.selection[1]))
        else:
            self.editor.remove_channel(str(self.selection[1]))

    @pyqtSlot()
    def duplicate(self) -> None:
        """A copy of the channel or pool of your own, with an id after its own."""
        self._add(self._picked_table())

    def _picked_table(self) -> Tables:
        """The channel or pool of your own picked, as tables to copy; none for a built-in pool."""
        if self.selection in POOLS:
            return {}
        section, name = self.selection[:2]
        return {str(section): {str(name): self.editor.document.get(self.selection)}}

    def _add(self, tables: Tables) -> int:
        """Adds the tables, picks the first one; how many."""
        added = self.editor.add_tables(tables)
        if added:
            self.select(added[0])
        return len(added)

    # -- renaming -------------------------------------------------------------------------------------------------

    @pyqtSlot(str, result=bool)  # pyright: ignore[reportArgumentType]
    def rename(self, new: str) -> bool:
        """Another id for the entry picked (slots, pools and states that name it follow); False if it can't."""
        if self.selection in POOLS:
            return False
        name = str(self.selection[1])
        if new == name:
            self._set_id_problem("")
            return True
        if not ID.fullmatch(new) or new in self.channels or new in self.pools or new in BUILT_IN:
            self._set_id_problem(NO_ID.format(new))
            return False
        section = self.selection[0]
        self._set_id_problem("")
        self.selection = (section, new)
        if section == "pool":
            self.editor.rename_pool(name, new)
        else:
            self.editor.rename_channel(name, new)
        return True

    @pyqtSlot()
    def clearIdProblem(self) -> None:
        self._set_id_problem("")

    def _set_id_problem(self, text: str) -> None:
        if text != self._id_problem:
            self._id_problem = text
            self.idProblemChanged.emit()

    # -- the Edit menu --------------------------------------------------------------------------------------------

    @pyqtSlot(bool)
    def listFocus(self, focused: bool) -> None:
        """The list got or lost the keyboard focus: the Edit menu works on its entry."""
        if focused != self._list_focused:
            self._list_focused = focused
            self.editableChanged.emit()

    def editable_actions(self) -> list[str]:
        if not self._list_focused:
            return []
        if self.selection in POOLS:
            return ["paste"]
        return ["cut", "copy", "paste", "duplicate", "remove", "rename"]

    @pyqtSlot(str)
    def edit(self, action: str) -> None:
        if action == "paste":
            self._add(parse_tables(clipboard_text(), ("channel", "pool")))
        elif self.selection in POOLS:
            return
        elif action in ("copy", "cut"):
            set_clipboard_text(tables_text(self._picked_table()))
            if action == "cut":
                self.remove()
        elif action == "duplicate":
            self.duplicate()
        elif action == "remove":
            self.remove()
        elif action == "rename":
            self.renameRequested.emit()
