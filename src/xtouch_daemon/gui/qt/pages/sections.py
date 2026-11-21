"""
The pages of the sections with options of their own (`[behavior]`, `[device]`, `[switching]`, ...), and the extras
of three of them: testing the broker on `[mqtt]` and the API on `[homeassistant]`, installing the Mumble plugin on
`[voip]`.
"""

import asyncio
import html
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.config.sections import HomeAssistantConfig, MqttConfig
from xtouch_daemon.gui.domain import docs, entities, sources
from xtouch_daemon.gui.domain.broker import live_status, try_broker
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.schema import SECTIONS, options
from xtouch_daemon.gui.domain.slots_document import OptionPath, Validation
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.domain.voip import install_hint, install_steps, voip_status
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import Suggest, help_label, help_tail, label, set_help, show_status
from xtouch_daemon.gui.qt.fields.entities import EntitySource
from xtouch_daemon.gui.qt.fields.option_row import add_rows, align_titles
from xtouch_daemon.gui.qt.pages.base import Audio, Page, Stack, button, card, page_title, row, set_text
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.live.messages import Snapshot
from xtouch_daemon.voip import mumble


class SectionPage(Page):
    """A section with options of its own, like `[behavior]`; an optional one (`[mqtt]`) can be added and removed."""

    def __init__(self, section: str, editor: Editor, audio: Audio):
        super().__init__(editor, audio)
        self.section = SECTIONS[section]
        name = self.section.name
        header = QHBoxLayout()
        header.addWidget(label(page_title(name), "section"))
        header.addWidget(label(f"[{name}]", "hint"))
        header.addStretch()
        self.remove_button = button("delete-outline", f"Remove [{name}]", "error", "danger")
        self.remove_button.clicked.connect(lambda: self.editor.remove_section(name))
        header.addWidget(self.remove_button)
        self.layout_.addWidget(row(header))
        self.layout_.addWidget(help_label(self.section.help, "hint", docs.page_link(name)))
        self.layout_.addWidget(self.problem)
        self._above_parts(self.layout_)
        self.parts = Stack()
        self.absent, layout = card()
        layout.addWidget(label(self._absent_text(), wrap=True))
        add = button("plus", f"Add [{name}]", "white", "primary")
        add.clicked.connect(lambda: self.editor.add_section(name))
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addStretch()
        layout.addWidget(row(buttons))
        self.present = QWidget()
        present = QVBoxLayout(self.present)
        present.setContentsMargins(0, 0, 0, 0)
        present.setSpacing(Space.M)
        self._above_options(present)
        frame, layout = card()
        suggest: dict[str, Suggest] = {"ignore": lambda: sources.patterns(self.audio())}
        add_rows(
            layout,
            [
                self._row(
                    option,
                    lambda option_name: (name, option_name),
                    suggest.get(option.name),
                    link=docs.option_link(name, option.name),
                )
                for option in options(self.section.model)
            ],
        )
        align_titles(self.option_rows)
        if name == "device":
            layout.addWidget(label("A changed name takes a restart of the service.", "help"))
        present.addWidget(frame)
        self.parts.add(self.absent)
        self.parts.add(self.present)
        self.layout_.addWidget(self.parts)
        self.layout_.addStretch()
        self._show()

    def _above_parts(self, layout: QVBoxLayout) -> None:
        """What a page shows below the help of its section, whether the file has it or not: nothing here."""

    def _above_options(self, layout: QVBoxLayout) -> None:
        """What a page shows above the options of its section while the file has it: nothing here."""

    def _absent_text(self) -> str:
        """What the page says while the file has no such section."""
        return f"There is no [{self.section.name}] section in the file."

    def _value(self, path: OptionPath) -> Any:
        # the rows are there also while the file has no such section
        return self.document.get(path) if self.document.has_section(self.section.name) else None

    def show_document(self, change: Change) -> None:
        if change.touches(Scope.SECTION):
            self._show()

    def _show(self) -> None:
        present = self.document.has_section(self.section.name)
        self.remove_button.setVisible(self.section.optional and present)
        self.parts.show_part(self.present if present else self.absent)
        self._load_rows(self.rows)

    def show_problems(self, validation: Validation) -> None:
        names = {option_row.option.name for option_row in self.rows}
        self._show_rest(
            [
                problem.message if len(problem.path) == 1 else str(problem)
                for problem in validation.at(self.section.name)
                if len(problem.path) == 1 or problem.path[1] not in names
            ]
        )
        for option_row in self.rows:
            option_row.show_problems(validation.at(self.section.name, option_row.option.name))


type BrokerTest = Callable[[MqttConfig], Awaitable[Status]]


class BrokerTester(QObject):
    """Tries settings of the [mqtt] section in a thread, so a broker that does not answer does not block the window."""

    finished = pyqtSignal(object, arguments=["status"])

    def __init__(self, test: BrokerTest = try_broker):
        super().__init__()
        self._test = test

    def start(self, config: MqttConfig) -> None:
        threading.Thread(target=self._run, args=(config,), name="broker test", daemon=True).start()

    def _run(self, config: MqttConfig) -> None:
        self.finished.emit(asyncio.run(self._test(config)))


class MqttPage(SectionPage):
    """
    The [mqtt] section, with how the daemon's connection to Home Assistant is doing and a test of the settings as
    they are in the editor, before they are saved.
    """

    def __init__(self, editor: Editor, audio: Audio, tester: BrokerTester):
        self.tester = tester
        self.tested: Status | None = None
        self.testing = False
        tester.finished.connect(self._tested)
        super().__init__("mqtt", editor, audio)
        self.show_live(None)

    def _above_options(self, layout: QVBoxLayout) -> None:
        self.box = ConnectionBox()
        """The connection and its test, below the help of the section, above its options."""
        self.box.test_button.clicked.connect(self.test)
        layout.addWidget(self.box)

    def show_live(self, snapshot: Snapshot | None) -> None:
        """How the daemon's connection is doing now (see `live_status`)."""
        status = live_status(snapshot)
        show_status(self.box.live_pill, status)
        set_help(self.box.live_detail, status.tip)

    def test(self) -> None:
        """Tries the settings in the editor (see `try_broker`)."""
        try:
            config = MqttConfig.model_validate(self.document.get(("mqtt",)) or {})
        except ValidationError:
            self.tested = Status("Fix the problems of the settings first.", Tone.BAD)
            self._show_test()
            return
        self.testing = True
        self.tested = Status(f"Connecting to {config.host}:{config.port}…", Tone.NEUTRAL)
        self._show_test()
        self.tester.start(config)

    def _tested(self, status: Status) -> None:
        self.testing = False
        # a result that comes after the section was removed has nowhere to go
        self.tested = status if self.document.has_section("mqtt") else None
        self._show_test()

    def _show(self) -> None:
        super()._show()
        if not self.document.has_section("mqtt"):
            # a test of settings that are gone says nothing
            self.tested = None
            self._show_test()

    def _show_test(self) -> None:
        self.box.show_test(self.tested, self.testing)


class HomeAssistantPage(SectionPage):
    """
    The [homeassistant] section, with how the daemon's connection to the API is doing and a test of the settings as
    they are in the editor, before they are saved. The entities a test finds are the suggestions of the fields.
    """

    def __init__(self, editor: Editor, audio: Audio, source: EntitySource):
        self.source = source
        self.tested: Status | None = None
        self.testing = False
        source.tested.connect(self._tested)
        super().__init__("homeassistant", editor, audio)
        self.show_live(None)

    def _above_options(self, layout: QVBoxLayout) -> None:
        self.box = ConnectionBox()
        """The connection and its test, below the help of the section, above its options."""
        self.box.test_button.setToolTip(
            "Connect once with the settings below, also unsaved ones, read the entities, and disconnect again"
        )
        self.box.test_button.clicked.connect(self.test)
        layout.addWidget(self.box)

    def show_live(self, snapshot: Snapshot | None) -> None:
        """How the daemon's connection is doing now (see `entities.live_status`)."""
        status = entities.live_status(snapshot)
        show_status(self.box.live_pill, status)
        set_help(self.box.live_detail, status.tip)

    def test(self) -> None:
        """Tries the settings in the editor (see `entities.try_home_assistant`)."""
        try:
            config = HomeAssistantConfig.model_validate(self.document.get(("homeassistant",)) or {})
        except ValidationError:
            self.tested = Status("Fix the problems of the settings first.", Tone.BAD)
            self._show_test()
            return
        self.testing = True
        self.tested = Status(f"Connecting to {config.url}…", Tone.NEUTRAL)
        self._show_test()
        self.source.test(config)

    def _tested(self, status: Status) -> None:
        self.testing = False
        # a result that comes after the section was removed has nowhere to go
        self.tested = status if self.document.has_section("homeassistant") else None
        self._show_test()

    def _show(self) -> None:
        super()._show()
        if not self.document.has_section("homeassistant"):
            self.tested = None
            self._show_test()

    def _show_test(self) -> None:
        self.box.show_test(self.tested, self.testing)


type MumbleInstall = Callable[[], str]


class MumbleInstaller(QObject):
    """
    Builds the Mumble plugin if needed and hands it to Mumble (`mumble.install()`) in a thread: a build takes a few
    seconds. `finished` tells what happens next, or what went wrong.
    """

    finished = pyqtSignal(object, arguments=["status"])

    def __init__(self, install: MumbleInstall = mumble.install, setup: Callable[[], mumble.Setup] = mumble.setup):
        super().__init__()
        self._install = install
        self.setup = setup

    def start(self) -> None:
        threading.Thread(target=self._run, name="mumble plugin", daemon=True).start()

    def _run(self) -> None:
        try:
            status = Status(self._install(), Tone.GOOD)
        except mumble.MumbleError as e:
            status = Status(str(e), Tone.BAD)
        self.finished.emit(status)


class VoipPage(SectionPage):
    """The [voip] section, with whether the daemon has a voice chat and the setup of the Mumble plugin."""

    def __init__(self, editor: Editor, audio: Audio, installer: MumbleInstaller):
        self.installer = installer
        self.setup = installer.setup()
        """
        The setup of the plugin: looked up when the page shows and after an install, not with every snapshot of the
        daemon (60 a second), as it searches the disk.
        """
        self.snapshot: Snapshot | None = None
        self.result: Status | None = None
        self.installing = False
        installer.finished.connect(self._installed)
        super().__init__("voip", editor, audio)
        self.show_live(None)

    def _above_parts(self, layout: QVBoxLayout) -> None:
        # voip strips work without the section (see `Config._voip_strips`), so the plugin shows without it too
        self.box = MumbleBox()
        """The voice chat and the setup of the plugin, below the help of the section, above its options."""
        self.box.install_button.clicked.connect(self.install)
        layout.addWidget(self.box)

    def _absent_text(self) -> str:
        return (
            "There is no [voip] section in the file, so voip strips use its defaults: the participants come from the "
            "Mumble plugin. Add it to change that."
        )

    def show_live(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot
        self.box.show_state(voip_status(snapshot), self.setup, self.result, self.installing)

    def showEvent(self, event: QShowEvent | None) -> None:
        # Mumble or the plugin may have come or gone while the page was hidden
        self.setup = self.installer.setup()
        self.show_live(self.snapshot)
        super().showEvent(event)

    def install(self) -> None:
        self.installing = True
        self.result = Status("Preparing the plugin…", Tone.NEUTRAL)
        self.show_live(self.snapshot)
        self.installer.start()

    def _installed(self, status: Status) -> None:
        self.installing = False
        self.result = status
        self.setup = self.installer.setup()
        self.show_live(self.snapshot)


class MumbleBox(QFrame):
    """The voice chat of the daemon, and the steps to set up the Mumble plugin with its install button."""

    def __init__(self) -> None:
        super().__init__()
        set_role(self, "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Space.L, Space.L, Space.L, Space.L)
        layout.setSpacing(Space.S)
        line = QHBoxLayout()
        line.addWidget(label("Mumble", "hint"))
        self.live_pill = label("", "pill")
        line.addWidget(self.live_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        line.addStretch()
        self.install_button = button("download", "Install Mumble plugin")
        line.addWidget(self.install_button)
        layout.addWidget(row(line))
        self.live_detail = help_label("", "hint")
        layout.addWidget(self.live_detail)
        self.steps = help_label("", "", docs.guide_link("mumble"))
        layout.addWidget(self.steps)
        self.result = label("", wrap=True)
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.result)

    def show_state(self, live: Status, setup: mumble.Setup, result: Status | None, installing: bool) -> None:
        show_status(self.live_pill, live)
        set_help(self.live_detail, live.tip)
        self.install_button.setEnabled(setup.installable and not installing)
        self.install_button.setToolTip(install_hint(setup))
        steps = "".join(f"<li>{html.escape(step)}</li>" for step in install_steps(setup))
        link = f"&emsp;{help_tail(link=docs.guide_link('mumble'))}"
        set_text(self.steps, f"Set up the plugin once:<ol>{steps}</ol>{install_hint(setup)}{link}")
        self.result.setVisible(result is not None)
        if result is not None:
            set_text(self.result, result.text)
            set_role(self.result, "error" if result.tone == Tone.BAD else "")


class ConnectionBox(QFrame):
    """How the daemon's connection to the broker is doing, and the test of the settings."""

    def __init__(self) -> None:
        super().__init__()
        set_role(self, "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Space.L, Space.L, Space.L, Space.L)
        layout.setSpacing(Space.S)
        line = QHBoxLayout()
        line.addWidget(label("The daemon", "hint"))
        self.live_pill = label("", "pill")
        line.addWidget(self.live_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        line.addStretch()
        self.test_button = button("lan-connect", "Test connection")
        self.test_button.setToolTip("Connect once with the settings below, also unsaved ones, and disconnect again")
        line.addWidget(self.test_button)
        layout.addWidget(row(line))
        self.live_detail = help_label("", "hint")
        layout.addWidget(self.live_detail)
        self.test_result = label("", wrap=True)
        layout.addWidget(self.test_result)
        self.test_hint = help_label("", "hint")
        layout.addWidget(self.test_hint)

    def show_test(self, status: Status | None, testing: bool) -> None:
        self.test_button.setEnabled(not testing)
        self.test_result.setVisible(status is not None)
        self.test_hint.setVisible(status is not None and bool(status.tip))
        if status is not None:
            self.test_result.setText(status.text)
            set_role(self.test_result, {Tone.GOOD: "", Tone.BAD: "error"}.get(status.tone, "hint"))
            set_help(self.test_hint, status.tip)
