"""
The window around the pages: what the menus, the footer, the dialogs, the panels and the log of `XTouch.Window` show
and do. `Shell` is `app.shell` in QML.

It decides what the widgets' `MainWindow` decided (see there for the why of each rule): what the footer says, when
Save and apply is enabled, what closing asks, what happens to the file, the service, the daemon and the preview.
The parts around it use these:

- `live` (the `LiveView`, `changed` with each snapshot of the daemon), `live_preview`, `daemon` (the `Instance` found,
  or None), `trying` (the daemon of "Try without a device"), `hosted` (the virtual device in the window, with
  `hostedChanged`), `audio` (the sound server as the forms see it; `audioChanged`) and `document`, `history`,
  `validation`. The shell is the one owner of all of these: the drawing of the device (`DevicePanel`) only reads them.
- `tell(text)` says something in the status line, `refresh_preview()` shows the state of the device, the preview and
  the file anew (call it after hosting a virtual device, a test, ...), `previewChanged` follows it.
- `try_without_device()`, `restart_daemon()`, `restart_reason()`, `use_virtual_device()`, `switch_to_device()`,
  `open_virtual_device()`, `close_virtual_device()`: what the buttons of the drawing of the device do. The shell
  starts the daemon of the trial, saves the file and hosts the virtual device; `virtualDeviceOpened` tells the drawing
  to play on it.
- `show_slot(n)`, `go_to(problem)`, `showPage(name)` (also for a section of the settings) go to places.
- Each snapshot of the daemon (`refresh_preview`) reaches the drawing (`previewChanged`), the page Slots
  (`show_live`, `show_place`), the page Settings (`show_live`) and the forms (`forms_of(app)`): see `_wire_pages`.
"""

import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import (
    QFileSystemWatcher,
    QObject,
    QProcess,
    QRect,
    QTimer,
    QUrl,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
)  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtGui import QClipboard, QColor, QDesktopServices, QGuiApplication
from PyQt6.QtQuick import QQuickWindow

from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.domain import docs, sources
from xtouch_daemon.gui.domain.apply import apply, describe
from xtouch_daemon.gui.domain.changes import EVERYTHING, Change, Scope
from xtouch_daemon.gui.domain.connections import connections
from xtouch_daemon.gui.domain.history import History
from xtouch_daemon.gui.domain.live_preview import Place, previewed, unavailable
from xtouch_daemon.gui.domain.problems import place_of
from xtouch_daemon.gui.domain.slots import slots_status
from xtouch_daemon.gui.domain.slots_document import SlotsDocument, Validation
from xtouch_daemon.gui.domain.status import (
    DeviceOffer,
    Status,
    Switch,
    Tone,
    changes_status,
    device_offer,
    drawing_status,
    offers_virtual_device,
    preview_status,
    runs_older,
)
from xtouch_daemon.gui.domain.twin import unavailable as twin_unavailable
from xtouch_daemon.gui.qt import errors
from xtouch_daemon.gui.qt.file_watch import FileWatch
from xtouch_daemon.gui.qt.live_preview import LivePreview
from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.gui.qt.theme.icons import APP_ICON
from xtouch_daemon.gui.qt.theme.settings import (
    ZOOM_LEVELS,
    load_rail_labels,
    load_zoom,
    save_rail_labels,
    save_zoom,
    zoom_step,
    zoom_text,
)
from xtouch_daemon.gui.qt.theme.tokens import THEMES, ThemeMode
from xtouch_daemon.gui.qt.virtual_device import HostedDevice
from xtouch_daemon.gui.qt.window.audio_loader import AudioLoader
from xtouch_daemon.gui.qt.window.session import Session, from_screen, to_screen
from xtouch_daemon.gui.quick.details import Content, Details
from xtouch_daemon.gui.quick.theme import Theme, colors_of
from xtouch_daemon.gui.quick.window import messages
from xtouch_daemon.gui.quick.window.dialogs import (
    OVERWRITE,
    OVERWRITE_RELOAD_CANCEL,
    RELOAD,
    SAVE,
    SAVE_DISCARD_CANCEL,
    YES,
    YES_NO,
    Asker,
    Dialogs,
)
from xtouch_daemon.gui.quick.window.hover import HoverTips
from xtouch_daemon.gui.quick.window.keys import UndoKeys
from xtouch_daemon.gui.quick.window.log import LogBackend
from xtouch_daemon.gui.quick.window.menus import flat, menus, native
from xtouch_daemon.gui.quick.window.panels import Panels
from xtouch_daemon.gui.quick.window.rich import help_html, tip_html
from xtouch_daemon.gui.quick.window.service import ServiceBackend
from xtouch_daemon.live.messages import Request, Snapshot
from xtouch_daemon.simulator.server import AlreadyServed
from xtouch_daemon.system import instance
from xtouch_daemon.system.instance import Instance
from xtouch_daemon.system.systemd import ServiceError

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.app import App

log = logging.getLogger(__name__)

SERVICE_POLL_MS = 3000
APPLY_GRACE_MS = 2000
"""How long a reload may take before the window says that the daemon did not take the file."""
AUDIO_ICONS = {"output": "speaker", "input": "microphone", "application": "play-circle-outline"}
"""The icons of what the sound server has, in its pill: outputs, inputs, applications that play."""
PLACE_TEXTS = {Place.GUI: "In the GUI", Place.DEVICE: "On the device", Place.OFF: "Off"}
"""The positions of the control "Preview", from the left."""
PLACE_TIPS = {
    Place.GUI: (
        "Shows the changes, and Simulate while it is open, here in the window: on a twin of the device in the daemon. "
        "The device keeps running the saved file."
    ),
    Place.DEVICE: (
        "Runs the changes, and Simulate while it is open, on the device before they are saved: the device changes. "
        "It runs the saved file again once you pick another place or close the window."
    ),
    Place.OFF: (
        "Shows the device as it is: it runs the saved file. The changes show nowhere until you save them or pick "
        "another place."
    ),
}
"""What each position of the control "Preview" does."""
RAIL = (("slots", "Slots"), ("channels", "Channels"), ("states", "States"), ("settings", "Settings"))
"""The pages of the rail by name and title (`app.PAGES`), for Ctrl+1 to Ctrl+4."""
SETTINGS = ("behavior", "device", "aliases", "mqtt", "homeassistant", "switching", "voip")
"""The sections of the settings: `showPage` takes these names too and shows the page Settings at the section."""
KEYS_LISTS = (
    ("Up, Down", "Pick the one above or below"),
    ("Ctrl+Up, Ctrl+Down", "Move the candidate (Slots), the entry of a table"),
)
KEYS_DEVICE = (
    ("Left, Right, Home, End", "Pick a strip"),
    ("Ctrl+Left, Ctrl+Right", "Move its slot"),
    ("Esc", "End Simulate, close a popover"),
)
KEYS_EDIT = (
    "Cut, Copy, Paste, Duplicate, Remove and Rename are for the candidate, channel or state picked "
    "in the list that has the focus. In a field, the keys edit its text."
)
MINIMUM_WINDOW = (640, 480)
"""The smallest size the window remembers."""


def start_trial(path: Path) -> QProcess:
    """A daemon with the virtual device on `path` (see `Shell.try_without_device`)."""
    process = QProcess()
    process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)
    process.start(sys.executable, ["-m", "xtouch_daemon", "run", "--virtual-device", "--config", str(path)])
    return process


class Shell(QObject):
    """See the module."""

    titleChanged = pyqtSignal(arguments=[])
    statusChanged = pyqtSignal(arguments=[])
    hoverChanged = pyqtSignal(arguments=[])
    disabledChanged = pyqtSignal(arguments=[])
    checkedChanged = pyqtSignal(arguments=[])
    problemsChanged = pyqtSignal(arguments=[])
    barChanged = pyqtSignal(arguments=[])
    editableChanged = pyqtSignal(arguments=[])
    zoomChanged = pyqtSignal(arguments=[])
    railLabelsChanged = pyqtSignal(arguments=[])
    diskChanged = pyqtSignal(arguments=[])
    previewChanged = pyqtSignal(arguments=[])
    """The state of the device, the preview or the file was shown anew (`refresh_preview`): the drawing follows."""
    audioChanged = pyqtSignal(arguments=[])
    """The sound server was read (see `audio`)."""
    hostedChanged = pyqtSignal(arguments=[])
    """The window hosts a virtual device now, or no longer, or it was plugged in or out or connected."""
    virtualDeviceOpened = pyqtSignal(arguments=[])
    """The window began to host the virtual device (a daemon waits for it): the drawing plays on it."""
    keysRequested = pyqtSignal(arguments=[])
    """The menu Help asked for the keys: QML opens their popover."""
    closeRequested = pyqtSignal(arguments=[])
    """The menu Quit: QML closes the window (which asks about unsaved changes)."""
    windowAttached = pyqtSignal(arguments=[])

    def __init__(self, app: App) -> None:
        super().__init__(app)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.app = app
        deps = app.deps
        self.editor = app.editor
        self.service = deps.service
        self.find_daemon = deps.find_daemon
        self.daemon: Instance | None = None
        self.audio: AudioState = deps.session.audio if deps.session is not None else DISCONNECTED
        self.zoom = load_zoom()
        self.rezoom: float | None = None
        """The zoom the next window gets: set when this one closes for a new zoom (see `Session`)."""
        self.last_session: Session | None = None
        """What the next window needs, taken as this one closes for a new zoom."""
        self.window: QQuickWindow | None = None
        self.theme: Theme | None = None
        self._dialogs = Dialogs(self)
        """The dialog QML shows; `asker` is what asks (this one, or a fake of the tests)."""
        self.asker: Asker = deps.dialogs if deps.dialogs is not None else self._dialogs
        self._status = ""
        self._hover = ""
        self._disk = ""
        self._labels = load_rail_labels()
        self._title = "X-Touch Extender"
        self._problems: list[Problem] = []
        self._disabled: list[str] = []
        self._bar: dict[str, Any] = {}
        self._editable: list[str] = []
        self._normal: QRect | None = None
        self._started = False
        self.applying = QTimer(self)
        """Runs for a moment after a reload, while the daemon takes the file."""
        self.applying.setSingleShot(True)
        self.applying.setInterval(APPLY_GRACE_MS)
        self.applying.timeout.connect(self.refresh_preview)
        self.audio_error: str | None = None
        self.trying: QProcess | None = None
        """The daemon started by "Try without a device"; it ends with the window."""
        self.restarting_trial = False
        self.hosted: HostedDevice | None = None
        """The virtual device while the window hosts it (see `open_virtual_device`)."""
        self.virtual_socket = deps.virtual_socket or instance.virtual_device_socket_file()
        self.launch_trial: Callable[[Path], QProcess] = deps.extra.get("launch_trial", start_trial)  # pyright: ignore[reportAttributeAccessIssue]
        if deps.session is not None and deps.session.trying is not None:
            self._keep_trying(deps.session.trying)
        self.resume_place = Place(deps.session.preview) if deps.session is not None else None
        """Where the preview showed in the window before the zoom: it goes there once it can."""

        self.live = LiveView(deps.live_socket or instance.socket_file(), self)
        self.live.changed.connect(lambda _: self.refresh_preview())
        self.live_preview = LivePreview(self.live, self.document)
        self.live_preview.changed.connect(self.refresh_preview)
        self._panels = Panels(self)
        self._log = LogBackend(self.live, self.colors, self)
        self._panels.log_panel.changed.connect(lambda: self._log.setActive(self._panels.log_panel.shown))
        self._controls = ServiceBackend(self.service, self.asker, self.rich, self)
        self._controls.changed.connect(self.refresh_service)
        self._controls.told.connect(self.tell)
        self._controls.settingsAsked.connect(self.showPage)
        self.audio_details = Details(self._audio_content, self.rich, self)
        self.changes_details = Details(self._changes_content, self.rich, self)
        self.keys_details = Details(self._keys_content, self.rich, self)
        self.changes: Status | None = None
        self.menu_data = menus([(name, title) for name, title in RAIL])
        self.entries = {item["id"]: item for item in flat(self.menu_data)}
        self.undo_keys = UndoKeys(self)  # pyright: ignore[reportArgumentType]
        self.hover: HoverTips | None = None
        self.loader = AudioLoader(deps.read_audio)
        self.loader.loaded.connect(self._audio_loaded)
        self.loader.failed.connect(self._audio_failed)
        self.audio_pill: dict[str, Any] = {
            "text": "Reading the sound server…",
            "tone": "neutral",
            "tip": "",
            "parts": [],
        }
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_service)
        # a daemon that starts: its live view at once, not at the next poll, so the drawing shows its startup sequence
        self.runtime_watch = QFileSystemWatcher([str(self.live.path.parent)], self)
        self.runtime_watch.directoryChanged.connect(self._runtime_changed)
        self._live_socket_there = self.live.path.exists()
        self.file_watch = FileWatch(self.document.path, self)
        """Changes of the file on disk by someone else (see `_file_changed`)."""
        self.file_watch.changed.connect(self._file_changed)
        self.editor.changed.connect(self._document_changed)
        errors.listen(self._error_raised)
        app.pageChanged.connect(self._page_changed)

    # -- the parts ------------------------------------------------------------------------------------------------

    @property
    def document(self) -> SlotsDocument:
        return self.editor.document

    @property
    def history(self) -> History[SlotsDocument]:
        return self.editor.history

    @property
    def validation(self) -> Validation:
        return self.editor.validation

    def colors(self) -> dict[str, QColor]:
        """The colors of the theme QML shows."""
        if self.theme is not None:
            return self.theme.colors
        return colors_of(THEMES[ThemeMode.DARK])

    @pyqtSlot(str, result=str)  # pyright: ignore[reportArgumentType]
    def rich(self, text: str) -> str:
        """`text` (a help with `code` and the words of the configuration) as markup in the colors of the theme."""
        return help_html(text, self.colors())

    @pyqtSlot(str, result=str)  # pyright: ignore[reportArgumentType]
    def tipHtml(self, tip: str) -> str:
        """The markup of a tooltip: the first paragraph as it is, the others muted."""
        return tip_html(tip, self.colors())

    @pyqtSlot(QObject, QObject)
    def attach(self, window: QObject, theme: QObject) -> None:
        """QML, when the window is made: starts what needs it (the service, the sound server, the file)."""
        assert isinstance(window, QQuickWindow)
        assert isinstance(theme, Theme)
        self.window, self.theme = window, theme
        theme.modeChanged.connect(self._theme_changed)
        self.checkedChanged.emit()
        self.hover = HoverTips(window, self._hovered)
        app = QGuiApplication.instance()
        assert app is not None
        app.installEventFilter(self.undo_keys)
        for changed in (window.widthChanged, window.heightChanged, window.xChanged, window.yChanged):
            changed.connect(self._remember_geometry)
        session = self.app.deps.session
        if session is not None:
            window.setGeometry(from_screen(session.geometry, window.devicePixelRatio()))
            if session.maximized:
                window.showMaximized()
        else:
            self._restore_size(window)
        self.start()
        self.windowAttached.emit()

    def start(self) -> None:
        """Reads the sound server, finds the daemon and shows everything; once."""
        if self._started:
            return
        self._started = True
        self.timer.start(SERVICE_POLL_MS)
        self._wire_pages()
        self.load_audio()
        if self.app.deps.follow_audio is not None:
            # the pill and its popover follow the sound server
            self.loader.follow(self.app.deps.follow_audio)
        self.refresh_service()
        self._document_changed(EVERYTHING)
        self._page_changed()
        self._panels.log_panel.changed.emit()

    # -- properties for QML ---------------------------------------------------------------------------------------

    @pyqtProperty(str, notify=titleChanged)
    def title(self) -> str:  # pyright: ignore[reportRedeclaration]
        """The title of the window: the file, with • while it has unsaved changes."""
        return self._title

    @pyqtProperty(str, notify=statusChanged)
    def statusText(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._status

    @pyqtProperty(str, notify=hoverChanged)
    def hoverTip(self) -> str:  # pyright: ignore[reportRedeclaration]
        """The first paragraph of the tip of what the mouse is over: it replaces the status line meanwhile."""
        return self._hover

    @pyqtProperty("QStringList", notify=disabledChanged)
    def disabled(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        """The ids of the menu entries (and footer buttons: `save`, `revert`, `undo`, `redo`) that do nothing now."""
        return self._disabled

    @pyqtProperty("QStringList", notify=checkedChanged)
    def checked(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        return self._checked()

    @pyqtProperty("QStringList", notify=problemsChanged)
    def problems(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        """What the list of problems says of each, in order."""
        return [self._problem_text(problem) for problem in self._problems]

    @pyqtProperty(str, notify=problemsChanged)
    def problemsText(self) -> str:  # pyright: ignore[reportRedeclaration]
        count = len(self._problems)
        return f"{count} problem{'' if count == 1 else 's'}"

    @pyqtProperty("QVariantMap", notify=barChanged)
    def bar(self) -> dict[str, Any]:  # pyright: ignore[reportRedeclaration]
        """What the footer shows besides the status line: `audio`, `changes`, `places`, `message`, `restart`, ..."""
        return self._bar

    @pyqtProperty("QStringList", notify=editableChanged)
    def editable(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        """What the Edit menu can do to the list of the page shown now (see `PageBackend.editable`)."""
        return self._editable

    @pyqtProperty("QVariantList", constant=True)
    def menus(self) -> list[dict[str, Any]]:  # pyright: ignore[reportRedeclaration]
        return self.menu_data

    @pyqtProperty("QVariantList", constant=True)
    def shortcuts(self) -> list[dict[str, Any]]:  # pyright: ignore[reportRedeclaration]
        """Every key of the menus: `id` and one `sequence` (an entry with two keys is two items)."""
        return [{"id": item["id"], "sequence": key} for item in self.entries.values() for key in item["keys"]]

    @pyqtProperty("QVariantList", constant=True)
    def zoomLevels(self) -> list[dict[str, Any]]:  # pyright: ignore[reportRedeclaration]
        return [{"value": level, "text": zoom_text(level)} for level in ZOOM_LEVELS]

    @pyqtProperty(float, notify=zoomChanged)
    def zoomLevel(self) -> float:  # pyright: ignore[reportRedeclaration]
        return self.zoom

    @pyqtProperty(bool, notify=railLabelsChanged)
    def railLabels(self) -> bool:  # pyright: ignore[reportRedeclaration]
        """Whether the rail shows the names of the pages under their icons."""
        return self._labels

    @pyqtProperty(str, notify=diskChanged)
    def diskMessage(self) -> str:  # pyright: ignore[reportRedeclaration]
        """What the bar over the page says while the file changed on disk or can't be read; "" hides the bar."""
        return self._disk

    @pyqtProperty(str, constant=True)
    def logo(self) -> str:  # pyright: ignore[reportRedeclaration]
        """The icon of the project, for the menu bar."""
        return QUrl.fromLocalFile(str(APP_ICON)).toString()

    @pyqtProperty(QObject, constant=True)
    def panels(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """Where the Device and the Log are (see `Panels`)."""
        return self._panels

    @pyqtProperty(QObject, constant=True)
    def logView(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._log

    @pyqtProperty(QObject, constant=True)
    def dialogs(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._dialogs

    @pyqtProperty(QObject, constant=True)
    def serviceControls(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._controls

    @pyqtProperty(QObject, constant=True)
    def audioPopover(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self.audio_details

    @pyqtProperty(QObject, constant=True)
    def changesPopover(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self.changes_details

    @pyqtProperty(QObject, constant=True)
    def keysPopover(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self.keys_details

    @pyqtProperty(str, notify=previewChanged)
    def place(self) -> str:  # pyright: ignore[reportRedeclaration]
        """Where the preview shows: `gui`, `device` or `off` (the control Preview of the footer)."""
        return self.live_preview.place.value

    @pyqtProperty(str, notify=previewChanged)
    def placeText(self) -> str:  # pyright: ignore[reportRedeclaration]
        """Where the page Slots says the preview shows: "On the device", "In the GUI" or "Nowhere: why"."""
        reason = twin_unavailable(self.live.snapshot, self.live.owned)
        if self.live_preview.on:
            return "On the device"
        return "In the GUI" if reason is None else f"Nowhere: {reason.short}"

    # -- the status line ------------------------------------------------------------------------------------------

    @pyqtSlot(str)
    def tell(self, text: str) -> None:
        """Says `text` in the status line."""
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    def _hovered(self, tip: str) -> None:
        if tip != self._hover:
            self._hover = tip
            self.hoverChanged.emit()

    def _error_raised(self, text: str) -> None:
        """An error no code caught (see `errors`): the window goes on, the status line says it."""
        self.tell(messages.error_raised(text))

    # -- menus and shortcuts --------------------------------------------------------------------------------------

    def _checked(self) -> list[str]:
        checked = [f"zoom.{self.zoom:g}"]
        if self.theme is not None:
            checked.append(f"theme.{self.theme.mode}")
        for panel in (self._panels.device_panel, self._panels.log_panel):
            if panel.shown:
                checked.append(panel.name)
            checked.append(f"{panel.name}.place.{panel.place}")
        if self._labels:
            checked.append("labels")
        return checked

    def _theme_changed(self) -> None:
        self.checkedChanged.emit()
        self._log.redraw()

    def _set_disabled(self) -> None:
        enabled = {
            "save": self._savable(),
            "revert": self.document.modified or self.document.overruled is not None,
            "undo": self.history.can_undo,
            "redo": self.history.can_redo,
        }
        edit = {
            action: action in self._editable for action in ("cut", "copy", "paste", "duplicate", "remove", "rename")
        }
        disabled = [name for name, on in {**enabled, **edit}.items() if not on]
        if disabled != self._disabled:
            self._disabled = disabled
            self.disabledChanged.emit()

    @pyqtSlot(str)
    def trigger(self, id: str) -> None:
        """Does the entry `id` of a menu (also the keys of the window)."""
        if id in self._disabled:
            return
        panels = {"device": self._panels.device_panel, "log": self._panels.log_panel}
        match id.split("."):
            case ["save"]:
                self.save()
            case ["revert"]:
                self.revert()
            case ["quit"]:
                self.closeRequested.emit()
            case ["undo"]:
                self.undo()
            case ["redo"]:
                self.redo()
            case ["cut" | "copy" | "paste" | "duplicate" | "remove" | "rename" as action]:
                self.edit(action)
            case ["page", name]:
                self.app.showPage(name)
            case ["device" | "log" as name]:
                panels[name].toggle()
                self.checkedChanged.emit()
            case ["device" | "log" as name, "place", place]:
                panels[name].setPlace(place)
                panels[name].setShown(True)
                self.checkedChanged.emit()
            case ["labels"]:
                self.setRailLabels(not self._labels)
            case ["theme", mode]:
                assert self.theme is not None
                self.theme.setMode(mode)
            case ["zoom", "in"]:
                self.zoom_to(zoom_step(self.zoom, 1))
            case ["zoom", "out"]:
                self.zoom_to(zoom_step(self.zoom, -1))
            case ["zoom", "reset"]:
                self.zoom_to(1.0)
            case ["zoom", *level]:
                self.zoom_to(float(".".join(level)))
            case ["docs"]:
                QDesktopServices.openUrl(QUrl(docs.DOCS_URL))
            case ["keys"]:
                self.keysRequested.emit()

    @pyqtSlot(bool)
    def setRailLabels(self, shown: bool) -> None:
        if shown != self._labels:
            self._labels = shown
            save_rail_labels(shown)
            self.railLabelsChanged.emit()
            self.checkedChanged.emit()

    def _keys_content(self) -> Content:
        """The keys of the window, under the menus: those of the menus, the lists and the device."""

        def keys(menu_id: str) -> tuple[tuple[str, str], ...]:
            menu = next(item for item in self.menu_data if item["id"] == menu_id)
            return tuple(
                (", ".join(native(key) for key in item["keys"]), item["text"].replace("&", ""))
                for item in flat(menu["entries"])
                if item["keys"]
            )

        from xtouch_daemon.gui.qt.fields.popover import Entry

        return Content(
            "Keyboard shortcuts",
            [
                Entry("Window", items=keys("file") + keys("view") + keys("help")),
                Entry("Edit", text=KEYS_EDIT, items=keys("edit")),
                Entry("Lists", items=KEYS_LISTS),
                Entry("Device", items=KEYS_DEVICE),
            ],
        )

    # -- pages ----------------------------------------------------------------------------------------------------

    def _page_backend(self, name: str) -> QObject | None:
        return {
            "slots": self.app.slots,
            "channels": self.app.channels,
            "states": self.app.states,
            "settings": self.app.settings,
        }.get(name)

    def _page_changed(self) -> None:
        """The page shown changed: the Edit menu works on its list."""
        page = self._page_backend(self.app.page)
        editable: list[str] = list(page.property("editable") or []) if page is not None else []
        if editable != self._editable:
            self._editable = editable
            self.editableChanged.emit()
            self._set_disabled()

    @pyqtSlot(str)
    def showPage(self, name: str) -> None:
        """Shows a page of the rail, or a section of the settings (the page Settings at that section)."""
        if name in SETTINGS:
            self.app.showPage("settings")
            show = getattr(self.app.settings, "showSection", None)
            if show is not None:
                show(name)
            return
        self.app.showPage(name)

    def show_slot(self, slot: int) -> None:
        """The slot (1 for the leftmost one) on the page Slots."""
        self.app.slots.selectSlot(slot)  # pyright: ignore[reportAttributeAccessIssue]
        self.app.showPage("slots")

    def go_to(self, problem: Problem) -> None:
        """Shows the page of the problem (see `place_of`), at the option the problem is about."""
        place = place_of(problem)
        if place is None:
            return
        if place.slot is not None:
            self.show_slot(place.slot)
            return
        self.showPage(place.page)
        page = self._page_backend("settings" if place.page in SETTINGS else place.page)
        if page is not None:
            page.reveal(list(problem.path))  # pyright: ignore[reportAttributeAccessIssue]

    @pyqtSlot(int)
    def pickProblem(self, index: int) -> None:
        """An entry of the list of problems: an unknown option is removed, any other is shown."""
        problem = self._problems[index]
        if problem.kind == "extra_forbidden":
            self.editor.unset(problem.path)
        else:
            self.go_to(problem)

    @staticmethod
    def _problem_text(problem: Problem) -> str:
        if problem.kind == "extra_forbidden":
            return f"{problem.location}: unknown option, click to remove it"
        return str(problem) if problem.path else problem.message

    @pyqtSlot(str)
    def edit(self, action: str) -> None:
        """Does an action of the Edit menu to the entry picked in the list of the page shown."""
        page = self._page_backend(self.app.page)
        if page is not None and action in self._editable:
            page.edit(action)  # pyright: ignore[reportAttributeAccessIssue]

    # -- the document ---------------------------------------------------------------------------------------------

    def _document_changed(self, change: Change) -> None:
        """The document changed (see `Change`): the title, the problems and what can be done show anew."""
        if change.scope is not Scope.FILE:
            # what the window said was about the document before
            self._bar_restart = False
            self.tell("")
        self._problems = list(self.validation.problems)
        self.problemsChanged.emit()
        mark = "• " if self.document.modified else ""
        new = " (new)" if not self.document.exists else ""
        title = f"{mark}{self.document.path.name}{new}"
        if title != self._title:
            self._title = title
            self.titleChanged.emit()
        for page in (self.app.slots, self.app.channels, self.app.states, self.app.settings):
            show = getattr(page, "show_document", None)
            if show is not None:
                show(change)
        self.live_preview.document_changed()
        self.refresh_preview()

    _bar_restart = False

    @pyqtSlot()
    def undo(self) -> None:
        if self.editor.undo():
            self.tell(messages.UNDONE)

    @pyqtSlot()
    def redo(self) -> None:
        if self.editor.redo():
            self.tell(messages.REDONE)

    def move_slot(self, source: int, target: int) -> None:
        """A strip was dragged to another place: its slot moves there, and stays picked."""
        self.editor.move_slot(source, target)
        self.tell(messages.slot_moved(source, target))
        self.app.slots.selectSlot(target)  # pyright: ignore[reportAttributeAccessIssue]

    # -- the preview and the footer -------------------------------------------------------------------------------

    def _savable(self) -> bool:
        """
        "Save and apply" while there is something to save, or the daemon runs another version of the file (e.g. one
        changed outside the GUI): then it only reloads the daemon.
        """
        saved = self.document.saved_config if self.document.exists else None
        stale = not self.applying.isActive() and runs_older(self.daemon, self.live.snapshot, self.document.path, saved)
        return self.validation.config is not None and (self.document.modified or not self.document.exists or stale)

    def _device_simulates(self, snapshot: Snapshot | None) -> bool:
        """Whether the device shows the situation of Simulate of this window."""
        preview = self.live_preview
        return preview.on and preview.simulating and snapshot is not None and snapshot.simulated

    def previewing(self) -> bool:
        """Whether the drawing shows a preview of this window: on its twin, or on the device."""
        preview = self.live_preview
        snapshot = self.live.snapshot
        on_device = previewed(snapshot, self.validation.config, preview.running) or self._device_simulates(snapshot)
        return preview.in_gui or (preview.on and on_device)

    @pyqtSlot(str)
    def setPlace(self, place: str) -> None:
        """The control Preview: where the changes show (`gui`, `device`, `off`)."""
        self.live_preview.set_place(Place(place))

    def situation_changed(self) -> None:
        """Simulate started, changed or ended on the page Slots: the preview follows, where it shows."""
        self.live_preview.set_situation(getattr(self.app.slots, "what_if", None))

    def refresh_preview(self) -> None:
        """Shows the device (live while the daemon tells what it shows), whether it runs the file, and the footer."""
        snapshot = self.live.snapshot
        if self.trying is not None and offers_virtual_device(snapshot, self.hosted is not None):
            # the daemon started to try without a device waits for its device: here it is
            self.open_virtual_device()
        preview = self.live_preview
        device_reason = unavailable(self.daemon, snapshot, self.document.path, self.live.owned)
        gui_reason = twin_unavailable(snapshot, self.live.owned)
        if device_reason is not None and preview.place == Place.DEVICE:
            preview.set_place(Place.GUI)
        elif self.resume_place is not None and (device_reason is None or self.resume_place != Place.DEVICE):
            place, self.resume_place = self.resume_place, None
            preview.set_place(place)
        shows_document = previewed(snapshot, self.validation.config, preview.running)
        saved = self.document.saved_config
        device = saved.device.name if saved is not None else "the device"
        changes = changes_status(
            self.daemon,
            snapshot,
            self.document.path,
            saved if self.document.exists else None,
            self.document.modified,
            self.applying.isActive(),
            shows_document and self.document.modified,
            preview.on,
            self.validation.config is None,
            self._device_simulates(snapshot),
            preview.place.value,
            getattr(self.app.slots, "what_if", None) is not None,
        )
        self.changes = changes
        self._controls.show_state(self.daemon, snapshot)
        self._controls.show_connections(connections(snapshot, device))
        reasons = {Place.GUI: gui_reason, Place.DEVICE: device_reason, Place.OFF: None}
        places = [
            {
                "id": place.value,
                "text": text,
                "enabled": reasons[place] is None,
                "checked": place == preview.place,
                "tip": PLACE_TIPS[place] if reasons[place] is None else f"{reasons[place].why}\n\n{PLACE_TIPS[place]}",  # pyright: ignore[reportOptionalMemberAccess]
            }
            for place, text in PLACE_TEXTS.items()
        ]
        message = f"The preview keeps the version before: {preview.error}" if preview.error else preview.notice
        bar = {
            "audio": self.audio_pill,
            "changes": {"text": changes.text, "tone": changes.tone.value, "tip": _more(changes.tip)},
            "previewShown": preview.wanted or preview.running,
            "places": places,
            "message": message or "",
            "restart": self._bar_restart and self.daemon is not None and self.daemon.systemd,
        }
        self._show_bar(bar)
        self._set_disabled()
        self.changes_details.refresh_if_open()
        self.previewChanged.emit()
        self._show_pages(snapshot)

    def _show_pages(self, snapshot: Snapshot | None) -> None:
        """Gives the pages what the daemon tells now (the widgets' `MainWindow.refresh_preview` did the same)."""
        if not self._started:
            return
        self.app.slots.show_place(self.placeText)  # pyright: ignore[reportAttributeAccessIssue]
        self.app.slots.show_live(snapshot)  # pyright: ignore[reportAttributeAccessIssue]
        self.app.settings.show_live(snapshot)  # pyright: ignore[reportAttributeAccessIssue]
        for page in (self.app.channels, self.app.states):
            show = getattr(page, "show_live", None)
            if show is not None:
                show(snapshot)

    def _twin_changed(self) -> None:
        """The virtual twin of the preview shows something new: the cards show it too, while they show the twin."""
        if self._started:
            self.app.slots.show_live(self.live.snapshot)  # pyright: ignore[reportAttributeAccessIssue]

    def _send(self, request: Request) -> None:
        """What the forms send to the daemon."""
        self.live.send(request)

    def _wire_pages(self) -> None:
        """Tells the pages what they reach outside of themselves: the daemon, the twin, the sound server."""
        from xtouch_daemon.gui.quick.forms.context import forms_of
        from xtouch_daemon.gui.quick.pages.slots import Live

        context = forms_of(self.app)
        context.snapshot = lambda: self.live.snapshot
        context.known = lambda: self.live.known
        context.send = self._send
        if self.app.deps.session is not None:
            # a new zoom goes on with what the last window read
            context.set_audio(self.audio)
        if not isinstance(self.app.deps.extra.get("slots_live"), Live):
            self.app.slots.live = Live(  # pyright: ignore[reportAttributeAccessIssue]
                snapshot=lambda: self.live.snapshot,
                request=self.live.send,
                twin_slots=lambda: self.live.twin.slots if self.live.twin is not None else None,
                simulate_unavailable=lambda: twin_unavailable(self.live.snapshot, self.live.owned),
                shows_twin=lambda: self.live_preview.in_gui,
                audio=lambda: self.audio,
            )
        self.app.slots.simulated.connect(self.situation_changed)  # pyright: ignore[reportAttributeAccessIssue]
        self.live.twin_changed.connect(lambda _view: self._twin_changed())

    def _show_bar(self, bar: dict[str, Any]) -> None:
        if bar != self._bar:
            self._bar = bar
            self.barChanged.emit()

    def drawing_status(self) -> Status:
        """What the drawing of the device says about what it shows (for the pill of the drawing)."""
        snapshot = self.live.snapshot
        preview = self.live_preview
        saved = self.document.saved_config
        device = saved.device.name if saved is not None else "the device"
        hosting = self.hosted is not None
        shows_document = previewed(snapshot, self.validation.config, preview.running)
        on_device = preview.on and (shows_document or self._device_simulates(snapshot))
        return drawing_status(preview_status(self.daemon, snapshot, device, hosting), preview.in_gui, on_device)

    def slots_status_text(self) -> Any:
        return slots_status(self.live.snapshot)

    def device_offer(self) -> DeviceOffer | None:
        """What the window offers while the device is plugged in and the daemon drives the virtual one."""
        saved = self.document.saved_config
        device = saved.device.name if saved is not None else "the device"
        file_virtual = saved is not None and saved.device.virtual
        return device_offer(self.live.snapshot, device, file_virtual, self.trying is not None)

    def _changes_content(self) -> Content:
        """What the device runs, and the file: its path, to copy or to open its folder."""
        from xtouch_daemon.gui.qt.fields.popover import Entry

        if self.changes is None:
            return Content("Configuration")
        path = self.document.path
        clipboard = QGuiApplication.clipboard()
        assert isinstance(clipboard, QClipboard)
        entries = [
            # the pill clicked says it already: what it means, in the color of its tone
            Entry("Device", Status("", self.changes.tone), self.changes.tip),
            Entry(
                "File",
                path=str(path),
                actions=(
                    ("Copy the path", lambda: clipboard.setText(str(path))),
                    ("Open the folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))),
                ),
            ),
        ]
        if self.daemon is not None and self.daemon.config != path.resolve():
            entries.append(
                Entry(
                    "Daemon's file",
                    Status("another file", Tone.WARN),
                    "Save and apply writes this file, which the daemon does not read.",
                    path=str(self.daemon.config),
                )
            )
        return Content("Configuration", entries)

    # -- the sound server -----------------------------------------------------------------------------------------

    def load_audio(self) -> None:
        self.audio_pill = {"text": "Reading the sound server…", "tone": "neutral", "tip": "", "parts": []}
        self._show_bar({**self._bar, "audio": self.audio_pill})
        self.loader.load()

    def _audio_loaded(self, state: AudioState) -> None:
        self.audio = state
        self.audio_error = None
        summary = sources.summary(state)
        tip = f"What the GUI read from the sound server: {summary}, the names the forms suggest."
        self.audio_pill = {
            "text": "Sound server",
            "tone": Tone.NEUTRAL.value,
            "tip": _more(tip),
            "parts": [{"icon": AUDIO_ICONS[thing], "count": str(number)} for thing, number in sources.counts(state)],
            "name": f"Sound server: {summary}",
        }
        self._audio_done()

    def _audio_failed(self, message: str) -> None:
        self.audio = DISCONNECTED
        self.audio_error = message
        self.audio_pill = {
            "text": "Sound server not reachable: type names by hand",
            "tone": Tone.WARN.value,
            "tip": _more(message),
            "parts": [],
            "name": "",
        }
        self._audio_done()

    def _audio_done(self) -> None:
        if self._started:
            from xtouch_daemon.gui.quick.forms.context import forms_of

            forms_of(self.app).set_audio(self.audio)
        self.audioChanged.emit()
        self.audio_details.refresh_if_open()
        self.refresh_preview()

    def _audio_content(self) -> Content:
        """What the GUI read from the sound server, or why it couldn't, and reading it again (it stays open)."""
        from xtouch_daemon.gui.qt.fields.popover import Entry

        again = (("Read again", self.load_audio),)
        if self.audio_error is not None:
            entry = Entry(
                "",
                Status("not reachable", Tone.WARN),
                f"{self.audio_error}\n\nThe forms suggest no names meanwhile: type them by hand.",
            )
            return Content("Sound server", [entry], actions=again)
        intro = (
            "The names the forms suggest for `device` and `match`. The GUI reads them itself: the daemon's own "
            "connection to the sound server is in the pill of the service."
        )
        entries = [
            Entry(
                kind,
                Status(str(len(items)), Tone.GOOD if items else Tone.NEUTRAL),
                "" if items else "None.",
                items=items,
                icon=AUDIO_ICONS[thing],
            )
            for (kind, items), (thing, _) in zip(sources.contents(self.audio), sources.counts(self.audio), strict=True)
        ]
        return Content("Sound server", entries, intro, again)

    # -- the service ----------------------------------------------------------------------------------------------

    def _runtime_changed(self, _directory: str) -> None:
        """Something changed in the directory of the live view: the daemon may have started or stopped."""
        there = self.live.path.exists()
        if there != self._live_socket_there:
            self._live_socket_there = there
            self.refresh_service()

    @pyqtSlot()
    def refresh_service(self) -> None:
        """Finds the daemon (and its live view) and the state of the service again."""
        self.daemon = self.find_daemon()
        if self.daemon is None:
            self.live.disconnect_from_daemon()
        else:
            self.live.connect_to_daemon()
        self.refresh_preview()

    @pyqtSlot()
    def restart_service(self) -> None:
        """The button Restart the service of the footer (after a save that needs a restart)."""
        self._restart()

    def _restart(self) -> None:
        self._bar_restart = False
        try:
            self.service.restart()
        except ServiceError as e:
            self.asker.tell("Service", str(e))
            self.refresh_preview()
            return
        self.tell(messages.RESTARTING)
        self.refresh_service()

    # -- the file -------------------------------------------------------------------------------------------------

    @pyqtSlot(result=bool)  # pyright: ignore[reportArgumentType]
    def save(self) -> bool:
        """Saves and applies the configuration; False when it could not be saved."""
        if self.validation.config is None:
            self.asker.tell("Not saved", "Fix the problems first: the daemon would not take the file.")
            return False
        if not self._savable():
            # nothing changed
            return True
        restart_sections = self.document.restart_sections
        if self.document.modified or not self.document.exists:
            if self.document.changed_on_disk() and not self._overwrite():
                return False
            try:
                self.document.save()
            except (OSError, ConfigError) as e:
                self.asker.tell("Saving failed", str(e))
                return False
        # else the file is saved: the daemon runs another version of it and is only reloaded
        # the daemon loads the file (also one it is not told to reload: it watches the file during a preview)
        self.live_preview.saved()
        try:
            applied = apply(self.daemon, self.document.path, restart_sections)
        except OSError as e:
            # e.g. it ended a moment ago
            assert self.daemon is not None
            self.tell(f"Saved, but reloading {describe(self.daemon)} failed: {e}")
        else:
            self.tell(applied.message)
            if applied.reloaded:
                self.applying.start()
            # the window restarts only the service
            self._bar_restart = applied.restart_needed
        self.editor.saved()
        self.refresh_service()
        return True

    @pyqtSlot()
    def revert(self) -> None:
        if self.reload():
            self.tell(messages.REVERTED)

    @pyqtSlot(result=bool)  # pyright: ignore[reportArgumentType]
    def reload(self) -> bool:
        """Reads the file again, one step to undo; False (and the bar says why) while it can't be read."""
        try:
            self.editor.revert()
        except ConfigError as e:
            self._show_disk(messages.disk_unreadable(e))
            return False
        self._show_disk("")
        return True

    @pyqtSlot()
    def keepMine(self) -> None:
        """Goes on with the changes here: the next save overwrites the file on disk without asking."""
        self.document.overrule()
        self._show_disk("")
        self.editor.saved()

    def _file_changed(self) -> None:
        """
        Something happened to the file on disk. Another text than the window read: without unsaved changes it reads
        it again, with them the bar asks (Reload or Keep mine). The window's own saves are no change.
        """
        if not self.document.changed_on_disk():
            # e.g. the file is back to what the window read
            self._show_disk("")
            return
        if self.document.modified:
            self._show_disk(messages.DISK_CHANGED)
        elif self.reload():
            self.tell(messages.RELOADED)

    def _show_disk(self, message: str) -> None:
        if message != self._disk:
            self._disk = message
            self.diskChanged.emit()

    def _overwrite(self) -> bool:
        """The file changed on disk since it was read: whether to overwrite it (Reload reads it instead)."""
        answer = self.asker.ask(
            "The file changed on disk",
            "Someone else changed the file since the window read it. Overwrite it with the changes here?",
            OVERWRITE_RELOAD_CANCEL,
        )
        if answer == RELOAD:
            self.reload()
        return answer == OVERWRITE

    # -- zoom -----------------------------------------------------------------------------------------------------

    def zoom_to(self, zoom: float) -> None:
        """Closes the window for a new one at `zoom` (see `Session`), keeping everything that is not saved."""
        if zoom == self.zoom:
            return
        save_zoom(zoom)
        self.rezoom = zoom
        self.closeRequested.emit()

    def session(self) -> Session:
        """What the next window needs to go on where this one is."""
        window = self.window
        assert window is not None
        maximized = window.visibility() == QQuickWindow.Visibility.Maximized
        geometry = self._normal if maximized and self._normal is not None else window.geometry()
        return Session(
            history=self.history,
            page=self.app.page,
            geometry=to_screen(geometry, window.devicePixelRatio()),
            maximized=maximized,
            audio=self.audio,
            preview=self.live_preview.place.value,
            trying=self.trying,
        )

    def _remember_geometry(self) -> None:
        window = self.window
        if window is not None and window.visibility() == QQuickWindow.Visibility.Windowed:
            self._normal = window.geometry()

    def _restore_size(self, window: QQuickWindow) -> None:
        from PyQt6.QtCore import QSettings

        size = QSettings().value("window/size")
        try:
            width, height = (int(part) for part in str(size).split("x"))
        except ValueError:
            return
        screen = window.screen()
        room = screen.availableGeometry() if screen is not None else None
        if room is not None:
            width, height = min(width, room.width()), min(height, room.height())
        window.resize(max(width, MINIMUM_WINDOW[0]), max(height, MINIMUM_WINDOW[1]))

    def _save_size(self) -> None:
        from PyQt6.QtCore import QSettings

        window = self.window
        if window is not None and window.visibility() == QQuickWindow.Visibility.Windowed:
            QSettings().setValue("window/size", f"{window.width()}x{window.height()}")

    # -- the trial daemon and the virtual device ------------------------------------------------------------------

    def try_without_device(self) -> None:
        """
        Starts a daemon with the virtual device on this file (saved first if it is new), and opens the device in the
        window once the daemon waits for it (see `refresh_preview`).
        """
        if self.trying is not None:
            return
        if not self.document.exists and not self.save():
            return
        self._keep_trying(self.launch_trial(self.document.path))
        self.tell(messages.TRIAL_STARTING)

    def _keep_trying(self, process: QProcess) -> None:
        """The daemon to try without a device is this window's: it ends with it."""
        process.setParent(self)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self._trying_ended = process.finished.connect(lambda code, _status: self._tried(process, code))
        self.trying = process

    def _tried(self, process: QProcess, code: int) -> None:
        if self.trying is not process:
            return
        self.trying = None
        process.deleteLater()
        if self.restarting_trial:
            self.restarting_trial = False
            self._keep_trying(self.launch_trial(self.document.path))
            self.tell(messages.TRIAL_AGAIN)
            return
        self.tell(messages.trial_ended(code))
        self.refresh_service()

    def restart_daemon(self) -> None:
        """
        The daemon that drives the hosted virtual device stops and starts again, so its shutdown and startup sequences
        show on it: the daemon of "Try without a device", or the service.
        """
        if self.trying is not None:
            self.restarting_trial = True
            self.trying.terminate()
            self.tell(messages.TRIAL_STOPPING)
            return
        self._restart()

    def restart_reason(self) -> str | None:
        """Why `restart_daemon` can't restart the daemon, None when it can."""
        if self.trying is not None:
            return None
        if self.daemon is None:
            return "No daemon runs now."
        if not self.daemon.systemd:
            return f"This daemon runs outside the service (process {self.daemon.pid}): restart it where it runs."
        return None

    def use_virtual_device(self) -> None:
        """
        For a daemon that finds no device: `[device] virtual = true`, saved (the daemon takes it when it reloads,
        without a restart), and the virtual device opened here.
        """
        if self.daemon is None or self.document.path.resolve() != self.daemon.config:
            self.tell("The daemon reads another file: set Virtual on the page Extender of that one.")
            return
        self.document.set(("device", "virtual"), True)
        self.editor.edited(Change(Scope.VALUE, ("device", "virtual")))
        if self.save():
            self.open_virtual_device()

    def open_virtual_device(self) -> None:
        """Hosts the virtual device, for a daemon that waits for it: the mouse on the drawing is a hand on it."""
        if self.hosted is not None:
            return
        hosted = HostedDevice(self.virtual_socket, self)
        try:
            hosted.start()
        except (AlreadyServed, OSError) as e:
            hosted.deleteLater()
            self.asker.tell("Virtual device", str(e))
            return
        self.hosted = hosted
        hosted.changed.connect(self.hostedChanged)
        self.hostedChanged.emit()
        self.refresh_preview()
        self.virtualDeviceOpened.emit()

    def close_virtual_device(self) -> None:
        """Unplugs the hosted virtual device and closes it."""
        hosted, self.hosted = self.hosted, None
        if hosted is None:
            return
        hosted.stop()
        hosted.deleteLater()
        self.hostedChanged.emit()
        self.refresh_preview()

    def switch_to_device(self) -> None:
        """
        The device is plugged in while the daemon drives the virtual one: the daemon goes to the device. With
        `[device] virtual` in the file, it is turned off and the file applied (no restart); the daemon of the window,
        to try without a device, ends instead (the service, started then, takes the device).
        """
        offer = self.device_offer()
        if offer is None:
            return
        match offer.switch:
            case Switch.TRIAL:
                # ended on purpose: not the message of a daemon that ended (`_tried`)
                trying, self.trying = self.trying, None
                assert trying is not None
                trying.finished.connect(trying.deleteLater)
                trying.terminate()
                self.tell(messages.TRIAL_ENDING)
                self.refresh_service()
            case Switch.FILE:
                if self.daemon is None or self.document.path.resolve() != self.daemon.config:
                    self.tell("The daemon reads another file: turn Virtual off on its page Extender.")
                    return
                if self.document.modified:
                    question = "Switching saves the file: your other changes too. Save them and switch to the device?"
                    if self.asker.ask("Switch to the device", question, YES_NO) != YES:
                        return
                self.document.unset(("device", "virtual"))
                self.editor.edited(Change(Scope.VALUE, ("device", "virtual")))
                if self.save():
                    self.close_virtual_device()
            case Switch.RESTART:
                # nothing the window can do: the bar says so
                return

    # -- closing --------------------------------------------------------------------------------------------------

    @pyqtSlot(result=bool)  # pyright: ignore[reportArgumentType]
    def closeAllowed(self) -> bool:
        """
        QML asks when the window is closed: with unsaved changes (and no new zoom, which takes them along) it asks
        what to do with them; False keeps the window. True ends what the window started.
        """
        if self.document.modified and self.rezoom is None:
            question = "Save the changes before closing?"
            if self.live_preview.running and self.live_preview.on:
                question += (
                    " The device runs them now (Preview: On the device): without saving, it goes back to the file."
                )
            answer = self.asker.ask("Unsaved changes", question, SAVE_DISCARD_CANCEL)
            if answer == "cancel" or (answer == SAVE and not self.save()):
                self.rezoom = None
                return False
        self.shutdown()
        return True

    def shutdown(self) -> None:
        """Ends what the window started: the preview goes back to the file, the trial daemon ends or goes on."""
        if self.rezoom is not None:
            self.last_session = self.session()
        # back to the file (the daemon would notice the closed connection too); after a new zoom the next window
        # previews again (see `Session`)
        self.live_preview.stop()
        self.close_virtual_device()
        self.timer.stop()
        self.loader.stop()
        self._save_size()
        if self.hover is not None:
            self.hover.stop()
        app = QGuiApplication.instance()
        if app is not None:
            app.removeEventFilter(self.undo_keys)
        if self.trying is not None and self.rezoom is not None:
            # the next window takes it over (see `session()`): its end is no longer this window's
            self.trying.finished.disconnect(self._trying_ended)
            self.trying.setParent(None)  # pyright: ignore[reportArgumentType]
        elif self.trying is not None:
            trying, self.trying = self.trying, None
            trying.terminate()
            trying.waitForFinished(3000)


def _more(tip: str) -> str:
    """The tip of a pill that opens a popover: its first paragraph, and that a click tells more."""
    return f"{tip.split(chr(10) * 2)[0]}\n\nClick for details."
