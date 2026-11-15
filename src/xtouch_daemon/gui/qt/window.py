"""
The main window. From the top: the file and the service; the strips as the device shows them, which is also where a
strip is picked; then two tabs that keep apart what applies to one strip and what applies to all of them; and at the
bottom the problems, undo and saving.
"""

import threading
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QKeyEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon import instance, protocol
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.audio.pulse import SoundServerError
from xtouch_daemon.config import Problem
from xtouch_daemon.gui.domain import broker, sources
from xtouch_daemon.gui.domain.apply import apply, describe
from xtouch_daemon.gui.domain.broker import header_status
from xtouch_daemon.gui.domain.document import SECTIONS, ConfigDocument
from xtouch_daemon.gui.domain.history import History
from xtouch_daemon.gui.domain.looks import faces, looks
from xtouch_daemon.gui.domain.status import Status, Tone, preview_status, sync_status
from xtouch_daemon.gui.qt import theme
from xtouch_daemon.gui.qt.fields import flat_button, label, show_status
from xtouch_daemon.gui.qt.live_view import LiveView
from xtouch_daemon.gui.qt.pages import (
    GLOBAL_PAGES,
    AliasesPage,
    BrokerTest,
    BrokerTester,
    MqttPage,
    Page,
    SectionPage,
    StripPage,
    page_title,
)
from xtouch_daemon.gui.qt.preview import Preview
from xtouch_daemon.instance import Instance
from xtouch_daemon.systemd import UNIT_NAME, Service, ServiceError, ServiceState, executable, unit_path

SERVICE_POLL_MS = 3000
APPLY_GRACE_MS = 2000
"""How long a reload may take before the window says that the daemon did not take the file."""
STRIP_TAB, GLOBAL_TAB = 0, 1


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
            self.failed.emit(str(e))
        else:
            self.loaded.emit(state)


_pill = show_status


class MainWindow(QMainWindow):
    def __init__(
        self,
        document: ConfigDocument,
        service: Service,
        read_audio: Callable[[], AudioState],
        find_daemon: Callable[[], Instance | None] = instance.running,
        live_socket: Path | None = None,
        try_broker: BrokerTest = broker.try_broker,
    ):
        """
        `live_socket` is where the daemon serves its live view, by default `instance.socket_file()`. `try_broker` tries
        the settings of the [mqtt] section.
        """
        super().__init__()
        self.try_broker = try_broker
        self.document = document
        self.service = service
        self.find_daemon = find_daemon
        self.daemon: Instance | None = None
        self.audio = DISCONNECTED
        self.selected = 0
        self.validation = document.validate()
        self.history = History(document)
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
        body.setSpacing(theme.Space.M)
        body.addLayout(self._preview_area())
        body.addWidget(self._tabs(), 1)
        layout.addLayout(body, 1)
        layout.addWidget(self._footer())
        self.setCentralWidget(root)

        QShortcut(QKeySequence.StandardKey.Save, self, self.save)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo)
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
        self.select(0)
        # the keys start on the strips (the arrows pick one), not on the first button of the header
        self.preview.strips[0].setFocus()

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
        self.service_button = QPushButton()
        # a key typed into the window right after it opened must not install or start a service
        self.service_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.service_button.clicked.connect(self._service_action)
        layout.addWidget(self.service_button)
        layout.addSpacing(8)
        self.theme_button = flat_button("theme-light-dark", "Switch between the dark and the light theme")
        self.theme_button.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_button)
        return header

    def _preview_area(self) -> QVBoxLayout:
        area = QVBoxLayout()
        area.setSpacing(theme.Space.S)
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
        area.addLayout(top)
        self.preview = Preview()
        self.preview.clicked.connect(self.select)
        self.preview.moved.connect(self._moved)
        self.preview.configure.connect(self._configure)
        self.preview.remove.connect(self.remove_strip)
        line = QHBoxLayout()
        line.addStretch()
        line.addWidget(self.preview)
        line.addStretch()
        area.addLayout(line)
        return area

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
        self.pages: dict[str, Page] = {"strip": self.strip_page}
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
        """Shows the page of the selected strip ("strip"), or one of the global settings."""
        if name != "strip":
            self.nav_buttons[name].setChecked(True)
            self.stack.setCurrentIndex(GLOBAL_PAGES.index(name))
        self.tabs.setCurrentIndex(STRIP_TAB if name == "strip" else GLOBAL_TAB)

    @property
    def current_page(self) -> str:
        if self.tabs.currentIndex() == STRIP_TAB:
            return "strip"
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
        self.preview.show_faces(faces(strip_looks, snapshot, edited), selected)
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
            self.service_button.hide()
            return
        try:
            state = self.service.state()
        except ServiceError as e:
            self.service_state = None
            _pill(self.pill, Status("unavailable", Tone.BAD, str(e)))
            self.service_button.hide()
            return
        self.service_state = state
        if not state.installed:
            tone, text, tip = Tone.WARN, "Install and start", "Write the systemd user unit, enable and start it"
        elif state.running:
            tone, text, tip = Tone.GOOD, "Restart", "Restart the daemon, e.g. after changing the device name"
        else:
            tone = Tone.BAD if state.active == "failed" else Tone.NEUTRAL
            text, tip = "Start", "Enable the service and start it"
        _pill(self.pill, Status(state.describe(), tone, f"systemctl --user status {UNIT_NAME}"))
        self.service_button.setText(text)
        self.service_button.setToolTip(tip)
        self.service_button.show()

    def _service_action(self) -> None:
        state = self.service_state
        assert state is not None, "the button shows only with a known state"
        if not state.running:
            question = (
                f"Write {unit_path()}, then enable and start the service?"
                if not state.installed
                else f"Enable {UNIT_NAME} (it starts with the session from now on) and start it?"
            )
            answer = QMessageBox.question(self, "Service", question)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            if not state.installed:
                path = self.service.install(executable(), start=True)
                self.status.setText(f"Installed {path} and started the service.")
            elif state.running:
                self.service.restart()
                self.status.setText("Restarted the service.")
            else:
                self.service.start()
                self.status.setText("Started the service.")
        except ServiceError as e:
            QMessageBox.warning(self, "Service", str(e))
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

    def closeEvent(self, event: QCloseEvent | None) -> None:
        assert event is not None
        if self.document.modified:
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
