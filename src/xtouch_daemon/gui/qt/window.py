"""The main window: the service, the preview of the strips, the pages of the editor, and saving."""

import threading
from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon import protocol
from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.audio.pulse import SoundServerError
from xtouch_daemon.config import Problem
from xtouch_daemon.gui.domain import sources
from xtouch_daemon.gui.domain.apply import apply
from xtouch_daemon.gui.domain.document import SECTIONS, ConfigDocument
from xtouch_daemon.gui.domain.looks import looks
from xtouch_daemon.gui.qt import theme
from xtouch_daemon.gui.qt.fields import flat_button, label
from xtouch_daemon.gui.qt.pages import AliasesPage, Page, SectionPage, StripPage
from xtouch_daemon.gui.qt.preview import Preview
from xtouch_daemon.systemd import UNIT_NAME, Service, ServiceError, ServiceState, executable

SERVICE_POLL_MS = 3000
PAGE_TITLES = {"mqtt": "MQTT"}


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


class MainWindow(QMainWindow):
    def __init__(self, document: ConfigDocument, service: Service, read_audio: Callable[[], AudioState]):
        super().__init__()
        self.document = document
        self.service = service
        self.audio = DISCONNECTED
        self.selected = 0
        self.validation = document.validate()
        self.service_state: ServiceState | None = None
        self.setWindowTitle("X-Touch Extender")
        self.resize(1000, 920)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header())
        body = QVBoxLayout()
        body.setContentsMargins(20, 14, 20, 0)
        body.setSpacing(12)
        body.addLayout(self._preview_area())
        body.addLayout(self._pages(), 1)
        layout.addLayout(body, 1)
        layout.addWidget(self._footer())
        self.setCentralWidget(root)

        QShortcut(QKeySequence.StandardKey.Save, self, self.save)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_service)
        self.timer.start(SERVICE_POLL_MS)
        self.loader = AudioLoader(read_audio)
        self.loader.loaded.connect(self._audio_loaded)
        self.loader.failed.connect(self._audio_failed)
        self.load_audio()
        self.refresh_service()
        self.select(0)

    # -- building -------------------------------------------------------------------------------------------------

    def _header(self) -> QWidget:
        header = QWidget()
        theme.set_role(header, "bar")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 10, 14, 10)
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
        self.service_button.clicked.connect(self._service_action)
        layout.addWidget(self.service_button)
        layout.addSpacing(8)
        self.theme_button = flat_button("theme-light-dark", "Switch between the dark and the light theme")
        self.theme_button.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_button)
        return header

    def _preview_area(self) -> QVBoxLayout:
        area = QVBoxLayout()
        area.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(label("The strips as the device shows them: click one to edit it, drag one to move it.", "hint"))
        top.addStretch()
        self.audio_label = label("Reading the sound server…", "hint")
        top.addWidget(self.audio_label)
        self.refresh_audio = flat_button("refresh", "Read the devices and applications of the sound server again")
        self.refresh_audio.clicked.connect(self.load_audio)
        top.addWidget(self.refresh_audio)
        area.addLayout(top)
        self.preview = Preview()
        self.preview.clicked.connect(self.select)
        self.preview.moved.connect(self._moved)
        line = QHBoxLayout()
        line.addStretch()
        line.addWidget(self.preview)
        line.addStretch()
        area.addLayout(line)
        return area

    def _pages(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(16)
        nav = QVBoxLayout()
        nav.setSpacing(2)
        self.nav = QButtonGroup(self)
        self.stack = QStackedWidget()
        self.strip_page = StripPage(self.document, lambda: self.audio, self.edited, self._strips_changed)
        self.pages: dict[str, Page] = {
            "strip": self.strip_page,
            "behavior": SectionPage("behavior", self.document, lambda: self.audio, self.edited),
            "aliases": AliasesPage(self.document, lambda: self.audio, self.edited),
            **{
                name: SectionPage(name, self.document, lambda: self.audio, self.edited)
                for name in SECTIONS
                if name != "behavior"
            },
        }
        self.nav_buttons: dict[str, QPushButton] = {}
        for name, page in self.pages.items():
            button = QPushButton(PAGE_TITLES.get(name, name.capitalize()))
            theme.set_role(button, "nav", "variant")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, name=name: self.show_page(name))
            self.nav.addButton(button)
            self.nav_buttons[name] = button
            nav.addWidget(button)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        nav.addStretch()
        layout.addLayout(nav)
        layout.addWidget(self.stack, 1)
        return layout

    def _footer(self) -> QWidget:
        footer = QWidget()
        theme.set_role(footer, "bar")
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 10, 20, 10)
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
        self.revert_button = QPushButton(theme.icon("undo"), "Revert")
        self.revert_button.setToolTip("Drop the changes and read the file again")
        self.revert_button.clicked.connect(self.revert)
        layout.addWidget(self.revert_button)
        self.save_button = QPushButton(theme.icon("content-save", "white"), "Save and apply")
        theme.set_role(self.save_button, "primary", "variant")
        self.save_button.setToolTip("Write the file and reload the service (Ctrl+S)")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        return footer

    # -- showing --------------------------------------------------------------------------------------------------

    def select(self, index: int) -> None:
        self.selected = index
        self.strip_page.show_strip(index)
        self.show_page("strip")
        self.refresh()

    def show_page(self, name: str) -> None:
        self.nav_buttons[name].setChecked(True)
        self.nav_buttons["strip"].setText(f"Strip {self.selected + 1}")
        self.stack.setCurrentIndex(list(self.pages).index(name))

    def refresh(self) -> None:
        """Validates the configuration and shows the result everywhere."""
        self.validation = self.document.validate()
        self.preview.show_looks(looks(self.document, self.validation, self.audio), self.selected)
        for page in self.pages.values():
            page.show_problems(self.validation)
        self._show_problems(self.validation.problems)
        modified = self.document.modified
        state = "new file" if not self.document.exists else "changed" if modified else "saved"
        self.path_label.setText(f"{self.document.path}  ·  {state}")
        self.save_button.setEnabled(self.validation.config is not None and (modified or not self.document.exists))
        self.revert_button.setEnabled(modified)

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
        self.reload_pages()

    def reload_pages(self) -> None:
        for page in self.pages.values():
            page.reload()
        self.select(min(self.selected, protocol.STRIPS - 1))

    def toggle_theme(self) -> None:
        dark = theme.current_mode() == theme.ThemeMode.DARK
        theme.apply_theme(theme.ThemeMode.LIGHT if dark else theme.ThemeMode.DARK)
        # the icons are drawn in the text color of the theme
        for button in (self.theme_button, self.refresh_audio):
            button.setIcon(theme.icon("theme-light-dark" if button is self.theme_button else "refresh"))
        self.restart_button.setIcon(theme.icon("restart"))
        self.revert_button.setIcon(theme.icon("undo"))
        self.reload_pages()

    # -- editing --------------------------------------------------------------------------------------------------

    def edited(self) -> None:
        self.restart_button.hide()
        self.status.setText("")
        self.refresh()

    def _strips_changed(self, selected: int) -> None:
        self.edited()
        self.select(selected)

    def _moved(self, source: int, target: int) -> None:
        self.document.move_strip(source, target)
        self._strips_changed(target)

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
        try:
            state = self.service.state()
        except ServiceError as e:
            self.service_state = None
            self._pill("unavailable", "bad", str(e))
            self.service_button.hide()
            return
        self.service_state = state
        if not state.installed:
            tone, text, tip = "warn", "Install and start", "Write the systemd user unit, enable and start it"
        elif state.running:
            tone, text, tip = "good", "Restart", "Restart the daemon, e.g. after changing [device]"
        else:
            tone = "bad" if state.active == "failed" else "neutral"
            text, tip = "Start", "Enable the service and start it"
        self._pill(state.describe(), tone, f"systemctl --user status {UNIT_NAME}")
        self.service_button.setText(text)
        self.service_button.setToolTip(tip)
        self.service_button.show()

    def _pill(self, text: str, tone: str, tip: str) -> None:
        self.pill.setText(text)
        self.pill.setToolTip(tip)
        theme.set_role(self.pill, tone, "tone")

    def _service_action(self) -> None:
        state = self.service_state
        assert state is not None, "the button shows only with a known state"
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
            applied = apply(self.service, self.document.path, restart_sections)
        except ServiceError as e:
            self.status.setText(f"Saved, but reloading the service failed: {e}")
        else:
            self.status.setText(applied.message)
            self.restart_button.setVisible(applied.restart_needed)
        self.refresh()
        self.refresh_service()
        return True

    def revert(self) -> None:
        self.document.revert()
        self.reload_pages()
        self.status.setText("Reverted to the file.")

    def closeEvent(self, event: QCloseEvent | None) -> None:
        assert event is not None
        if not self.document.modified:
            event.accept()
            return
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
        else:
            event.accept()
