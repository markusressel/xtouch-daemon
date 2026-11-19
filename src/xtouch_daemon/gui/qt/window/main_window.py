"""
The main window (its title: the file, • with unsaved changes). From the top: the menus; the service; the window Device
and the window Configuration (docked one above the other at first; each can go to any side, or be a window of its
own), which has a rail of the pages (Slots, Channels, States, Settings) and the page; at the bottom the problems, undo
and saving.
"""

import sys
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QProcess, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QClipboard,
    QCloseEvent,
    QDesktopServices,
    QKeySequence,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.domain import broker, docs, sources
from xtouch_daemon.gui.domain.apply import apply, describe
from xtouch_daemon.gui.domain.changes import EVERYTHING, Change, Scope
from xtouch_daemon.gui.domain.connections import connections
from xtouch_daemon.gui.domain.history import History
from xtouch_daemon.gui.domain.live_preview import Place, previewed, unavailable
from xtouch_daemon.gui.domain.problems import place_of
from xtouch_daemon.gui.domain.slots import slots_status
from xtouch_daemon.gui.domain.slots_document import SlotsDocument, Validation
from xtouch_daemon.gui.domain.status import (
    Status,
    Tone,
    changes_status,
    drawing_status,
    offers_virtual_device,
    preview_status,
    runs_older,
)
from xtouch_daemon.gui.domain.twin import unavailable as twin_unavailable
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import ElidedLabel, flat_button, label, refresh_help, show_status
from xtouch_daemon.gui.qt.fields.popover import Entry, make_clickable, show_popover
from xtouch_daemon.gui.qt.file_watch import FileWatch
from xtouch_daemon.gui.qt.live_preview import LivePreview
from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.gui.qt.pages.aliases import AliasesPage
from xtouch_daemon.gui.qt.pages.base import SETTINGS_PAGES, Page
from xtouch_daemon.gui.qt.pages.channels import ChannelsPage
from xtouch_daemon.gui.qt.pages.sections import (
    BrokerTest,
    BrokerTester,
    MqttPage,
    MumbleInstaller,
    SectionPage,
    VoipPage,
)
from xtouch_daemon.gui.qt.pages.slots import SlotsPanel
from xtouch_daemon.gui.qt.pages.states import StatesPage
from xtouch_daemon.gui.qt.remote_hand import RemoteHand
from xtouch_daemon.gui.qt.theme.icons import app_icon, refresh_icons, set_icon
from xtouch_daemon.gui.qt.theme.settings import (
    ZOOM_LEVELS,
    load_window_state,
    load_zoom,
    save_window_state,
    save_zoom,
    zoom_step,
    zoom_text,
)
from xtouch_daemon.gui.qt.theme.style import apply_theme, current_mode, set_role
from xtouch_daemon.gui.qt.theme.tokens import Space, ThemeMode
from xtouch_daemon.gui.qt.virtual_device import HostedDevice
from xtouch_daemon.gui.qt.window.audio_loader import AudioLoader
from xtouch_daemon.gui.qt.window.device_view import DeviceView
from xtouch_daemon.gui.qt.window.hover_tips import HoverTips
from xtouch_daemon.gui.qt.window.input_filter import InputFilter
from xtouch_daemon.gui.qt.window.rail import RAIL_PAGES, RAIL_TITLES, Rail, SettingsPages
from xtouch_daemon.gui.qt.window.service import ServiceControls
from xtouch_daemon.gui.qt.window.session import Session, from_screen, to_screen
from xtouch_daemon.live.messages import Snapshot
from xtouch_daemon.simulator.server import AlreadyServed
from xtouch_daemon.system import instance
from xtouch_daemon.system.instance import Instance
from xtouch_daemon.system.systemd import (
    Service,
    ServiceError,
)

SERVICE_POLL_MS = 3000
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
APPLY_GRACE_MS = 2000
"""How long a reload may take before the window says that the daemon did not take the file."""
LOGO_SIZE = 44
"""The size of the icon of the project in the header, next to the title."""
WINDOW_SIZE = (1280, 1000)
"""The size of the window when it opens, where the screen has room for it."""
DEVICE_HEIGHT = 380
"""The height of the window Device above the page, until it is made larger or smaller."""


class MainWindow(QMainWindow):
    def __init__(
        self,
        document: SlotsDocument,
        service: Service,
        read_audio: Callable[[], AudioState],
        find_daemon: Callable[[], Instance | None] = instance.running,
        live_socket: Path | None = None,
        try_broker: BrokerTest = broker.try_broker,
        session: Session | None = None,
        mumble_installer: MumbleInstaller | None = None,
        virtual_socket: Path | None = None,
    ):
        """
        `live_socket` is where the daemon serves its live view, by default `instance.socket_file()`. `try_broker` tries
        the settings of the [mqtt] section, `mumble_installer` sets up the Mumble plugin (page of [voip]).
        `virtual_socket` is where the virtual device waits for the daemon when the GUI hosts it, by default
        `instance.virtual_device_socket_file()`.
        """
        super().__init__()
        self.try_broker = try_broker
        self.mumble_installer = mumble_installer or MumbleInstaller()
        self.zoom = load_zoom()
        self.rezoom: float | None = None
        """The zoom the next window gets: set when this one closes for a new zoom (see `Session`)."""
        self.editor = Editor(document, session.history if session is not None else None)
        """The document, its history and validation: what everything shows."""
        self.service = service
        self.find_daemon = find_daemon
        self.daemon: Instance | None = None
        self.audio = DISCONNECTED
        self.setWindowTitle("X-Touch Extender")
        # at most the room of the screen: a larger window is made smaller by the desktop right after it shows
        room = self.screen().availableGeometry()  # pyright: ignore[reportOptionalMemberAccess]
        self.resize(min(WINDOW_SIZE[0], room.width()), min(WINDOW_SIZE[1], room.height()))
        self.applying = QTimer(self)
        """Runs for a moment after a reload, while the daemon takes the file."""
        self.applying.setSingleShot(True)
        self.applying.setInterval(APPLY_GRACE_MS)
        self.applying.timeout.connect(self.refresh_preview)
        self.virtual_socket = virtual_socket or instance.virtual_device_socket_file()
        self.hosted: HostedDevice | None = None
        """The virtual device while the GUI hosts it (see `open_virtual_device()`)."""
        self.live = LiveView(live_socket or instance.socket_file(), self)
        self.live.changed.connect(lambda _: self.refresh_preview())
        self.live_preview = LivePreview(self.live, document)
        self.live_preview.changed.connect(self.refresh_preview)
        self.shown = False
        """Whether the window was shown: the first time the keys go to the strips."""
        self.trying: QProcess | None = None
        """The daemon started by "Try without a device", with the virtual device; it ends with the window."""
        if session is not None and session.trying is not None:
            self._keep_trying(session.trying)
        self.resume_place = Place(session.preview) if session is not None else None
        """Where the preview showed in the window before the zoom: it goes there once it can."""

        root = QWidget()
        body = QVBoxLayout(root)
        body.setContentsMargins(Space.XL, Space.L, Space.XL, 0)
        body.setSpacing(Space.S)
        body.addLayout(self._preview_status())
        self.preview_message = label("", "error", wrap=True)
        """What the daemon said about the live preview: why it did not take the latest change, or why it ended."""
        self.preview_message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_message.hide()
        body.addWidget(self.preview_message)
        body.addWidget(self._disk_bar())
        body.addWidget(self._pages(), 1)
        configuration = QWidget()
        editor = QHBoxLayout(configuration)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setSpacing(0)
        self.rail = Rail()
        """The pages on the left of the window Configuration."""
        self.rail.picked.connect(self.show_page)
        self.rail_buttons = self.rail.buttons
        editor.addWidget(self.rail)
        editor.addWidget(root, 1)
        # the docks have all the room: a main window needs a central widget, this one takes none
        placeholder = QWidget()
        placeholder.setMaximumSize(0, 0)
        self.setCentralWidget(placeholder)
        # hidden, it leaves no handle between it and the docks either
        placeholder.hide()
        # the header and the footer reach across the window, the docks are between them
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._bar("header", self._header()))
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self._bar("footer", self._footer()))
        self.device_dock = self._device_dock()
        self.configuration_dock = self._configuration_dock(configuration)
        self._menus()
        # the menus of the window list its docks and bars: the menu View has the dock, the bars always show
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        state = load_window_state()
        if state is not None:
            self.restoreState(state)
        else:
            # most of the height is for the page
            self.resizeDocks([self.device_dock], [DEVICE_HEIGHT], Qt.Orientation.Vertical)
        app = QApplication.instance()
        assert app is not None
        self.input_filter = InputFilter()
        """The document's undo also while a text field has the focus, the wheel on the page rather than in a field."""
        app.installEventFilter(self.input_filter)
        # Cut, Copy, Paste ... follow the focus: for the list of a page, not for a field
        app.focusChanged.connect(self._focus_changed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_service)
        self.timer.start(SERVICE_POLL_MS)
        self.loader = AudioLoader(read_audio)
        self.loader.loaded.connect(self._audio_loaded)
        self.loader.failed.connect(self._audio_failed)
        self.editor.changed.connect(self._document_changed)
        self.file_watch = FileWatch(document.path, self)
        """Changes of the file on disk by someone else (see `_file_changed`)."""
        self.file_watch.changed.connect(self._file_changed)
        self.load_audio()
        self.refresh_service()
        self._document_changed(EVERYTHING)
        self.show_page("slots")
        if session is not None:
            self._resume(session)

    def showEvent(self, event: QShowEvent | None) -> None:
        super().showEvent(event)
        if not self.shown:
            self.shown = True
            # the keys start on the strips (the arrows pick one), not on the first button of the header
            self.device_view.preview.strips[0].setFocus()

    @property
    def document(self) -> SlotsDocument:
        return self.editor.document

    @property
    def history(self) -> History[SlotsDocument]:
        return self.editor.history

    @property
    def validation(self) -> Validation:
        return self.editor.validation

    def _resume(self, session: Session) -> None:
        """Goes on where the window before the zoom left off."""
        self.audio = session.audio
        self.show_page(session.page)
        self.setGeometry(from_screen(session.geometry, self.devicePixelRatioF()))
        if session.maximized:
            self.setWindowState(Qt.WindowState.WindowMaximized)
        self.refresh_preview()

    # -- building -------------------------------------------------------------------------------------------------

    def _header(self) -> QWidget:
        header = QWidget()
        set_role(header, "bar")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(Space.XL, Space.M, Space.L, Space.M)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(QSize(LOGO_SIZE, LOGO_SIZE)))
        layout.addWidget(logo)
        layout.addSpacing(Space.S)
        # the file is in the title of the window and the tip of the pill next to Save
        layout.addWidget(label("X-Touch Extender", "title"))
        layout.addStretch(1)
        layout.addSpacing(Space.L)
        self.service_controls = ServiceControls(self.service)
        self.service_controls.changed.connect(self.refresh_service)
        # the status line comes later, with the footer
        self.service_controls.told.connect(lambda text: self.status.setText(text))
        self.service_controls.settings_asked.connect(self.show_page)
        layout.addWidget(self.service_controls)
        return header

    def _preview_control(self) -> QWidget:
        """
        "Preview", next to Save and apply: where the changes in the editor (and Simulate) show before they are saved.
        In the GUI (on a twin in the daemon), on the device, or Off (the drawing shows the device as it is). Only there
        while there is something to preview.
        """
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, Space.S, 0)
        layout.setSpacing(0)
        self.preview_label = label("Preview", "hint")
        layout.addWidget(self.preview_label)
        layout.addSpacing(Space.S)
        self.place_group = QButtonGroup(self)
        self.place_buttons: dict[Place, QPushButton] = {}
        for index, (place, text) in enumerate(PLACE_TEXTS.items()):
            segment = QPushButton(text)
            set_role(segment, "segment", "variant")
            segment.setCheckable(True)
            # a key typed into the window must not press it: Enter in a field would send the changes to the device
            segment.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            segment.setAccessibleName(f"Preview: {text}")
            self.place_group.addButton(segment, index)
            self.place_buttons[place] = segment
            layout.addWidget(segment)
        self.place_group.idClicked.connect(lambda index: self.live_preview.set_place(list(PLACE_TEXTS)[index]))
        return box

    def _preview_status(self) -> QHBoxLayout:
        """The bar of the page shown (see `_pages`) and the sound server."""
        top = QHBoxLayout()
        self.page_bars = QStackedWidget()
        """The bar of each page of the rail (an empty one for a page without), switched with the page."""
        top.addWidget(self.page_bars, 1)
        self.audio_label = label("Reading the sound server…", "pill")
        """What the GUI read from the sound server (for the suggestions); a click: all of it."""
        make_clickable(self.audio_label, self._show_audio)
        self.audio_error: str | None = None
        self.audio_popover: QFrame | None = None
        self.reopen_audio = False
        """Whether the popover asked to read again: it shows the result."""
        top.addWidget(self.audio_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.refresh_audio = flat_button("refresh", "Read the devices and applications of the sound server again")
        self.refresh_audio.clicked.connect(self.load_audio)
        top.addWidget(self.refresh_audio)
        return top

    def _pages(self) -> QStackedWidget:
        def audio() -> AudioState:
            # the pages ask for the current one every time
            return self.audio

        self.slots_page = slots = SlotsPanel(
            self.editor,
            audio,
            lambda: self.live.snapshot,
            self.live.send,
            self.show_channel,
            lambda: self.live.twin.slots if self.live.twin is not None else None,
            lambda: twin_unavailable(self.live.snapshot, self.live.owned),
            lambda: self.live_preview.in_gui,
        )
        self.device_view = DeviceView(
            slots,
            RemoteHand(self.live),
            RemoteHand(self.live, preview=True),
            lambda: self.live.twin,
            lambda: self.live.owned,
            lambda: self.live_preview.in_gui,
            self._previewing,
        )
        self.device_view.close_virtual_device.connect(self.close_virtual_device)
        self.device_view.picked.connect(self.show_slot)
        self.device_view.moved.connect(self.move_slot)
        self.device_view.try_without_device.connect(self.try_without_device)
        self.device_view.use_virtual_device.connect(self.use_virtual_device)
        self.device_view.live_clicked.connect(self._mode_clicked)
        slots.simulated.connect(self._simulated)
        self.live.twin_changed.connect(lambda _view: self.device_view.show_live(self.live.snapshot))
        self.channels_page = ChannelsPage(
            self.editor, audio, lambda: self.live.snapshot, lambda: self.live.known, self.live.send
        )
        self.states_page = StatesPage(self.editor, audio, lambda: self.live.snapshot, self.live.send)
        # a strip of "Used by" shows its slot
        self.channels_page.used.strips.picked.connect(self.show_slot)
        self.states_page.used.strips.picked.connect(self.show_slot)
        self.pages: dict[str, Page] = {"slots": slots, "channels": self.channels_page, "states": self.states_page}
        for name in SETTINGS_PAGES:
            if name == "aliases":
                self.pages[name] = AliasesPage(self.editor, audio)
            elif name == "mqtt":
                self.mqtt_page = MqttPage(self.editor, audio, BrokerTester(self.try_broker))
                self.pages[name] = self.mqtt_page
            elif name == "voip":
                self.voip_page = VoipPage(self.editor, audio, self.mumble_installer)
                self.pages[name] = self.voip_page
            else:
                self.pages[name] = SectionPage(name, self.editor, audio)
        self.stack = QStackedWidget()
        self.stack.addWidget(slots)
        self.stack.addWidget(self.channels_page)
        self.stack.addWidget(self.states_page)
        self.settings = SettingsPages(self.pages)
        self.settings.picked.connect(self.show_page)
        self.nav_buttons = self.settings.buttons
        self.stack.addWidget(self.settings)
        for name in RAIL_PAGES:
            self.page_bars.addWidget(slots.bar if name == "slots" else QWidget())
        self.stack.currentChanged.connect(self.page_bars.setCurrentIndex)
        return self.stack

    def _disk_bar(self) -> QFrame:
        """The bar above the page while the file changed on disk and the window has unsaved changes."""
        self.disk_bar = QFrame()
        set_role(self.disk_bar, "banner")
        layout = QHBoxLayout(self.disk_bar)
        layout.setContentsMargins(Space.M, Space.S, Space.M, Space.S)
        self.disk_message = label("", wrap=True)
        layout.addWidget(self.disk_message, 1)
        self.reload_button = QPushButton("Reload")
        set_icon(self.reload_button, "file-refresh-outline")
        self.reload_button.setToolTip("Read the file again and drop the changes here (Undo brings them back)")
        self.reload_button.clicked.connect(self.reload)
        layout.addWidget(self.reload_button)
        self.keep_button = QPushButton("Keep mine")
        self.keep_button.setToolTip("Go on with the changes here: Save and apply overwrites the file on disk")
        self.keep_button.clicked.connect(self.keep_mine)
        layout.addWidget(self.keep_button)
        self.disk_bar.hide()
        return self.disk_bar

    def _bar(self, name: str, content: QWidget) -> QToolBar:
        """A bar of the window that stays where it is: the header or the footer."""
        bar = QToolBar(name)
        bar.setObjectName(name)
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.toggleViewAction().setVisible(False)  # pyright: ignore[reportOptionalMemberAccess]
        bar.addWidget(content)
        return bar

    def _device_dock(self) -> QDockWidget:
        """The window Device: above the page at first; it can go to any side, or be a window of its own."""
        dock = QDockWidget("Device", self)
        dock.setObjectName("device")
        dock.setWidget(self.device_view)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock)
        return dock

    def _configuration_dock(self, configuration: QWidget) -> QDockWidget:
        """
        The window Configuration (the rail and the page): under the device at first; it can go to any side, or be a
        window of its own, but not be closed: it is what the window edits.
        """
        dock = QDockWidget("Configuration", self)
        dock.setObjectName("configuration")
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setWidget(configuration)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock)
        self.splitDockWidget(self.device_dock, dock, Qt.Orientation.Vertical)
        return dock

    def _menus(self) -> None:
        """The menus: what is used now and then, with the keys of what is used often."""
        bar = self.menuBar()
        assert bar is not None

        def action(
            menu: QMenu, text: str, slot: Callable[[], object], *keys: QKeySequence.StandardKey | str
        ) -> QAction:
            entry = menu.addAction(text)
            assert entry is not None
            entry.triggered.connect(lambda _=False: slot())
            entry.setShortcuts(
                [
                    sequence
                    for key in keys
                    for sequence in (QKeySequence.keyBindings(key) if not isinstance(key, str) else [QKeySequence(key)])
                ]
            )
            return entry

        file = bar.addMenu("&File")
        assert file is not None
        self.save_action = action(file, "&Save and apply", self.save, QKeySequence.StandardKey.Save)
        self.revert_action = action(file, "&Revert", self.revert)
        file.addSeparator()
        action(file, "&Quit", self.close, QKeySequence.StandardKey.Quit)
        edit = bar.addMenu("&Edit")
        assert edit is not None
        self.undo_action = action(edit, "&Undo", self.undo, QKeySequence.StandardKey.Undo)
        self.redo_action = action(edit, "&Redo", self.redo, QKeySequence.StandardKey.Redo)
        edit.addSeparator()
        # for the entry picked in the list of the page (a candidate, a channel, a state) while the list has the focus;
        # off in a field, where the keys edit its text
        self.entry_actions = (
            action(edit, "Cu&t", self.cut_entry, QKeySequence.StandardKey.Cut),
            action(edit, "&Copy", self.copy_entry, QKeySequence.StandardKey.Copy),
            action(edit, "&Paste", self.paste_entries, QKeySequence.StandardKey.Paste),
            action(edit, "&Duplicate", self.duplicate_entry, "Ctrl+D"),
            action(edit, "Re&move", self.remove_entry, QKeySequence.StandardKey.Delete, "Backspace"),
            action(edit, "Re&name", self.rename_entry, "F2"),
        )
        edit.aboutToShow.connect(self._show_entry_actions)
        self._show_entry_actions()
        view = bar.addMenu("&View")
        assert view is not None
        for number, (name, title) in enumerate(zip(RAIL_PAGES, RAIL_TITLES, strict=True), start=1):
            action(view, f"&{title}", lambda name=name: self.show_page(name), f"Ctrl+{number}")
        view.addSeparator()
        device = self.device_dock.toggleViewAction()
        assert device is not None
        device.setText("&Device")
        device.setToolTip("The window with the device: what it shows right now, or what Simulate shows")
        view.addAction(device)
        view.addSeparator()
        theme = view.addMenu("&Theme")
        assert theme is not None
        themes = QActionGroup(self)
        self.theme_actions: dict[ThemeMode, QAction] = {}
        for mode in ThemeMode:
            entry = action(theme, mode.value.capitalize(), lambda mode=mode: self.set_theme(mode))
            entry.setCheckable(True)
            entry.setChecked(mode == current_mode())
            themes.addAction(entry)
            self.theme_actions[mode] = entry
        zoom = view.addMenu("&Zoom")
        assert zoom is not None
        # Ctrl++ on keyboards with a + key, Ctrl+= where + is Shift+=
        action(zoom, "Zoom &in", self.zoom_in, QKeySequence.StandardKey.ZoomIn, "Ctrl+=")
        action(zoom, "Zoom &out", self.zoom_out, QKeySequence.StandardKey.ZoomOut)
        action(zoom, "&Actual size", self.zoom_reset, "Ctrl+0")
        zoom.addSeparator()
        zooms = QActionGroup(self)
        self.zoom_actions: dict[float, QAction] = {}
        for level in ZOOM_LEVELS:
            entry = action(zoom, zoom_text(level), lambda level=level: self.zoom_to(level))
            entry.setCheckable(True)
            entry.setChecked(level == self.zoom)
            zooms.addAction(entry)
            self.zoom_actions[level] = entry
        help_menu = bar.addMenu("&Help")
        assert help_menu is not None
        action(
            help_menu,
            "&Documentation",
            lambda: QDesktopServices.openUrl(QUrl(docs.DOCS_URL)),
            QKeySequence.StandardKey.HelpContents,
        )
        action(help_menu, "&Keyboard shortcuts", self.show_keys)

    def show_keys(self) -> None:
        """
        The keys of the window, under the menus: those of the menus as the desktop has them, the lists and the
        drawing.
        """
        bar = self.menuBar()
        assert bar is not None

        def keys(menu: QMenu | None) -> tuple[tuple[str, str], ...]:
            assert menu is not None
            found: list[tuple[str, str]] = []
            for entry in menu.actions():
                if entry.menu() is not None:
                    found.extend(keys(entry.menu()))
                elif not entry.shortcut().isEmpty():
                    text = entry.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
                    found.append((text, entry.text().replace("&", "")))
            return tuple(found)

        menus = [entry.menu() for entry in bar.actions()]
        entries = [
            Entry("Window", items=keys(menus[0]) + keys(menus[2]) + keys(menus[3])),
            Entry(
                "Edit",
                text="Cut, Copy, Paste, Duplicate, Remove and Rename are for the candidate, channel or state picked "
                "in the list that has the focus. In a field, the keys edit its text.",
                items=keys(menus[1]),
            ),
            Entry(
                "Lists",
                items=(
                    ("Up, Down", "Pick the one above or below"),
                    ("Ctrl+Up, Ctrl+Down", "Move the candidate (Slots), the entry of a table"),
                ),
            ),
            Entry(
                "Device",
                items=(
                    ("Left, Right, Home, End", "Pick a strip"),
                    ("Ctrl+Left, Ctrl+Right", "Move its slot"),
                    ("Esc", "End Simulate, close a popover"),
                ),
            ),
        ]
        show_popover(bar, "Keyboard shortcuts", entries)

    def _footer(self) -> QWidget:
        footer = QWidget()
        set_role(footer, "bar")
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(Space.XL, Space.M, Space.XL, Space.M)
        self.problems_button = QToolButton()
        set_role(self.problems_button, "problems")
        set_icon(self.problems_button, "alert-circle", "error")
        self.problems_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.problems_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.problems_menu = QMenu(self.problems_button)
        self.problems_button.setMenu(self.problems_menu)
        layout.addWidget(self.problems_button)
        self.status = ElidedLabel("", "hint")
        layout.addWidget(self.status, 1)
        self.hover_tip = ElidedLabel("", "hint")
        """The tip of what is under the mouse, in place of the status line (see `HoverTips`)."""
        layout.addWidget(self.hover_tip, 1)
        self.hover_tips = HoverTips(self, self.hover_tip, self.status)
        self.restart_button = QPushButton("Restart the service")
        set_icon(self.restart_button, "restart")
        self.restart_button.clicked.connect(self._restart)
        self.restart_button.hide()
        layout.addWidget(self.restart_button)
        self.changes_pill = label("", "pill")
        """Whether the device runs the saved file, the unsaved changes, or neither (see `changes_status`)."""
        self.changes: Status | None = None
        make_clickable(self.changes_pill, self._show_changes)
        layout.addWidget(self.changes_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.try_box = self._preview_control()
        layout.addWidget(self.try_box)
        self.undo_button = flat_button("undo", "Undo (Ctrl+Z)")
        self.undo_button.clicked.connect(self.undo)
        layout.addWidget(self.undo_button)
        self.redo_button = flat_button("redo", "Redo (Ctrl+Shift+Z)")
        self.redo_button.clicked.connect(self.redo)
        layout.addWidget(self.redo_button)
        self.revert_button = QPushButton("Revert")
        set_icon(self.revert_button, "file-undo-outline")
        self.revert_button.setToolTip("Drop the changes and read the file again (Undo brings them back)")
        self.revert_button.clicked.connect(self.revert)
        layout.addWidget(self.revert_button)
        self.save_button = QPushButton("Save and apply")
        set_icon(self.save_button, "content-save", "white")
        set_role(self.save_button, "primary", "variant")
        self.save_button.setToolTip("Write the file and reload the daemon (Ctrl+S)")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        return footer

    # -- showing --------------------------------------------------------------------------------------------------

    def show_page(self, name: str) -> None:
        """Shows a page of the rail ("slots", "channels", "states", "settings"), or one of the settings."""
        if name in SETTINGS_PAGES:
            self.settings.show_page(name)
            name = "settings"
        self.rail_buttons[name].setChecked(True)
        self.stack.setCurrentIndex(RAIL_PAGES.index(name))

    @property
    def current_page(self) -> str:
        name = RAIL_PAGES[self.stack.currentIndex()]
        return self.settings.current_page if name == "settings" else name

    def _document_changed(self, change: Change) -> None:
        """The document changed (see `Change`): every view shows what changed for it, and the problems."""
        if change.scope is not Scope.FILE:
            # what the window said was about the document before
            self.restart_button.hide()
            self.status.setText("")
        for page in self.pages.values():
            page.show_document(change)
            page.show_problems(self.validation)
        self._show_problems(self.validation.problems)
        modified = self.document.modified
        # Qt adds the name of the application ("— X-Touch Extender"); • as editors mark unsaved changes
        mark = "• " if modified else ""
        new = " (new)" if not self.document.exists else ""
        self.setWindowTitle(f"{mark}{self.document.path.name}{new}")
        self._show_savable()
        for widget in (self.revert_button, self.revert_action):
            # after Keep mine also without changes: the file on disk is another one
            widget.setEnabled(modified or self.document.overruled is not None)
        for widget in (self.undo_button, self.undo_action):
            widget.setEnabled(self.history.can_undo)
        for widget in (self.redo_button, self.redo_action):
            widget.setEnabled(self.history.can_redo)
        self.live_preview.document_changed()
        self.refresh_preview()

    def refresh_preview(self) -> None:
        """Shows the device (live while the daemon tells what it shows) and whether it runs the file."""
        snapshot = self.live.snapshot
        if self.trying is not None and offers_virtual_device(snapshot, self.hosted is not None):
            # the daemon started to try without a device waits for its device: here it is
            self.open_virtual_device()
        self.device_view.show_daemon(self.daemon is not None or self.trying is not None)
        self._show_live_preview(snapshot)
        self.device_view.show_live(snapshot)
        shows_document = previewed(snapshot, self.validation.config, self.live_preview.running)
        saved = self.document.saved_config
        device = saved.device.name if saved is not None else "the device"
        hosting = self.hosted is not None
        on_device = self.live_preview.on and (shows_document or self._device_simulates(snapshot))
        self.device_view.show_status(
            drawing_status(preview_status(self.daemon, snapshot, device, hosting), self.live_preview.in_gui, on_device),
            offers_virtual_device(snapshot, hosting),
            slots_status(snapshot),
        )
        self.service_controls.show_connections(connections(snapshot, device))
        self.states_page.show_live(snapshot)
        self.mqtt_page.show_live(snapshot)
        self.voip_page.show_live(snapshot)
        changes = changes_status(
            self.daemon,
            snapshot,
            self.document.path,
            saved if self.document.exists else None,
            self.document.modified,
            self.applying.isActive(),
            shows_document and self.document.modified,
            self.live_preview.on,
            self.validation.config is None,
            self._device_simulates(snapshot),
            self.live_preview.place.value,
            self.slots_page.what_if is not None,
        )
        self.changes = changes
        show_status(self.changes_pill, changes, more=True)
        self._show_savable()

    def _show_changes(self) -> None:
        """What the device runs, and the file: its path, to copy or to open its folder."""
        if self.changes is None:
            return
        path = self.document.path
        clipboard = QApplication.clipboard()
        assert clipboard is not None
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
        show_popover(self.changes_pill, "Configuration", entries)

    def _show_savable(self) -> None:
        """
        "Save and apply" while there is something to save, or the daemon runs another version of the file (e.g. one
        changed outside the GUI): then it only reloads the daemon.
        """
        saved = self.document.saved_config if self.document.exists else None
        stale = not self.applying.isActive() and runs_older(self.daemon, self.live.snapshot, self.document.path, saved)
        savable = self.validation.config is not None and (self.document.modified or not self.document.exists or stale)
        for widget in (self.save_button, self.save_action):
            widget.setEnabled(savable)

    def _simulated(self) -> None:
        """Simulate started, changed or ended: the preview follows, where it shows."""
        self.live_preview.set_situation(self.slots_page.what_if)

    def _device_simulates(self, snapshot: Snapshot | None) -> bool:
        """Whether the device shows the situation of Simulate of this window."""
        preview = self.live_preview
        return preview.on and preview.simulating and snapshot is not None and snapshot.simulated

    def _previewing(self) -> bool:
        """Whether the drawing shows a preview of this window: on its twin, or on the device."""
        preview = self.live_preview
        snapshot = self.live.snapshot
        on_device = previewed(snapshot, self.validation.config, preview.running) or self._device_simulates(snapshot)
        return preview.in_gui or (preview.on and on_device)

    def _show_live_preview(self, snapshot: Snapshot | None) -> None:
        """
        The control "Preview": there while there is something to preview (or it runs); a place it can't show in is
        disabled and says why; and what the daemon said.
        """
        preview = self.live_preview
        device_reason = unavailable(self.daemon, snapshot, self.document.path, self.live.owned)
        gui_reason = twin_unavailable(snapshot, self.live.owned)
        if device_reason is not None and preview.place == Place.DEVICE:
            preview.set_place(Place.GUI)
        elif self.resume_place is not None and (device_reason is None or self.resume_place != Place.DEVICE):
            place, self.resume_place = self.resume_place, None
            preview.set_place(place)
        self.try_box.setVisible(preview.wanted or preview.running)
        self.slots_page.show_place(
            "On the device" if preview.on else "In the GUI" if gui_reason is None else f"Nowhere: {gui_reason.short}"
        )
        reasons = {Place.GUI: gui_reason, Place.DEVICE: device_reason, Place.OFF: None}
        for place, segment in self.place_buttons.items():
            reason = reasons[place]
            segment.setEnabled(reason is None)
            segment.setChecked(place == preview.place)
            segment.setToolTip(PLACE_TIPS[place] if reason is None else f"{reason.why}\n\n{PLACE_TIPS[place]}")
        message = f"The preview keeps the version before: {preview.error}" if preview.error else preview.notice
        self.preview_message.setVisible(message is not None)
        self.preview_message.setText(message or "")

    def _show_problems(self, problems: list[Problem]) -> None:
        self.problems_button.setVisible(bool(problems))
        self.problems_button.setText(f"{len(problems)} problem{'' if len(problems) == 1 else 's'}")
        self.problems_menu.clear()
        for problem in problems:
            if problem.kind == "extra_forbidden":
                action = QAction(f"{problem.location}: unknown option, click to remove it", self.problems_menu)
                action.triggered.connect(lambda _=False, problem=problem: self.editor.unset(problem.path))
            else:
                action = QAction(str(problem) if problem.path else problem.message, self.problems_menu)
                action.triggered.connect(lambda _=False, problem=problem: self.go_to(problem))
            self.problems_menu.addAction(action)

    def show_slot(self, slot: int) -> None:
        """The slot (1 for the leftmost one) on the page Slots, with the candidate the device shows."""
        self.slots_page.select_slot(slot)
        self.show_page("slots")

    def show_channel(self, name: str) -> None:
        self.channels_page.select(("channel", name))
        self.show_page("channels")

    def go_to(self, problem: Problem) -> None:
        """Shows the page of the problem (see `place_of`)."""
        place = place_of(problem)
        if place is None:
            return
        if place.slot is not None:
            # the strip on the drawing, which picks its card on the page Slots
            self.device_view.select(place.slot - 1)
            return
        if place.channel is not None:
            self.channels_page.select(place.channel)
        if place.state is not None:
            self.states_page.select(place.state)
        self.show_page(place.page)

    def set_theme(self, mode: ThemeMode) -> None:
        apply_theme(mode)
        self.theme_actions[mode].setChecked(True)
        # the icons are drawn in the colors of the theme
        refresh_icons(self)
        refresh_help(self)
        # and the dots of the states in the bar of Slots
        self.slots_page.shown_live = None
        self.slots_page.show_live(self.slots_page.snapshot())
        self.device_view.preview.update()

    # -- editing --------------------------------------------------------------------------------------------------

    def undo(self) -> None:
        if self.editor.undo():
            self.status.setText("Undone.")

    def redo(self) -> None:
        if self.editor.redo():
            self.status.setText("Redone.")

    def _entry_page(self) -> Page | None:
        """The page whose list has the focus: the menu Edit cuts, copies, pastes ... its entries."""
        page = self.pages.get(self.current_page)
        return page if page is not None and page.entries_focused() else None

    def _focus_changed(self, _old: QWidget | None, _new: QWidget | None) -> None:
        self._show_entry_actions()

    def _show_entry_actions(self) -> None:
        """Cut, Copy, Paste ... only while the list of a page has the focus: in a field the keys edit its text."""
        page = self._entry_page()
        for entry_action in self.entry_actions:
            entry_action.setEnabled(page is not None)

    def copy_entry(self) -> None:
        page = self._entry_page()
        text = page.copy_entry() if page is not None else None
        if text is not None:
            _clipboard().setText(text)
            self.status.setText("Copied, as in the file: Ctrl+V pastes it after the one picked, or into a text editor.")

    def cut_entry(self) -> None:
        page = self._entry_page()
        text = page.copy_entry() if page is not None else None
        if page is not None and text is not None and page.remove_entry():
            _clipboard().setText(text)
            self.status.setText("Cut: Ctrl+V pastes it after the one picked, Ctrl+Z brings it back.")

    def paste_entries(self) -> None:
        page = self._entry_page()
        if page is None:
            return
        count = page.paste_entries(_clipboard().text())
        if count:
            self.status.setText(f"Pasted {count}. Ctrl+Z takes {'them' if count > 1 else 'it'} out again.")
        else:
            self.status.setText(f"The clipboard has no {page.ENTRIES}: copy them here, or from the file.")

    def duplicate_entry(self) -> None:
        page = self._entry_page()
        if page is not None:
            page.duplicate_entry()

    def remove_entry(self) -> None:
        page = self._entry_page()
        if page is not None and page.remove_entry():
            self.status.setText("Removed. Ctrl+Z brings it back.")

    def rename_entry(self) -> None:
        page = self._entry_page()
        if page is not None:
            page.rename_entry()

    # -- the sound server -----------------------------------------------------------------------------------------

    def load_audio(self) -> None:
        self.audio_label.setText("Reading the sound server…")
        self.audio_label.setToolTip("")
        self.loader.load()

    def _audio_loaded(self, state: AudioState) -> None:
        self.audio = state
        self.audio_error = None
        tip = "What the GUI read from the sound server: the names the forms suggest."
        show_status(self.audio_label, Status(f"Sound server: {sources.summary(state)}", Tone.NEUTRAL, tip), more=True)
        self._audio_changed()
        self._audio_read()

    def _audio_failed(self, message: str) -> None:
        self.audio = DISCONNECTED
        self.audio_error = message
        status = Status("Sound server not reachable: type names by hand", Tone.WARN, message)
        show_status(self.audio_label, status, more=True)
        self._audio_changed()
        self._audio_read()

    def _show_audio(self) -> None:
        """What the GUI read from the sound server, or why it couldn't, and reading it again (it stays open)."""
        heading = "Sound server"
        again = (("Read again", self._read_audio_again),)
        if self.audio_error is not None:
            entry = Entry(
                "",
                Status("not reachable", Tone.WARN),
                f"{self.audio_error}\n\nThe forms suggest no names meanwhile: type them by hand.",
            )
            self._keep_audio_popover(show_popover(self.audio_label, heading, [entry], actions=again))
            return
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
            )
            for kind, items in sources.contents(self.audio)
        ]
        self._keep_audio_popover(show_popover(self.audio_label, heading, entries, intro, again))

    def _keep_audio_popover(self, popover: QFrame) -> None:
        self.audio_popover = popover
        popover.destroyed.connect(lambda: self._forget_audio_popover(popover))

    def _forget_audio_popover(self, popover: QFrame) -> None:
        # the one closed for showing anew goes after the new one is there
        if self.audio_popover is popover:
            self.audio_popover = None

    def _read_audio_again(self) -> None:
        """Read again from the popover: it shows what was read when it is there (see `_audio_read`)."""
        self.reopen_audio = True
        self.load_audio()

    def _audio_read(self) -> None:
        """The popover, open while it read again, shows what it read now (in the same place)."""
        if not self.reopen_audio:
            return
        self.reopen_audio = False
        if self.audio_popover is not None and self.audio_popover.isVisible():
            self.audio_popover.close()
            self._show_audio()

    def _audio_changed(self) -> None:
        """What the forms suggest depends on the devices and the applications of the sound server."""
        self.refresh_preview()

    # -- the service ----------------------------------------------------------------------------------------------

    def refresh_service(self) -> None:
        """Finds the daemon (and its live view) and the state of the service again."""
        self.daemon = self.find_daemon()
        if self.daemon is None:
            self.live.disconnect_from_daemon()
        else:
            self.live.connect_to_daemon()
        self.service_controls.show_state(self.daemon, self.live.snapshot)
        self.refresh_preview()

    def _restart(self) -> None:
        self.restart_button.hide()
        try:
            self.service.restart()
        except ServiceError as e:
            QMessageBox.warning(self, "Service", str(e))
            return
        self.status.setText("Restarted the service.")
        self.refresh_service()

    # -- the file -------------------------------------------------------------------------------------------------

    def save(self) -> bool:
        """Saves and applies the configuration; False when it could not be saved."""
        if self.validation.config is None:
            QMessageBox.warning(self, "Not saved", "Fix the problems first: the daemon would not take the file.")
            return False
        if not self.save_button.isEnabled():
            # nothing changed
            return True
        restart_sections = self.document.restart_sections
        if self.document.modified or not self.document.exists:
            if self.document.changed_on_disk() and not self._overwrite():
                return False
            try:
                self.document.save()
            except (OSError, ConfigError) as e:
                QMessageBox.critical(self, "Saving failed", str(e))
                return False
        # else the file is saved: the daemon runs another version of it and is only reloaded
        # the daemon loads the file (also one it is not told to reload: it watches the file during a preview)
        self.live_preview.saved()
        try:
            applied = apply(self.daemon, self.document.path, restart_sections)
        except OSError as e:
            # e.g. it ended a moment ago
            assert self.daemon is not None
            self.status.setText(f"Saved, but reloading {describe(self.daemon)} failed: {e}")
        else:
            self.status.setText(applied.message)
            if applied.reloaded:
                self.applying.start()
            # the window restarts only the service
            self.restart_button.setVisible(applied.restart_needed and self.daemon is not None and self.daemon.systemd)
        self.editor.saved()
        self.refresh_service()
        return True

    def revert(self) -> None:
        if self.reload():
            self.status.setText("Reverted to the file. Ctrl+Z brings the changes back.")

    def reload(self) -> bool:
        """Reads the file again, one step to undo; False (and the bar says why) while it can't be read."""
        try:
            self.editor.revert()
        except ConfigError as e:
            self._show_disk_bar(f"The file on disk can't be read: {e}. The changes here stay; saving overwrites it.")
            return False
        self.disk_bar.hide()
        return True

    def keep_mine(self) -> None:
        """Goes on with the changes here: the next save overwrites the file on disk without asking."""
        self.document.overrule()
        self.disk_bar.hide()
        self.editor.saved()

    def _file_changed(self) -> None:
        """
        Something happened to the file on disk. Another text than the window read: without unsaved changes it reads
        it again, with them the bar asks (Reload or Keep mine). The window's own saves are no change.
        """
        if not self.document.changed_on_disk():
            # e.g. the file is back to what the window read
            self.disk_bar.hide()
            return
        if self.document.modified:
            self._show_disk_bar(
                "The file changed on disk. Reload reads it again and drops the changes here (Ctrl+Z brings them back); "
                "Keep mine goes on with them, and saving overwrites the file."
            )
        elif self.reload():
            self.status.setText("The file changed on disk: read it again. Ctrl+Z goes back to the version before.")

    def _show_disk_bar(self, message: str) -> None:
        self.disk_message.setText(message)
        self.disk_bar.show()

    def _overwrite(self) -> bool:
        """The file changed on disk since it was read: whether to overwrite it (Reload reads it instead)."""
        box = QMessageBox(
            QMessageBox.Icon.Question,
            "The file changed on disk",
            "Someone else changed the file since the window read it. Overwrite it with the changes here?",
            parent=self,
        )
        overwrite = box.addButton("Overwrite", QMessageBox.ButtonRole.AcceptRole)
        reload = box.addButton("Reload", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is reload:
            self.reload()
        return box.clickedButton() is overwrite

    # -- zoom -----------------------------------------------------------------------------------------------------

    def zoom_in(self) -> None:
        self.zoom_to(zoom_step(self.zoom, 1))

    def zoom_out(self) -> None:
        self.zoom_to(zoom_step(self.zoom, -1))

    def zoom_reset(self) -> None:
        self.zoom_to(1.0)

    def zoom_to(self, zoom: float) -> None:
        """Closes the window for a new one at `zoom` (see `Session`), keeping everything that is not saved."""
        if zoom == self.zoom:
            return
        save_zoom(zoom)
        self.rezoom = zoom
        self.close()

    def session(self) -> Session:
        """What the next window needs to go on where this one is."""
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        return Session(
            history=self.history,
            page=self.current_page,
            geometry=to_screen(geometry, self.devicePixelRatioF()),
            maximized=self.isMaximized(),
            audio=self.audio,
            preview=self.live_preview.place.value,
            trying=self.trying,
        )

    def move_slot(self, source: int, target: int) -> None:
        """A strip was dragged to another place: its slot moves there, and stays picked."""
        self.editor.move_slot(source, target)
        self.status.setText(f"Moved slot {source} to {target}. Ctrl+Z moves it back.")
        self.device_view.select(target - 1)

    def try_without_device(self) -> None:
        """
        Starts a daemon with the virtual device on this file (saved first if it is new), and opens the device in the
        window once the daemon waits for it (see `refresh_preview`).
        """
        if self.trying is not None:
            return
        if not self.document.exists and not self.save():
            return
        process = QProcess()
        process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)
        process.start(
            sys.executable, ["-m", "xtouch_daemon", "run", "--virtual-device", "--config", str(self.document.path)]
        )
        self._keep_trying(process)
        self.status.setText("Starting a daemon with the virtual device…")

    def _keep_trying(self, process: QProcess) -> None:
        """The daemon to try without a device is this window's: it ends with it."""
        process.setParent(self)  # pyright: ignore[reportArgumentType]: PyQt's stub types the parent as Self
        process.finished.connect(lambda code, _status: self._tried(process, code))
        self.trying = process

    def _tried(self, process: QProcess, code: int) -> None:
        if self.trying is not process:
            return
        self.trying = None
        process.deleteLater()
        self.status.setText(f"The daemon for trying without a device ended (exit code {code}).")
        self.refresh_service()

    def use_virtual_device(self) -> None:
        """
        For a daemon that finds no device: `[device] virtual = true`, saved (the daemon takes it when it reloads,
        without a restart), and the virtual device opened here.
        """
        if self.daemon is None or self.document.path.resolve() != self.daemon.config:
            self.status.setText("The daemon reads another file: set Virtual on the page Extender of that one.")
            return
        self.document.set(("device", "virtual"), True)
        self.editor.edited(Change(Scope.VALUE, ("device", "virtual")))
        if self.save():
            self.open_virtual_device()

    def _mode_clicked(self) -> None:
        if offers_virtual_device(self.live.snapshot, self.hosted is not None):
            self.open_virtual_device()

    def open_virtual_device(self) -> None:
        """Hosts the virtual device, for a daemon that waits for it: the mouse on the drawing is a hand on it."""
        hosted = HostedDevice(self.virtual_socket, self)
        try:
            hosted.start()
        except (AlreadyServed, OSError) as e:
            hosted.deleteLater()
            QMessageBox.warning(self, "Virtual device", str(e))
            return
        self.hosted = hosted
        self.device_view.host(hosted)
        self.device_dock.show()
        self.device_dock.raise_()
        self.refresh_preview()

    def close_virtual_device(self) -> None:
        """Unplugs the hosted virtual device and closes it."""
        if self.hosted is None:
            return
        self.hosted.stop()
        self.hosted.deleteLater()
        self.hosted = None
        self.device_view.host(None)
        self.refresh_preview()

    def closeEvent(self, event: QCloseEvent | None) -> None:
        assert event is not None
        if self.document.modified and self.rezoom is None:
            buttons = QMessageBox.StandardButton
            question = "Save the changes before closing?"
            if self.live_preview.running and self.live_preview.on:
                question += (
                    " The device runs them now (Preview: On the device): without saving, it goes back to the file."
                )
            answer = QMessageBox.question(
                self,
                "Unsaved changes",
                question,
                buttons.Save | buttons.Discard | buttons.Cancel,
                buttons.Save,
            )
            if answer == buttons.Cancel or (answer == buttons.Save and not self.save()):
                event.ignore()
                return
        # back to the file (the daemon would notice the closed connection too); after a new zoom the next window
        # previews again (see `Session`)
        self.live_preview.stop()
        self.hover_tips.stop()
        self.close_virtual_device()
        if self.trying is not None and self.rezoom is not None:
            # the next window takes it over (see `session()`)
            self.trying.setParent(None)  # pyright: ignore[reportArgumentType]
        elif self.trying is not None:
            trying, self.trying = self.trying, None
            trying.terminate()
            trying.waitForFinished(3000)
        save_window_state(bytes(self.saveState()))
        app = QApplication.instance()
        assert app is not None
        app.removeEventFilter(self.input_filter)
        app.focusChanged.disconnect(self._focus_changed)
        event.accept()


def _clipboard() -> QClipboard:
    clipboard = QApplication.clipboard()
    assert clipboard is not None
    return clipboard
