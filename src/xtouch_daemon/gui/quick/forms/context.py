"""
What the forms of the window share: the sound server (for the suggestions), the daemon's live view (for people and
devices it remembers), the entities of Home Assistant, and the helpers QML calls (the help as rich text, the file
dialog, the typed data of a service). One `FormContext` per `App`; `forms_of(app)` finds or makes it.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtWidgets import QFileDialog

from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.gui.domain.entities import data_text, parse_data
from xtouch_daemon.gui.domain.places import program_text
from xtouch_daemon.gui.domain.schema import describe
from xtouch_daemon.gui.qt.fields.entities import EntitySource
from xtouch_daemon.gui.qt.window.audio_loader import AudioLoader
from xtouch_daemon.gui.quick.forms import tables, usage
from xtouch_daemon.gui.quick.forms.help import help_html
from xtouch_daemon.live.messages import KnownDevice, Request, Snapshot

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.app import App

log = logging.getLogger(__name__)


class FormContext(QObject):
    """See the module. The window gives it the sound server and the live view (`set_audio`, `snapshot`, ...)."""

    audioChanged = pyqtSignal(arguments=[])
    entitiesChanged = pyqtSignal(arguments=[])
    """The entities of Home Assistant, or why there are none, changed."""
    settingsWanted = pyqtSignal(arguments=[])
    """A field of an entity asks for the page of the settings of Home Assistant."""

    def __init__(self, app: App) -> None:
        super().__init__(app)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.app = app
        self.editor = app.editor
        self._audio: AudioState = DISCONNECTED
        self._audio_asked = False
        self.snapshot: Callable[[], Snapshot | None] = lambda: None
        """The latest snapshot of the daemon, None without one."""
        self.known: Callable[[], tuple[KnownDevice, ...]] = tuple
        """The devices the daemon remembers."""
        self.send: Callable[[Request], None] = lambda message: None
        """Sends a message to the daemon."""
        self.clock: Callable[[], float] = time.time
        self.choose_file: Callable[[str, str], str] = self._file_dialog
        """Asks for a file (title, where to start), "" for none; tests replace it."""
        document = app.editor.document
        self.entity_source = EntitySource(lambda: document.get(("homeassistant",)), app.deps.read_entities)
        self.entity_source.changed.connect(self.entitiesChanged)
        self.entity_source.settings_wanted.connect(self.settingsWanted)
        self._loader: AudioLoader | None = None

    # -- the sound server -----------------------------------------------------------------------------------------

    def audio(self) -> AudioState:
        """What the sound server has: read once in a thread the first time it is asked, until the window sets it."""
        if not self._audio_asked:
            self._audio_asked = True
            self._loader = AudioLoader(self.app.deps.read_audio)
            self._loader.loaded.connect(self.set_audio)
            self._loader.failed.connect(lambda message: log.info("The forms read no sound server: %s", message))
            self._loader.load()
        return self._audio

    def set_audio(self, state: AudioState) -> None:
        """The window read the sound server (again): the lists of suggestions are made from it."""
        self._audio_asked = True
        if state != self._audio:
            self._audio = state
            self.audioChanged.emit()

    @pyqtProperty(int, notify=audioChanged)
    def audioRevision(self) -> int:  # pyright: ignore[reportRedeclaration]
        """Changes whenever the sound server did: QML re-asks the suggestions it shows."""
        return id(self._audio) % 1_000_003

    # -- helpers for QML ------------------------------------------------------------------------------------------

    @pyqtSlot(str, str, str, str, result="QString")
    def help(self, text: str, mode: str, link: str = "", default: str = "") -> str:
        """The help of an option as rich text, in the theme `mode` (see `help_html`)."""
        return help_html(text, mode, link or None, default or None)

    @pyqtSlot("QVariant", result="QString")
    def describe(self, value: Any) -> str:
        """A value for people: "on", "a, b", "not set"."""
        return describe(value)

    @pyqtSlot("QVariant", result="QString")
    def dataText(self, value: Any) -> str:
        """The data of a service as it is typed, an inline table of TOML."""
        return data_text(value)

    @pyqtSlot(str, result="QVariant")
    def parseData(self, text: str) -> Any:
        """The table typed, None for nothing, the text as it is for what is no inline table."""
        return parse_data(text)

    @pyqtSlot(str, str, result="QString")
    def chooseFile(self, title: str, current: str) -> str:
        """The path of a file picked with a dialog: under the home directory as `~/...`; "" for none."""
        return self.choose_file(title, current)

    @staticmethod
    def _file_dialog(title: str, current: str) -> str:
        start = Path(current or "~").expanduser()
        path, _ = QFileDialog.getOpenFileName(None, title, str(start))
        if not path:
            return ""
        home = str(Path.home())
        # the daemon expands ~, which keeps the configuration usable for another user name
        return "~" + path[len(home) :] if path.startswith(home + "/") else path

    @pyqtSlot("QVariantList", int, str, "QVariant", result="QVariantList")
    def tablePut(self, entries: list[Any], index: int, name: str, value: Any) -> list[Any]:
        return tables.put(entries, index, name, value)

    @pyqtSlot("QVariantList", int, int, result="QVariantMap")
    def tableMove(self, entries: list[Any], index: int, delta: int) -> dict[str, Any]:
        moved, at = tables.move(entries, index, delta)
        return {"entries": moved, "index": at}

    @pyqtSlot("QVariantList", int, int, result="QVariantMap")
    def tableDrop(self, entries: list[Any], index: int, before: int) -> dict[str, Any]:
        moved, at = tables.move_before(entries, index, before)
        return {"entries": moved, "index": at}

    @pyqtSlot("QVariantList", int, result="QVariantList")
    def tableRemove(self, entries: list[Any], index: int) -> list[Any]:
        return tables.remove(entries, index)

    @pyqtSlot("QVariantList", result="QVariantList")
    def tableCommitted(self, entries: list[Any]) -> list[Any]:
        """The entries that go into the file: those with something in them."""
        return tables.committed(entries) or []

    @pyqtSlot("QVariantMap", result="QString")
    def programText(self, table: dict[str, Any]) -> str:
        """A table of a part as a list shows it: `launch: mumble`, `service: light.toggle`."""
        return program_text(table)

    @pyqtSlot("QVariantMap", str, "QVariant", str, result="QVariantMap")
    def entityPut(self, table: dict[str, Any], name: str, value: Any, marker: str) -> dict[str, Any]:
        """The table of an entity or a service with an option set (None: removed); the marker stays, even empty."""
        result = dict(table)
        if value is None and name != marker:
            result.pop(name, None)
        else:
            result[name] = "" if value is None else value
        return result

    @pyqtSlot("QStringList", str, result="QVariantMap")
    def usedBy(self, where: list[str], none: str) -> dict[str, Any]:
        """Where a channel or state is used, for `UsedBy` (see `usage.used_by`)."""
        return usage.used_by(where, none)

    @pyqtSlot("QVariantList", result="QVariantList")
    def historyBars(self, history: list[Any]) -> list[Any]:
        """The bars of the last day of a state, for `HistoryBars` (see `usage.history_bars`)."""
        return usage.history_bars([(float(at), bool(on)) for at, on in history], time.time())

    # -- the entities of Home Assistant ---------------------------------------------------------------------------

    @pyqtSlot()
    def wantEntities(self) -> None:
        """A field of an entity shows: reads the entities if the settings changed or they are old."""
        self.entity_source.want()

    @pyqtSlot()
    def showSettingsOfHomeAssistant(self) -> None:
        self.entity_source.settings_wanted.emit()

    @pyqtSlot(result="QString")
    def entityHint(self) -> str:
        """Why the fields of an entity have no suggestions, "" while they have."""
        return self.entity_source.why()


def forms_of(app: App) -> FormContext:
    """The context of the forms of `app`: made the first time."""
    existing = getattr(app, "_form_context", None)
    if isinstance(existing, FormContext):
        return existing
    context = FormContext(app)
    app._form_context = context  # pyright: ignore[reportAttributeAccessIssue]
    return context
