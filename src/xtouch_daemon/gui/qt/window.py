"""
The main window. From the top: the file and the service; the strips as the device shows them, which is also where a
strip is picked; then two tabs that keep apart what applies to one strip and what applies to all of them; and at the
bottom the problems, undo and saving.
"""

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEvent, QObject, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QShortcut,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon import installed_version, instance, live, protocol
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.audio.pulse import SoundServerError
from xtouch_daemon.config import Problem
from xtouch_daemon.gui.domain import broker, sources
from xtouch_daemon.gui.domain.apply import apply, describe
from xtouch_daemon.gui.domain.broker import header_status
from xtouch_daemon.gui.domain.document import SECTIONS, ConfigDocument
from xtouch_daemon.gui.domain.history import History
from xtouch_daemon.gui.domain.looks import faces, looks
from xtouch_daemon.gui.domain.status import Status, Tone, outdated, preview_status, sync_status, unit_status
from xtouch_daemon.gui.qt import theme
from xtouch_daemon.gui.qt.fields import flat_button, label, show_status
from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.gui.qt.pages import (
    GLOBAL_PAGES,
    AliasesPage,
    BrokerTest,
    BrokerTester,
    LayoutPage,
    MqttPage,
    Page,
    SectionPage,
    StripPage,
    page_title,
)
from xtouch_daemon.gui.qt.preview import Preview
from xtouch_daemon.instance import Instance
from xtouch_daemon.systemd import (
    UNIT_NAME,
    Service,
    ServiceError,
    ServiceState,
    executable,
    overrides_packaged_unit,
    unit_path,
    uses_packaged_unit,
)

SERVICE_POLL_MS = 3000
APPLY_GRACE_MS = 2000
"""How long a reload may take before the window says that the daemon did not take the file."""
STRIP_TAB, GLOBAL_TAB, LAYOUT_TAB = 0, 1, 2
ACTIVE_MARK = " ●"
"""Next to the name of the layout the device shows."""


class AudioLoader(QObject):
    """Reads the sound server in a thread, so a slow or missing one does not block the window."""

    loaded = pyqtSignal(object, arguments=["state"])
    failed = pyqtSignal(str, arguments=["message"])

    def __init__(self, read: Callable[[], AudioState]):
        super().__init__()
        self._read = read

    def load(self) -> None:
        threading.Thread(target=self._run, name="sound server", daemon=True).start()

    def _run(self) -> None:
        try:
            state = self._read()
        except SoundServerError as e:
            self._emit(self.failed, str(e))
        else:
            self._emit(self.loaded, state)

    @staticmethod
    def _emit(signal: Any, value: object) -> None:
        # the window may be gone meanwhile, e.g. for a new zoom
        with contextlib.suppress(RuntimeError):
            signal.emit(value)


_pill = show_status


@dataclass(frozen=True)
class Session:
    """
    What a window hands to the next one when the zoom changes (see `run_gui`): Qt scales a whole application only when
    it starts, so a new zoom takes a new window, which goes on where the old one was.
    """

    history: History
    """The undo history, and through it the document with its unsaved changes."""
    selected: int
    page: str
    geometry: QRect
    """Where the window was, in pixels of the screen (the zoom changes the size of a window's own pixels)."""
    maximized: bool
    audio: AudioState
    preview_share: float | None
    """The share of the height the preview has, None while it has not been dragged."""


EDITOR_MIN_HEIGHT = 160
"""The editor below the preview keeps room for a few rows when the preview is dragged large."""
GRIP = (36, 4)
"""The grip on the handle between the preview and the editor: a short bar that shows it can be dragged."""


class _GripHandle(QSplitterHandle):
    """The handle between the preview and the editor, with a grip in the middle, brighter under the mouse."""

    def __init__(self, orientation: Qt.Orientation, parent: PreviewSplitter):
        super().__init__(orientation, parent)
        self.owner = parent
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setToolTip("Drag to make the strips larger or smaller")
        self.move_to: QMouseEvent | None = None
        """The last move of the mouse that the handle has not followed yet."""

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        super().mousePressEvent(event)
        self.owner.held.emit(True)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        """
        Follows the mouse once for all the moves that came in together: each step lays out the window again, and a
        fast mouse sends more of them than the screen shows.
        """
        assert event is not None
        if self.move_to is None:
            QTimer.singleShot(0, self._follow)
        self.move_to = event.clone()

    def _follow(self) -> None:
        event, self.move_to = self.move_to, None
        if event is not None:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        self._follow()
        super().mouseReleaseEvent(event)
        self.owner.held.emit(False)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme.current_colors()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors.text_muted if self.underMouse() else colors.control_border))
        width, height = GRIP
        grip = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
        painter.drawRoundedRect(grip, height / 2, height / 2)


class PreviewSplitter(QSplitter):
    """The preview above, the editor below, and a handle with a grip between them."""

    held = pyqtSignal(bool, arguments=["held"])
    """The handle was pressed (True) or let go (False)."""

    def __init__(self):
        super().__init__(Qt.Orientation.Vertical)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(theme.Space.M)

    def createHandle(self) -> QSplitterHandle:
        return _GripHandle(self.orientation(), self)

    @property
    def share(self) -> float:
        """The share of the height the preview has."""
        top, bottom = self.sizes()
        return top / (top + bottom)

    @share.setter
    def share(self, share: float) -> None:
        total = sum(self.sizes())
        top = round(total * share)
        self.setSizes([top, total - top])


class MainWindow(QMainWindow):
    def __init__(
        self,
        document: ConfigDocument,
        service: Service,
        read_audio: Callable[[], AudioState],
        find_daemon: Callable[[], Instance | None] = instance.running,
        live_socket: Path | None = None,
        try_broker: BrokerTest = broker.try_broker,
        session: Session | None = None,
    ):
        """
        `live_socket` is where the daemon serves its live view, by default `instance.socket_file()`. `try_broker` tries
        the settings of the [mqtt] section.
        """
        super().__init__()
        self.try_broker = try_broker
        self.zoom = theme.load_zoom()
        self.rezoom: float | None = None
        """The zoom the next window gets: set when this one closes for a new zoom (see `Session`)."""
        self.document = document
        self.service = service
        self.find_daemon = find_daemon
        self.daemon: Instance | None = None
        self.audio = DISCONNECTED
        self.selected = 0
        self.validation = document.validate()
        self.history = session.history if session is not None else History(document)
        self.preview_share = session.preview_share if session is not None else theme.load_preview_share()
        """The share of the height the preview has, None while it has not been dragged: then it has its own size."""
        self.service_state: ServiceState | None = None
        self.setWindowTitle("X-Touch Extender")
        self.resize(1000, 960)
        self.applying = QTimer(self)
        """Runs for a moment after a reload, while the daemon takes the file."""
        self.applying.setSingleShot(True)
        self.applying.setInterval(APPLY_GRACE_MS)
        self.applying.timeout.connect(self.refresh_preview)
        self.live = LiveView(live_socket or instance.socket_file())
        self.live.changed.connect(lambda _: self.refresh_preview())

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header())
        body = QVBoxLayout()
        body.setContentsMargins(theme.Space.XL, theme.Space.L, theme.Space.XL, 0)
        body.setSpacing(theme.Space.S)
        body.addLayout(self._preview_status())
        body.addLayout(self._layout_bar())
        self.splitter = PreviewSplitter()
        self.splitter.addWidget(self._preview())
        tabs = self._tabs()
        tabs.setMinimumHeight(EDITOR_MIN_HEIGHT)
        self.splitter.addWidget(tabs)
        # a larger window gives the room to the editor, the preview keeps its size until the handle is dragged
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(self._preview_resized)
        self.splitter.held.connect(self._handle_held)
        body.addWidget(self.splitter, 1)
        layout.addLayout(body, 1)
        layout.addWidget(self._footer())
        self.setCentralWidget(root)

        QShortcut(QKeySequence.StandardKey.Save, self, self.save)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo)
        # Ctrl++ (on keyboards with a + key) and Ctrl+= (where + is Shift+=)
        for keys, action in (
            (QKeySequence.StandardKey.ZoomIn, self.zoom_in),
            (QKeySequence("Ctrl+="), self.zoom_in),
            (QKeySequence.StandardKey.ZoomOut, self.zoom_out),
            (QKeySequence("Ctrl+0"), self.zoom_reset),
        ):
            QShortcut(keys, self, action)
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
        self.load_audio()
        self.refresh_service()
        self.select(0 if session is None else session.selected)
        if session is not None:
            self._resume(session)
        # the keys start on the strips (the arrows pick one), not on the first button of the header
        self.preview.strips[self.selected].setFocus()

    def showEvent(self, event: QShowEvent | None) -> None:
        """Gives the preview its share of the height, now that the window has its size."""
        super().showEvent(event)
        if self.preview_share is not None:
            self.splitter.share = self.preview_share

    def _preview_resized(self) -> None:
        """The handle was dragged: the share of the preview is kept for the next start (once it is let go)."""
        self.preview_share = self.splitter.share

    def _handle_held(self, held: bool) -> None:
        """
        While the handle is held, the strips scale their pictures; once it is let go, they are drawn sharp, and the
        share of the preview is saved (not on every step of a drag, which would slow it down).
        """
        self.preview.hold(held)
        if not held and self.preview_share is not None:
            theme.save_preview_share(self.preview_share)

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
        self.refresh()

    # -- building -------------------------------------------------------------------------------------------------

    def _header(self) -> QWidget:
        header = QWidget()
        theme.set_role(header, "bar")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(theme.Space.XL, theme.Space.M, theme.Space.L, theme.Space.M)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label("X-Touch Extender", "title"))
        self.path_label = label("", "hint")
        titles.addWidget(self.path_label)
        layout.addLayout(titles)
        layout.addStretch()
        layout.addWidget(label("Service", "hint"))
        self.pill = label("…", "pill")
        layout.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.unit_label = label("", "hint")
        """Which unit is in effect: the package's, or one in ~/.config and the program it starts."""
        layout.addWidget(self.unit_label)
        self.service_button = QPushButton()
        # a key typed into the window right after it opened must not install or start a service
        self.service_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.service_button.clicked.connect(self._service_action)
        layout.addWidget(self.service_button)
        self.override_button = QPushButton("Use the packaged unit")
        self.override_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.override_button.clicked.connect(self._remove_override)
        layout.addWidget(self.override_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setToolTip("Stop the daemon: the device goes dark until the service starts again")
        self.stop_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stop_button.clicked.connect(self._stop)
        layout.addWidget(self.stop_button)
        layout.addSpacing(8)
        self.zoom_button = QToolButton()
        self.zoom_button.setText(theme.zoom_text(self.zoom))
        self.zoom_button.setToolTip("Zoom: Ctrl++ larger, Ctrl+- smaller, Ctrl+0 100 %")
        self.zoom_button.setAutoRaise(True)
        self.zoom_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.zoom_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        theme.set_role(self.zoom_button, "flat", "variant")
        zooms = QMenu(self.zoom_button)
        for level in theme.ZOOM_LEVELS:
            action = zooms.addAction(theme.zoom_text(level))
            assert action is not None
            action.setCheckable(True)
            action.setChecked(level == self.zoom)
            action.triggered.connect(lambda _=False, level=level: self.zoom_to(level))
        self.zoom_button.setMenu(zooms)
        layout.addWidget(self.zoom_button)
        self.theme_button = flat_button("theme-light-dark", "Switch between the dark and the light theme")
        self.theme_button.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_button)
        return header

    def _preview_status(self) -> QHBoxLayout:
        """What the preview shows (live or the file), the connection to Home Assistant, and the sound server."""
        top = QHBoxLayout()
        self.mode_pill = label("", "pill")
        top.addWidget(self.mode_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.mqtt_pill = label("", "pill")
        self.mqtt_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mqtt_pill.mousePressEvent = lambda event: self.show_page("mqtt")  # type: ignore[method-assign]
        top.addWidget(self.mqtt_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.sync_label = label("", "hint", wrap=True)
        top.addWidget(self.sync_label, 1)
        self.audio_label = label("Reading the sound server…", "hint")
        top.addWidget(self.audio_label)
        self.refresh_audio = flat_button("refresh", "Read the devices and applications of the sound server again")
        self.refresh_audio.clicked.connect(self.load_audio)
        top.addWidget(self.refresh_audio)
        return top

    def _layout_bar(self) -> QHBoxLayout:
        """The layouts: one tab each, the one the device shows marked; + adds one, and one button shows it there."""
        bar = QHBoxLayout()
        bar.addWidget(label("Layout", "hint"))
        self.layout_tabs = QTabBar()
        self.layout_tabs.setDrawBase(False)
        self.layout_tabs.setExpanding(False)
        self.layout_tabs.setToolTip(f"The layouts of the file; {ACTIVE_MARK.strip()} marks the one the device shows")
        self.layout_tabs.currentChanged.connect(self._layout_picked)
        bar.addWidget(self.layout_tabs)
        self.add_layout_button = QToolButton()
        self.add_layout_button.setIcon(theme.icon("plus"))
        self.add_layout_button.setToolTip("Add a layout")
        self.add_layout_button.setAutoRaise(True)
        self.add_layout_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.add_layout_button)
        empty = menu.addAction("Empty layout (auto strips)")
        assert empty is not None
        empty.triggered.connect(lambda: self.add_layout(copy_strips=False))
        copied = menu.addAction("Copy of this layout")
        assert copied is not None
        copied.triggered.connect(lambda: self.add_layout(copy_strips=True))
        self.add_layout_button.setMenu(menu)
        bar.addWidget(self.add_layout_button)
        bar.addStretch()
        self.show_layout_button = QPushButton("Show on the device")
        self.show_layout_button.setToolTip("Switch the running daemon to this layout (as saved)")
        self.show_layout_button.clicked.connect(self.show_layout_on_device)
        bar.addWidget(self.show_layout_button)
        self._fill_layout_tabs()
        return bar

    def _fill_layout_tabs(self) -> None:
        """The tabs of the layouts, again: after one was added, removed, renamed or moved, or another one shown."""
        snapshot = self.live.snapshot
        active = (snapshot.layout or "default") if snapshot is not None else None
        names = self.document.layout_names
        self.layout_tabs.blockSignals(True)
        while self.layout_tabs.count() > len(names):
            self.layout_tabs.removeTab(self.layout_tabs.count() - 1)
        for index, name in enumerate(names):
            text = (name or "(no name)") + (ACTIVE_MARK if name == active else "")
            if index < self.layout_tabs.count():
                self.layout_tabs.setTabText(index, text)
            else:
                self.layout_tabs.addTab(text)
        edited = self.document.layout
        self.layout_tabs.setCurrentIndex(0 if edited is None else edited + 1)
        self.layout_tabs.blockSignals(False)
        showable = snapshot is not None and active != self.document.layout_name
        self.show_layout_button.setVisible(bool(self.document.layouts))
        self.show_layout_button.setEnabled(
            showable and snapshot is not None and self.document.layout_name in snapshot.layouts
        )

    def _layout_picked(self, index: int) -> None:
        self.edit_layout(None if index <= 0 else index - 1)

    def edit_layout(self, index: int | None) -> None:
        """Shows the strips of another layout (an index of the layouts of the document, None for the default one)."""
        self.document.edit_layout(index)
        self.selected = min(self.selected, protocol.STRIPS - 1)
        self.reload_pages()
        self._fill_layout_tabs()

    def add_layout(self, copy_strips: bool) -> None:
        self.document.add_layout(copy_strips)
        self.edited()
        self.edit_layout(self.document.layout)
        self.show_page("layout")
        self.status.setText(f"Added the layout {self.document.layout_name}. Name it on the page Layout.")

    def _layouts_changed(self, index: int | None) -> None:
        """After the layout page removed or moved a layout."""
        self.edited()
        self.edit_layout(index)
        self.show_page("layout")

    def show_layout_on_device(self) -> None:
        name = self.document.layout_name
        if self.live.send(live.command(layout=name)):
            self.status.setText(f"Asked the daemon to show the layout {name}.")

    def _preview(self) -> Preview:
        self.preview = Preview()
        self.preview.clicked.connect(self.select)
        self.preview.moved.connect(self._moved)
        self.preview.configure.connect(self._configure)
        self.preview.remove.connect(self.remove_strip)
        # it scales itself to the space the handle below it gives it, centered
        return self.preview

    def _tabs(self) -> QTabWidget:
        """What applies to the selected strip, and what applies to all of them, apart."""
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        def audio() -> AudioState:
            # the pages ask for the current one every time
            return self.audio

        self.strip_page = StripPage(
            self.document, audio, self.edited, self._strips_changed, self.show_page, self.remove_strip
        )
        self.layout_page = LayoutPage(self.document, audio, self.edited, self._layouts_changed)
        self.pages: dict[str, Page] = {"strip": self.strip_page, "layout": self.layout_page}
        for name in GLOBAL_PAGES:
            if name == "aliases":
                self.pages[name] = AliasesPage(self.document, audio, self.edited)
            elif name == "mqtt":
                self.mqtt_page = MqttPage(self.document, audio, self.edited, BrokerTester(self.try_broker))
                self.pages[name] = self.mqtt_page
            else:
                self.pages[name] = SectionPage(name, self.document, audio, self.edited)
        self.tabs.addTab(self._scroll(self.strip_page), theme.icon("tune-vertical"), "Strip 1")
        self.tabs.setTabToolTip(STRIP_TAB, "The options of the strip selected above: they apply to it alone")

        settings = QWidget()
        layout = QVBoxLayout(settings)
        layout.setContentsMargins(0, theme.Space.M, 0, 0)
        layout.addWidget(label("These settings apply to the daemon and to every strip.", "hint"))
        pages = QHBoxLayout()
        pages.setSpacing(16)
        nav = QVBoxLayout()
        nav.setSpacing(2)
        self.nav = QButtonGroup(self)
        self.stack = QStackedWidget()
        self.nav_buttons: dict[str, QPushButton] = {}
        for name in GLOBAL_PAGES:
            button = QPushButton(page_title(name))
            theme.set_role(button, "nav", "variant")
            button.setCheckable(True)
            button.setToolTip(f"[{name}] in the file")
            button.clicked.connect(lambda _=False, name=name: self.show_page(name))
            self.nav.addButton(button)
            self.nav_buttons[name] = button
            nav.addWidget(button)
            self.stack.addWidget(self._scroll(self.pages[name]))
        nav.addStretch()
        holder = QWidget()
        holder.setLayout(nav)
        nav.setContentsMargins(0, 0, 0, 0)
        # wide enough for the longest name with the padding of the style
        holder.setMinimumWidth(max(button.sizeHint().width() for button in self.nav_buttons.values()) + 40)
        pages.addWidget(holder)
        pages.addWidget(self.stack, 1)
        layout.addLayout(pages, 1)
        self.tabs.addTab(settings, theme.icon("cog-outline"), "Global settings")
        self.tabs.setTabToolTip(GLOBAL_TAB, "Behavior, aliases, the Home Assistant connection and the device")
        self.tabs.addTab(self._scroll(self.layout_page), theme.icon("view-dashboard-variant-outline"), "Layout")
        self.tabs.setTabToolTip(LAYOUT_TAB, "The layout shown above: its name, and when the device switches to it")
        self.nav_buttons[GLOBAL_PAGES[0]].setChecked(True)
        self.tabs.currentChanged.connect(lambda _: self.refresh_preview())
        return self.tabs

    @staticmethod
    def _scroll(page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _footer(self) -> QWidget:
        footer = QWidget()
        theme.set_role(footer, "bar")
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(theme.Space.XL, theme.Space.M, theme.Space.XL, theme.Space.M)
        self.problems_button = QToolButton()
        theme.set_role(self.problems_button, "problems")
        self.problems_button.setIcon(theme.icon("alert-circle", theme.current_colors().error))
        self.problems_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.problems_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.problems_menu = QMenu(self.problems_button)
        self.problems_button.setMenu(self.problems_menu)
        layout.addWidget(self.problems_button)
        self.status = label("", "hint", wrap=True)
        layout.addWidget(self.status, 1)
        self.restart_button = QPushButton(theme.icon("restart"), "Restart the service")
        self.restart_button.clicked.connect(self._restart)
        self.restart_button.hide()
        layout.addWidget(self.restart_button)
        self.undo_button = flat_button("undo", "Undo (Ctrl+Z)")
        self.undo_button.clicked.connect(self.undo)
        layout.addWidget(self.undo_button)
        self.redo_button = flat_button("redo", "Redo (Ctrl+Shift+Z)")
        self.redo_button.clicked.connect(self.redo)
        layout.addWidget(self.redo_button)
        self.revert_button = QPushButton(theme.icon("file-undo-outline"), "Revert")
        self.revert_button.setToolTip("Drop the changes and read the file again (Undo brings them back)")
        self.revert_button.clicked.connect(self.revert)
        layout.addWidget(self.revert_button)
        self.save_button = QPushButton(theme.icon("content-save", "white"), "Save and apply")
        theme.set_role(self.save_button, "primary", "variant")
        self.save_button.setToolTip("Write the file and reload the daemon (Ctrl+S)")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        return footer

    # -- showing --------------------------------------------------------------------------------------------------

    def select(self, index: int) -> None:
        """Shows the options of a strip."""
        self.selected = index
        self.strip_page.show_strip(index)
        self.show_page("strip")
        self.refresh()

    def show_page(self, name: str) -> None:
        """Shows the page of the selected strip ("strip"), of the layout ("layout"), or one of the global settings."""
        if name not in ("strip", "layout"):
            self.nav_buttons[name].setChecked(True)
            self.stack.setCurrentIndex(GLOBAL_PAGES.index(name))
        self.tabs.setCurrentIndex({"strip": STRIP_TAB, "layout": LAYOUT_TAB}.get(name, GLOBAL_TAB))

    @property
    def current_page(self) -> str:
        if self.tabs.currentIndex() == STRIP_TAB:
            return "strip"
        if self.tabs.currentIndex() == LAYOUT_TAB:
            return "layout"
        return GLOBAL_PAGES[self.stack.currentIndex()]

    def refresh(self) -> None:
        """Validates the configuration and shows the result everywhere."""
        self.validation = self.document.validate()
        for page in self.pages.values():
            page.show_problems(self.validation)
        self._show_problems(self.validation.problems)
        modified = self.document.modified
        state = "new file" if not self.document.exists else "unsaved changes" if modified else "saved"
        self.path_label.setText(f"{self.document.path}  ·  {state}")
        self.save_button.setEnabled(self.validation.config is not None and (modified or not self.document.exists))
        self.revert_button.setEnabled(modified)
        self.undo_button.setEnabled(self.history.can_undo)
        self.redo_button.setEnabled(self.history.can_redo)
        self.refresh_preview()

    def refresh_preview(self) -> None:
        """Shows the strips (live while the daemon tells what the device shows) and whether it runs the file."""
        snapshot = self.live.snapshot
        edited = tuple(self.document.strip_changed(index) for index in range(protocol.STRIPS))
        strip_looks = looks(self.document, self.validation, self.audio)
        selected = self.selected if self.tabs.currentIndex() == STRIP_TAB else None
        # live only while the device shows the layout being edited
        live_layout = (snapshot.layout or "default") if snapshot is not None else None
        shown = snapshot if live_layout == self.document.layout_name else None
        self.preview.show_faces(faces(strip_looks, shown, edited), selected)
        self._fill_layout_tabs()
        look = strip_looks[self.selected]
        self.tabs.setTabText(STRIP_TAB, f"Strip {self.selected + 1}" + (f" · {look.label}" if look.label else ""))
        saved = self.document.saved_config
        device = saved.device.name if saved is not None else "the device"
        _pill(self.mode_pill, preview_status(self.daemon, snapshot, device))
        mqtt = header_status(snapshot)
        self.mqtt_pill.setVisible(mqtt is not None)
        if mqtt is not None:
            _pill(self.mqtt_pill, Status(mqtt.text, mqtt.tone, f"{mqtt.tip} Click for the settings."))
        self.mqtt_page.show_live(snapshot)
        sync = sync_status(
            self.daemon,
            snapshot,
            self.document.path,
            saved if self.document.exists else None,
            sum(edited),
            self.document.modified,
            self.applying.isActive(),
        )
        self.sync_label.setText(sync.text)
        self.sync_label.setToolTip(sync.tip)

    def _show_problems(self, problems: list[Problem]) -> None:
        self.problems_button.setVisible(bool(problems))
        self.problems_button.setText(f"{len(problems)} problem{'' if len(problems) == 1 else 's'}")
        self.problems_menu.clear()
        for problem in problems:
            if problem.kind == "extra_forbidden":
                action = QAction(f"{problem.location}: unknown option, click to remove it", self.problems_menu)
                action.triggered.connect(lambda _=False, problem=problem: self._remove_option(problem))
            else:
                action = QAction(str(problem) if problem.path else problem.message, self.problems_menu)
                action.triggered.connect(lambda _=False, problem=problem: self.go_to(problem))
            self.problems_menu.addAction(action)

    def go_to(self, problem: Problem) -> None:
        """Shows the page of the problem."""
        match problem.path:
            case ("strip", int(index), *_):
                self.select(index)
            case ("layouts", str(name), *rest) if name in self.document.layout_names:
                index = self.document.layout_names.index(name)
                self.edit_layout(None if index == 0 else index - 1)
                match rest:
                    case ["strip", int(strip), *_]:
                        self.select(strip)
                    case _:
                        self.show_page("layout")
            case (str(name), *_) if name in self.pages:
                self.show_page(name)
            case _:
                # a problem of the whole configuration, e.g. homeassistant strips without [mqtt]
                for name in SECTIONS:
                    if f"[{name}]" in problem.message:
                        self.show_page(name)

    def _remove_option(self, problem: Problem) -> None:
        self.document.unset(problem.path)
        self._changed()

    def reload_pages(self) -> None:
        """Builds every page again from the document, staying on the page that is shown."""
        page = self.current_page
        for each in self.pages.values():
            each.reload()
        self.strip_page.show_strip(self.selected)
        self.show_page(page)
        self.refresh()

    def toggle_theme(self) -> None:
        dark = theme.current_mode() == theme.ThemeMode.DARK
        theme.apply_theme(theme.ThemeMode.LIGHT if dark else theme.ThemeMode.DARK)
        # the icons are drawn in the text color of the theme
        for button, name in (
            (self.theme_button, "theme-light-dark"),
            (self.refresh_audio, "refresh"),
            (self.undo_button, "undo"),
            (self.redo_button, "redo"),
        ):
            button.setIcon(theme.icon(name))
        self.restart_button.setIcon(theme.icon("restart"))
        self.revert_button.setIcon(theme.icon("file-undo-outline"))
        self.tabs.setTabIcon(STRIP_TAB, theme.icon("tune-vertical"))
        self.tabs.setTabIcon(GLOBAL_TAB, theme.icon("cog-outline"))
        self.tabs.setTabIcon(LAYOUT_TAB, theme.icon("view-dashboard-variant-outline"))
        self.add_layout_button.setIcon(theme.icon("plus"))
        self.reload_pages()

    # -- editing --------------------------------------------------------------------------------------------------

    def edited(self) -> None:
        """After every edit: a step to undo, and everything shows it."""
        self.history.record()
        self.restart_button.hide()
        self.status.setText("")
        self.refresh()

    def _changed(self) -> None:
        """After an edit the pages did not make themselves: they show the document again."""
        self.edited()
        self.reload_pages()

    def _strips_changed(self, selected: int) -> None:
        self.edited()
        self.select(selected)

    def _moved(self, source: int, target: int) -> None:
        self.document.move_strip(source, target)
        self._strips_changed(target)
        self.status.setText(f"Moved strip {source + 1} to place {target + 1}.")

    def _configure(self, index: int) -> None:
        self.document.configure_up_to(index)
        self._strips_changed(index)

    def remove_strip(self, index: int) -> None:
        self.document.remove_strip(index)
        self._strips_changed(index)
        self.status.setText(f"Removed strip {index + 1}, the strips right of it moved left. Ctrl+Z brings it back.")

    def undo(self) -> None:
        if self.history.can_undo:
            self.history.undo()
            self.reload_pages()
            self.status.setText("Undone.")

    def redo(self) -> None:
        if self.history.can_redo:
            self.history.redo()
            self.reload_pages()
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
        return False

    # -- the sound server -----------------------------------------------------------------------------------------

    def load_audio(self) -> None:
        self.audio_label.setText("Reading the sound server…")
        self.loader.load()

    def _audio_loaded(self, state: AudioState) -> None:
        self.audio = state
        self.audio_label.setText(f"Sound server: {sources.summary(state)}")
        self.audio_label.setToolTip("")
        self.refresh()

    def _audio_failed(self, message: str) -> None:
        self.audio = DISCONNECTED
        self.audio_label.setText("Sound server not reachable: type names by hand")
        self.audio_label.setToolTip(message)
        self.refresh()

    # -- the service ----------------------------------------------------------------------------------------------

    def refresh_service(self) -> None:
        """Finds the daemon (and its live view) and the state of the service again."""
        self.daemon = self.find_daemon()
        if self.daemon is None:
            self.live.disconnect_from_daemon()
        else:
            self.live.connect_to_daemon()
        self._show_service()
        self.refresh_preview()

    def _show_service(self) -> None:
        if self.daemon is not None and not self.daemon.systemd:
            # started from a terminal or an IDE: the service can't start (the device is taken) or restart it
            self.service_state = None
            tip = (
                f"The daemon runs outside systemd (process {self.daemon.pid}, e.g. from a terminal or an IDE) "
                f"and reads {self.daemon.config}. Saving reloads it; restart it where it runs."
            )
            _pill(self.pill, Status("running elsewhere", Tone.GOOD, tip))
            self._hide_service_controls()
            return
        try:
            state = self.service.state()
        except ServiceError as e:
            self.service_state = None
            _pill(self.pill, Status("unavailable", Tone.BAD, str(e)))
            self._hide_service_controls()
            return
        self.service_state = state
        highlight = False
        if not state.installed:
            tone, text = Tone.WARN, "Install and start"
            tip = (
                "Enable the unit of the package and start it"
                if uses_packaged_unit()
                else "Write the systemd user unit, enable and start it"
            )
        elif state.running:
            tone, text, tip = Tone.GOOD, "Restart", "Restart the daemon, e.g. after changing the device name"
            reason = outdated(state, self.live.snapshot, installed_version(), executable())
            if reason is not None:
                highlight, tip = True, reason
        else:
            tone = Tone.BAD if state.active == "failed" else Tone.NEUTRAL
            text, tip = "Start", "Enable the service and start it"
        _pill(self.pill, Status(state.describe(), tone, f"systemctl --user status {UNIT_NAME}"))
        self.service_button.setText(text)
        self.service_button.setToolTip(tip)
        theme.set_role(self.service_button, "primary" if highlight else "", "variant")
        self.service_button.show()
        self.stop_button.setVisible(state.running)
        overrides = overrides_packaged_unit()
        unit = unit_status(state, overrides)
        self.unit_label.setVisible(unit is not None)
        if unit is not None:
            self.unit_label.setText(unit.text)
            self.unit_label.setToolTip(unit.tip)
        self.override_button.setToolTip(f"Remove {unit_path()}, which overrides the unit of the package")
        self.override_button.setVisible(overrides)

    def _hide_service_controls(self) -> None:
        for widget in (self.unit_label, self.service_button, self.override_button, self.stop_button):
            widget.hide()

    def _service_action(self) -> None:
        state = self.service_state
        assert state is not None, "the button shows only with a known state"
        if not state.running:
            if state.installed:
                question = f"Enable {UNIT_NAME} (it starts with the session from now on) and start it?"
            elif uses_packaged_unit():
                question = f"Enable {UNIT_NAME} of the package (it starts with the session from now on) and start it?"
            else:
                question = f"Write {unit_path()}, then enable and start the service?"
            answer = QMessageBox.question(self, "Service", question)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            if not state.installed:
                path = self.service.install(executable(), start=True)
                done = "Enabled the unit of the package" if path is None else f"Installed {path}"
                self.status.setText(f"{done} and started the service.")
            elif state.running:
                self.service.restart()
                self.status.setText("Restarted the service.")
            else:
                self.service.start()
                self.status.setText("Started the service.")
        except ServiceError as e:
            QMessageBox.warning(self, "Service", str(e))
        self.refresh_service()

    def _remove_override(self) -> None:
        """Removes the unit in ~/.config, so the one of the package is in effect."""
        question = (
            f"Remove {unit_path()}? The unit of the package takes over; a running service restarts with the program "
            "of the package."
        )
        if QMessageBox.question(self, "Service", question) != QMessageBox.StandardButton.Yes:
            return
        try:
            path = self.service.remove_override()
        except ServiceError as e:
            QMessageBox.warning(self, "Service", str(e))
        else:
            self.status.setText(f"Removed {path}: the service uses the unit of the package.")
        self.refresh_service()

    def _stop(self) -> None:
        """Stops the service but leaves it enabled: Start (or the next session) brings it back."""
        try:
            self.service.stop()
        except ServiceError as e:
            QMessageBox.warning(self, "Service", str(e))
        else:
            self.status.setText("Stopped the service.")
        self.refresh_service()

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
        try:
            self.document.save()
        except OSError as e:
            QMessageBox.critical(self, "Saving failed", str(e))
            return False
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
        self.refresh()
        self.refresh_service()
        return True

    def revert(self) -> None:
        self.document.revert()
        self._changed()
        self.status.setText("Reverted to the file. Ctrl+Z brings the changes back.")

    # -- zoom -----------------------------------------------------------------------------------------------------

    def zoom_in(self) -> None:
        self.zoom_to(theme.zoom_step(self.zoom, 1))

    def zoom_out(self) -> None:
        self.zoom_to(theme.zoom_step(self.zoom, -1))

    def zoom_reset(self) -> None:
        self.zoom_to(1.0)

    def zoom_to(self, zoom: float) -> None:
        """Closes the window for a new one at `zoom` (see `Session`), keeping everything that is not saved."""
        if zoom == self.zoom:
            return
        theme.save_zoom(zoom)
        self.rezoom = zoom
        self.close()

    def session(self) -> Session:
        """What the next window needs to go on where this one is."""
        ratio = self.devicePixelRatioF()
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        return Session(
            history=self.history,
            selected=self.selected,
            page=self.current_page,
            geometry=QRect(
                round(geometry.x() * ratio),
                round(geometry.y() * ratio),
                round(geometry.width() * ratio),
                round(geometry.height() * ratio),
            ),
            maximized=self.isMaximized(),
            audio=self.audio,
            preview_share=self.preview_share,
        )

    def closeEvent(self, event: QCloseEvent | None) -> None:
        assert event is not None
        if self.document.modified and self.rezoom is None:
            buttons = QMessageBox.StandardButton
            answer = QMessageBox.question(
                self,
                "Unsaved changes",
                "Save the changes before closing?",
                buttons.Save | buttons.Discard | buttons.Cancel,
                buttons.Save,
            )
            if answer == buttons.Cancel or (answer == buttons.Save and not self.save()):
                event.ignore()
                return
        app = QApplication.instance()
        assert app is not None
        app.removeEventFilter(self)
        event.accept()
