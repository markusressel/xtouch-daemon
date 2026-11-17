"""
The main window. From the top: the menus; the file and the service; a rail of the pages (Slots, Channels, States,
Settings), the window Device (docked above the page at first, or anywhere else, or on its own) and the page; at the
bottom the problems, undo and saving.
"""

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QPointF, QRect, QSignalBlocker, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QKeyEvent,
    QKeySequence,
    QShowEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollBar,
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
from xtouch_daemon.gui.domain.broker import header_status
from xtouch_daemon.gui.domain.changes import EVERYTHING, Change, Scope
from xtouch_daemon.gui.domain.history import History
from xtouch_daemon.gui.domain.live_preview import preview_pill, previewed, unavailable
from xtouch_daemon.gui.domain.schema import SECTIONS
from xtouch_daemon.gui.domain.slots import slots_status
from xtouch_daemon.gui.domain.slots_document import SlotsDocument, Validation
from xtouch_daemon.gui.domain.status import Status, offers_virtual_device, preview_status, runs_older, sync_status
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import ElidedLabel, flat_button, label, refresh_help, show_status
from xtouch_daemon.gui.qt.fields.controls import Switch
from xtouch_daemon.gui.qt.live_preview import LivePreview
from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.gui.qt.pages.aliases import AliasesPage
from xtouch_daemon.gui.qt.pages.base import SETTINGS_PAGES, Page, page_title, scrolled, set_text
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
from xtouch_daemon.gui.qt.theme.icons import refresh_icons, set_icon
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
from xtouch_daemon.gui.qt.window.service import ServiceControls
from xtouch_daemon.gui.qt.window.session import Session
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import Snapshot
from xtouch_daemon.simulator.server import AlreadyServed
from xtouch_daemon.system import instance
from xtouch_daemon.system.instance import Instance
from xtouch_daemon.system.systemd import (
    Service,
    ServiceError,
)

SERVICE_POLL_MS = 3000
APPLY_GRACE_MS = 2000
"""How long a reload may take before the window says that the daemon did not take the file."""
RAIL = (
    ("slots", "Slots", "tune-vertical", "What each slot shows when"),
    ("channels", "Channels", "format-list-bulleted", "What a strip can control"),
    ("states", "States", "toggle-switch-outline", "The states and modes that decide what slots show"),
    ("settings", "Settings", "cog-outline", "The device, behavior, aliases, Home Assistant, the voice chat"),
)
"""The pages of the rail: name, title, icon, tip."""
WINDOW_SIZE = (1280, 1000)
"""The size of the window when it opens, where the screen has room for it."""
DEVICE_HEIGHT = 380
"""The height of the window Device above the page, until it is made larger or smaller."""


def _takes_wheel(widget: QObject | None) -> bool:
    """Whether the wheel would change the value of `widget`: a number, a choice or a slider (not a scroll bar)."""
    return isinstance(widget, QAbstractSpinBox | QComboBox) or (
        isinstance(widget, QAbstractSlider) and not isinstance(widget, QScrollBar)
    )


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
        self.resume_live_preview = session is not None and session.live_preview
        """Turns the live preview on once it can be: it was on in the window before the zoom."""

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
        body.addWidget(self._pages(), 1)
        self.setCentralWidget(root)
        # the header, the rail and the footer reach across the window, the docks are between them
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._bar("header", self._header()))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self._bar("rail", self._rail()))
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self._bar("footer", self._footer()))
        self.device_dock = self._device_dock()
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
        # the document's undo, also while a text field has the focus: its own would leave the document behind
        app.installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_service)
        self.timer.start(SERVICE_POLL_MS)
        self.loader = AudioLoader(read_audio)
        self.loader.loaded.connect(self._audio_loaded)
        self.loader.failed.connect(self._audio_failed)
        self.editor.changed.connect(self._document_changed)
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
        ratio = self.devicePixelRatioF()
        geometry = session.geometry
        self.setGeometry(
            round(geometry.x() / ratio),
            round(geometry.y() / ratio),
            round(geometry.width() / ratio),
            round(geometry.height() / ratio),
        )
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
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label("X-Touch Extender", "title"))
        self.path_label = ElidedLabel("", "hint", Qt.TextElideMode.ElideMiddle)
        titles.addWidget(self.path_label)
        layout.addLayout(titles)
        layout.addStretch()
        self._live_preview_switch(layout)
        self.service_controls = ServiceControls(self.service)
        self.service_controls.changed.connect(self.refresh_service)
        # the status line comes later, with the footer
        self.service_controls.told.connect(lambda text: self.status.setText(text))
        layout.addWidget(self.service_controls)
        return header

    def _live_preview_switch(self, layout: QHBoxLayout) -> None:
        """The switch of the live preview: the device runs the document instead of the file while it is on."""
        self.preview_switch = Switch()
        # like the service controls: a key typed into the window right after it opened must not turn it on
        self.preview_switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview_switch.setAccessibleName("Live preview")
        self.preview_switch.toggled.connect(self.live_preview.set_on)
        self.preview_label = label("Live preview", "hint")
        self.preview_label.setBuddy(self.preview_switch)
        layout.addWidget(self.preview_label)
        layout.addWidget(self.preview_switch)
        layout.addSpacing(Space.L)

    def _preview_status(self) -> QHBoxLayout:
        """What the preview shows (live or the file), the connection to Home Assistant, and the sound server."""
        top = QHBoxLayout()
        self.mode_pill = label("", "pill")
        """Live or the file; while the daemon waits for the virtual device, a click opens it."""
        self.mode_pill.mousePressEvent = lambda event: self._mode_clicked()  # type: ignore[method-assign]
        top.addWidget(self.mode_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.preview_pill = label("", "pill")
        """Whether the device runs the unsaved changes (the live preview)."""
        top.addWidget(self.preview_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.mqtt_pill = label("", "pill")
        self.mqtt_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mqtt_pill.mousePressEvent = lambda event: self.show_page("mqtt")  # type: ignore[method-assign]
        top.addWidget(self.mqtt_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.slots_pill = label("", "pill")
        """The mode of a daemon with channels, states and slots; its tip has the states and the slots."""
        top.addWidget(self.slots_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.sync_label = ElidedLabel("", "hint")
        top.addWidget(self.sync_label, 1)
        self.audio_label = ElidedLabel("Reading the sound server…", "hint")
        top.addWidget(self.audio_label)
        self.refresh_audio = flat_button("refresh", "Read the devices and applications of the sound server again")
        self.refresh_audio.clicked.connect(self.load_audio)
        top.addWidget(self.refresh_audio)
        return top

    def _rail(self) -> QWidget:
        """The pages on the left, one at a time."""
        rail = QWidget()
        set_role(rail, "bar")
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(Space.S, Space.L, Space.S, Space.L)
        layout.setSpacing(Space.XS)
        self.rail = QButtonGroup(self)
        self.rail_buttons: dict[str, QToolButton] = {}
        for name, title, icon_name, tip in RAIL:
            rail_button = QToolButton()
            rail_button.setText(title)
            # the pages of the states, channels and slots in their colors, like everywhere in the window
            set_icon(rail_button, icon_name, name.removesuffix("s") if name != "settings" else None)
            rail_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            rail_button.setCheckable(True)
            rail_button.setAutoRaise(True)
            rail_button.setToolTip(tip)
            rail_button.setMinimumWidth(72)
            rail_button.clicked.connect(lambda _=False, name=name: self.show_page(name))
            self.rail.addButton(rail_button)
            self.rail_buttons[name] = rail_button
            layout.addWidget(rail_button)
        layout.addStretch()
        return rail

    def _pages(self) -> QStackedWidget:
        def audio() -> AudioState:
            # the pages ask for the current one every time
            return self.audio

        self.slots_page = slots = SlotsPanel(
            self.editor, audio, lambda: self.live.snapshot, self.live.send, self.show_channel
        )
        self.device_view = DeviceView(slots)
        self.device_view.close_virtual_device.connect(self.close_virtual_device)
        self.device_view.picked.connect(self.show_slot)
        self.channels_page = ChannelsPage(self.editor, audio, lambda: self.live.snapshot)
        self.states_page = StatesPage(self.editor, audio, lambda: self.live.snapshot, self.live.send)
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
        self.stack.addWidget(self._settings())
        return self.stack

    def _settings(self) -> QWidget:
        """The sections with options of their own, one at a time."""
        settings = QWidget()
        pages = QHBoxLayout(settings)
        pages.setContentsMargins(0, Space.M, 0, 0)
        pages.setSpacing(16)
        nav = QVBoxLayout()
        nav.setSpacing(2)
        self.nav = QButtonGroup(self)
        self.settings_stack = QStackedWidget()
        self.nav_buttons: dict[str, QPushButton] = {}
        for name in SETTINGS_PAGES:
            nav_button = QPushButton(page_title(name))
            set_role(nav_button, "nav", "variant")
            nav_button.setCheckable(True)
            nav_button.setToolTip(f"[{name}] in the file")
            nav_button.clicked.connect(lambda _=False, name=name: self.show_page(name))
            self.nav.addButton(nav_button)
            self.nav_buttons[name] = nav_button
            nav.addWidget(nav_button)
            self.settings_stack.addWidget(scrolled(self.pages[name]))
        nav.addStretch()
        holder = QWidget()
        holder.setLayout(nav)
        nav.setContentsMargins(0, 0, 0, 0)
        # wide enough for the longest name with the padding of the style
        holder.setMinimumWidth(max(nav_button.sizeHint().width() for nav_button in self.nav_buttons.values()) + 40)
        pages.addWidget(holder)
        pages.addWidget(self.settings_stack, 1)
        self.nav_buttons[SETTINGS_PAGES[0]].setChecked(True)
        return settings

    def _bar(self, name: str, content: QWidget) -> QToolBar:
        """A bar of the window that stays where it is: the header, the rail or the footer."""
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
        view = bar.addMenu("&View")
        assert view is not None
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
        self.restart_button = QPushButton("Restart the service")
        set_icon(self.restart_button, "restart")
        self.restart_button.clicked.connect(self._restart)
        self.restart_button.hide()
        layout.addWidget(self.restart_button)
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
            self.nav_buttons[name].setChecked(True)
            self.settings_stack.setCurrentIndex(SETTINGS_PAGES.index(name))
            name = "settings"
        self.rail_buttons[name].setChecked(True)
        self.stack.setCurrentIndex([entry[0] for entry in RAIL].index(name))

    @property
    def current_page(self) -> str:
        name = RAIL[self.stack.currentIndex()][0]
        return SETTINGS_PAGES[self.settings_stack.currentIndex()] if name == "settings" else name

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
        state = "new file" if not self.document.exists else "unsaved changes" if modified else "saved"
        self.path_label.setText(f"{self.document.path}  ·  {state}")
        self._show_savable()
        for widget in (self.revert_button, self.revert_action):
            widget.setEnabled(modified)
        for widget in (self.undo_button, self.undo_action):
            widget.setEnabled(self.history.can_undo)
        for widget in (self.redo_button, self.redo_action):
            widget.setEnabled(self.history.can_redo)
        self.live_preview.document_changed()
        self.refresh_preview()

    def refresh_preview(self) -> None:
        """Shows the device (live while the daemon tells what it shows) and whether it runs the file."""
        snapshot = self.live.snapshot
        self._show_live_preview(snapshot)
        self.device_view.show_live(snapshot)
        shows_document = previewed(snapshot, self.validation.config, self.live_preview.running)
        saved = self.document.saved_config
        device = saved.device.name if saved is not None else "the device"
        hosting = self.hosted is not None
        show_status(self.mode_pill, preview_status(self.daemon, snapshot, device, hosting))
        offered = offers_virtual_device(snapshot, hosting)
        self.mode_pill.setCursor(Qt.CursorShape.PointingHandCursor if offered else Qt.CursorShape.ArrowCursor)
        mqtt = header_status(snapshot)
        self.mqtt_pill.setVisible(mqtt is not None)
        if mqtt is not None:
            show_status(self.mqtt_pill, Status(mqtt.text, mqtt.tone, f"{mqtt.tip} Click for the settings."))
        slots = slots_status(snapshot)
        self.slots_pill.setVisible(slots is not None)
        if slots is not None:
            show_status(self.slots_pill, slots)
        self.states_page.show_live(snapshot)
        self.mqtt_page.show_live(snapshot)
        self.voip_page.show_live(snapshot)
        sync = sync_status(
            self.daemon,
            snapshot,
            self.document.path,
            saved if self.document.exists else None,
            self.document.modified,
            self.applying.isActive(),
            shows_document and self.document.modified,
        )
        set_text(self.sync_label, sync.text)
        self.sync_label.setToolTip(sync.tip)
        self._show_savable()

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

    def _show_live_preview(self, snapshot: Snapshot | None) -> None:
        """The switch of the live preview (off while it can't be on), its pill, and what the daemon said."""
        preview = self.live_preview
        reason = unavailable(self.daemon, snapshot, self.document.path, self.live.owned)
        if reason is not None:
            preview.set_on(False)
        elif self.resume_live_preview:
            self.resume_live_preview = False
            preview.set_on(True)
        self.preview_switch.setEnabled(reason is None)
        with QSignalBlocker(self.preview_switch):
            self.preview_switch.setChecked(preview.on)
        tip = reason or (
            "The device runs the changes in the editor while they are not saved, and the file again once this is "
            "off or the window closes"
        )
        for widget in (self.preview_switch, self.preview_label):
            widget.setToolTip(tip)
        pill = preview_pill(preview.on, preview.running, self.document.modified, self.validation.config is None)
        self.preview_pill.setVisible(pill is not None)
        if pill is not None:
            show_status(self.preview_pill, pill)
        message = f"The device keeps the version before: {preview.error}" if preview.error else preview.notice
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
        """Shows the page of the problem."""
        match problem.path:
            case ("channel", str(name), *_):
                self.channels_page.select(("channel", name))
                self.show_page("channels")
            case ("pool", "auto", *_):
                self.channels_page.select(("pool", "auto"))
                self.show_page("channels")
            case ("people", *_):
                self.channels_page.select(("people",))
                self.show_page("channels")
            case ("state", str(name), *_):
                self.states_page.select(name)
                self.show_page("states")
            case ("slots" | "controls", str(slot), *_) if slot.isdigit() and 1 <= int(slot) <= protocol.STRIPS:
                self.device_view.select(int(slot) - 1)
            case ("slots" | "controls", *_):
                self.show_page("slots")
            case (str(name), *_) if name in SECTIONS or name == "aliases":
                self.show_page(name)
            case _:
                # a problem of the whole configuration, e.g. homeassistant channels without [mqtt]
                for name in SECTIONS:
                    if f"[{name}]" in problem.message:
                        self.show_page(name)

    def set_theme(self, mode: ThemeMode) -> None:
        apply_theme(mode)
        self.theme_actions[mode].setChecked(True)
        # the icons are drawn in the colors of the theme
        refresh_icons(self)
        refresh_help(self)
        self.device_view.preview.update()

    # -- editing --------------------------------------------------------------------------------------------------

    def undo(self) -> None:
        if self.editor.undo():
            self.status.setText("Undone.")

    def redo(self) -> None:
        if self.editor.redo():
            self.status.setText("Redone.")

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        assert event is not None
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and (event.matches(QKeySequence.StandardKey.Undo) or event.matches(QKeySequence.StandardKey.Redo))
        ):
            # kept from the text fields: the shortcuts of the window undo and redo
            event.ignore()
            return True
        if event.type() == QEvent.Type.Wheel and isinstance(event, QWheelEvent) and _takes_wheel(watched):
            # the wheel scrolls the page under a field instead of changing its value by accident
            assert isinstance(watched, QWidget)
            area = watched.parentWidget()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:
                viewport = area.viewport()
                assert viewport is not None
                QApplication.sendEvent(
                    viewport,
                    QWheelEvent(
                        QPointF(watched.mapTo(viewport, event.position().toPoint())),
                        event.globalPosition(),
                        event.pixelDelta(),
                        event.angleDelta(),
                        event.buttons(),
                        event.modifiers(),
                        event.phase(),
                        event.inverted(),
                    ),
                )
            return True
        return False

    # -- the sound server -----------------------------------------------------------------------------------------

    def load_audio(self) -> None:
        self.audio_label.setText("Reading the sound server…")
        self.loader.load()

    def _audio_loaded(self, state: AudioState) -> None:
        self.audio = state
        self.audio_label.setText(f"Sound server: {sources.summary(state)}")
        self.audio_label.setToolTip("")
        self._audio_changed()

    def _audio_failed(self, message: str) -> None:
        self.audio = DISCONNECTED
        self.audio_label.setText("Sound server not reachable: type names by hand")
        self.audio_label.setToolTip(message)
        self._audio_changed()

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
        self.editor.revert()
        self.status.setText("Reverted to the file. Ctrl+Z brings the changes back.")

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
        ratio = self.devicePixelRatioF()
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        return Session(
            history=self.history,
            page=self.current_page,
            geometry=QRect(
                round(geometry.x() * ratio),
                round(geometry.y() * ratio),
                round(geometry.width() * ratio),
                round(geometry.height() * ratio),
            ),
            maximized=self.isMaximized(),
            audio=self.audio,
            live_preview=self.live_preview.on,
        )

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
            if self.live_preview.running:
                question += " The device runs them now (live preview): without saving, it goes back to the file."
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
        self.live_preview.set_on(False)
        self.close_virtual_device()
        save_window_state(bytes(self.saveState()))
        app = QApplication.instance()
        assert app is not None
        app.removeEventFilter(self)
        event.accept()
