"""
The pages of the editor: the selected strip, the layout being edited, and the global settings: a section of options
(`[behavior]`, `[mqtt]`, `[device]`, ...) and the aliases.

Every page is built once. From then on it shows the document in place: `show_document()` with the `Change` the
`Editor` reports loads the values into the fields it has, and switches between parts it built before (e.g. the form of
another strip type), instead of building itself again (see the GUI section of docs/architecture.md).
"""

import asyncio
import html
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon import mumble, protocol
from xtouch_daemon.audio.model import AudioState, Direction
from xtouch_daemon.config import STRIP_TYPES, BehaviorConfig, Config, LayoutConfig, MqttConfig, default_encoder
from xtouch_daemon.gui.domain import docs, sources
from xtouch_daemon.gui.domain.broker import live_status, try_broker
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.document import SECTIONS, ConfigDocument, StripDraft, Validation
from xtouch_daemon.gui.domain.looks import look
from xtouch_daemon.gui.domain.schema import options, strip_models, strip_options, strip_type_help
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.domain.voip import install_hint, install_steps, voip_status
from xtouch_daemon.gui.qt import theme
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields import (
    LEARN_MORE,
    OptionRow,
    Suggest,
    completer,
    flat_button,
    help_html,
    help_label,
    help_text,
    label,
    show_status,
    suggestion_menu,
)
from xtouch_daemon.live import Snapshot

type Audio = Callable[[], AudioState]

TYPE_TITLES = {"homeassistant": "Home Assistant", "voip": "VoIP"}
PAGE_TITLES = {"mqtt": "Home Assistant", "switching": "Layouts", "voip": "Voice chat"}
"""The names of the global settings for people: the MQTT broker is how Home Assistant is reached."""
GLOBAL_PAGES = ("behavior", "aliases", "mqtt", "switching", "voip", "device")
"""The global settings, the ones changed most often first: `[device]` is set once, if ever."""
LAYOUT_TYPES = ("inherit",)
"""The strip types only the strips of a `[[layout]]` have."""


def page_title(name: str) -> str:
    return PAGE_TITLES.get(name, name.capitalize())


def type_title(strip_type: str) -> str:
    return TYPE_TITLES.get(strip_type, strip_type.capitalize())


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    theme.set_role(frame, "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(theme.Space.L, theme.Space.L, theme.Space.L, theme.Space.L)
    layout.setSpacing(theme.Space.S)
    return frame, layout


def row(layout: QLayout) -> QWidget:
    """A widget around a layout, to add it to a page like its other widgets."""
    layout.setContentsMargins(0, 0, 0, 0)
    holder = QWidget()
    holder.setLayout(layout)
    return holder


def button(icon: str, text: str, color: str | None = None, role: str = "") -> QPushButton:
    """A push button with an icon that follows the theme (see `theme.set_icon`), in a style role ("primary", ...)."""
    widget = QPushButton(text)
    theme.set_icon(widget, icon, color)
    if role:
        theme.set_role(widget, role, "variant")
    return widget


def set_text(widget: QLabel | QPushButton, text: str) -> None:
    """A new text, only if it is one: the same text again would still lay out the window again."""
    if widget.text() != text:
        widget.setText(text)


class Stack(QStackedWidget):
    """
    Parts of a page of which one shows at a time, e.g. the form of each strip type. It takes the size of the one that
    shows, not that of the largest, so a short part does not leave a gap under it.
    """

    def show_part(self, part: QWidget) -> None:
        if self.indexOf(part) < 0:
            self.addWidget(part)
        elif self.currentWidget() is part:
            return
        for index in range(self.count()):
            widget = self.widget(index)
            assert widget is not None
            shown = widget is part
            policy = QSizePolicy.Policy.Preferred if shown else QSizePolicy.Policy.Ignored
            widget.setSizePolicy(policy, policy)
        self.setCurrentWidget(part)
        self.updateGeometry()


class Page(QWidget):
    """A page of the editor. `show_document` shows the document again where `change` touches the page."""

    def __init__(self, editor: Editor, audio: Audio):
        super().__init__()
        self.editor = editor
        self.audio = audio
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(theme.Space.XS, theme.Space.XS, theme.Space.M, theme.Space.M)
        self.layout_.setSpacing(theme.Space.M)
        self.option_rows: list[OptionRow] = []
        self.problem = label("", "error", wrap=True)
        """Problems that belong to no row: of the whole section or strip, and unknown options."""
        self.problem.hide()

    @property
    def document(self) -> ConfigDocument:
        return self.editor.document

    @property
    def rows(self) -> list[OptionRow]:
        """The rows of the options the page shows."""
        return self.option_rows

    def show_document(self, change: Change) -> None:
        raise NotImplementedError

    def show_problems(self, validation: Validation) -> None:
        raise NotImplementedError

    def _row(
        self,
        option: Any,
        path: Callable[[str], tuple[str | int, ...]],
        suggest: Suggest | None = None,
        placeholder: Callable[[], str] | None = None,
        link: str | None = None,
        rows: list[OptionRow] | None = None,
    ) -> OptionRow:
        """
        A row for an option at `path(name)` (the path may depend on what the page shows, e.g. the strip), kept in
        `rows` (those of the page by default).
        """
        name = option.name

        def put(value: Any) -> None:
            if value is None:
                self.document.unset(path(name))
            else:
                self.document.set(path(name), value)

        option_row = OptionRow(option, lambda: self._value(path(name)), put, suggest, placeholder, link)
        option_row.edited.connect(lambda: self.editor.edited(Change(Scope.VALUE, path(name))))
        (self.option_rows if rows is None else rows).append(option_row)
        return option_row

    def _value(self, path: tuple[str | int, ...]) -> Any:
        return self.document.get(path)

    def _load_rows(self, rows: list[OptionRow]) -> None:
        for option_row in rows:
            option_row.load()

    def _show_rest(self, rest: list[str]) -> None:
        set_text(self.problem, "\n".join(rest))
        self.problem.setVisible(bool(rest))


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
        self.parts = Stack()
        self.absent, layout = card()
        layout.addWidget(label(f"There is no [{name}] section in the file.", wrap=True))
        add = button("plus", f"Add [{name}]", "white", "primary")
        add.clicked.connect(lambda: self.editor.add_section(name))
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addStretch()
        layout.addWidget(row(buttons))
        self.present = QWidget()
        present = QVBoxLayout(self.present)
        present.setContentsMargins(0, 0, 0, 0)
        present.setSpacing(theme.Space.M)
        self._above_options(present)
        frame, layout = card()
        suggest: dict[str, Suggest] = {"ignore": lambda: sources.patterns(self.audio())}
        for option in options(self.section.model):
            layout.addWidget(
                self._row(
                    option,
                    lambda option_name: (name, option_name),
                    suggest.get(option.name),
                    link=docs.option_link(name, option.name),
                )
            )
        if name == "device":
            layout.addWidget(label("A changed name takes a restart of the service.", "help"))
        present.addWidget(frame)
        self.layout_.addWidget(self.parts)
        self.layout_.addStretch()
        self._show()

    def _above_options(self, layout: QVBoxLayout) -> None:
        """What a page shows above the options of its section while the file has it: nothing here."""

    def _value(self, path: tuple[str | int, ...]) -> Any:
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
        set_text(self.box.live_detail, help_text(status.tip))

    def test(self) -> None:
        """Tries the settings in the editor (see `try_broker`)."""
        try:
            config = MqttConfig.model_validate(self.document.data().get("mqtt") or {})
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

    def __init__(self, document: ConfigDocument, audio: Audio, on_edit: Callable[[], None], installer: MumbleInstaller):
        self.installer = installer
        self.snapshot: Snapshot | None = None
        self.result: Status | None = None
        self.installing = False
        self.box: MumbleBox | None = None
        installer.finished.connect(self._installed)
        super().__init__("voip", document, audio, on_edit)

    def reload(self) -> None:
        super().reload()
        self.box = MumbleBox()
        self.box.install_button.clicked.connect(self.install)
        # below the help of the section, above its options
        self.layout_.insertWidget(3, self.box)
        self.show_live(self.snapshot)

    def show_live(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot
        assert self.box is not None, "reload() makes it"
        self.box.show_state(voip_status(snapshot), self.installer.setup(), self.result, self.installing)

    def install(self) -> None:
        self.installing = True
        self.result = Status("Preparing the plugin…", Tone.NEUTRAL)
        self.show_live(self.snapshot)
        self.installer.start()

    def _installed(self, status: Status) -> None:
        self.installing = False
        self.result = status
        self.show_live(self.snapshot)


class MumbleBox(QFrame):
    """The voice chat of the daemon, and the steps to set up the Mumble plugin with its install button."""

    def __init__(self) -> None:
        super().__init__()
        theme.set_role(self, "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.Space.L, theme.Space.L, theme.Space.L, theme.Space.L)
        layout.setSpacing(theme.Space.S)
        line = QHBoxLayout()
        line.addWidget(label("Mumble", "hint"))
        self.live_pill = label("", "pill")
        line.addWidget(self.live_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        line.addStretch()
        self.install_button = QPushButton(theme.icon("download"), "Install Mumble plugin")
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
        self.live_detail.setText(help_text(live.tip))
        self.install_button.setEnabled(setup.installable and not installing)
        self.install_button.setToolTip(install_hint(setup))
        steps = "".join(f"<li>{html.escape(step)}</li>" for step in install_steps(setup))
        link = f' <a href="{html.escape(docs.guide_link("mumble"))}">{LEARN_MORE}</a>'
        self.steps.setText(f"Set up the plugin once:<ol>{steps}</ol>{install_hint(setup)}{link}")
        self.result.setVisible(result is not None)
        if result is not None:
            self.result.setText(result.text)
            theme.set_role(self.result, "error" if result.tone == Tone.BAD else "")


class ConnectionBox(QFrame):
    """How the daemon's connection to the broker is doing, and the test of the settings."""

    def __init__(self) -> None:
        super().__init__()
        theme.set_role(self, "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.Space.L, theme.Space.L, theme.Space.L, theme.Space.L)
        layout.setSpacing(theme.Space.S)
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
            theme.set_role(self.test_result, {Tone.GOOD: "", Tone.BAD: "error"}.get(status.tone, "hint"))
            self.test_hint.setText(help_text(status.tip))


class StripPage(Page):
    """
    The strip selected in the preview: its type and its options, or how to configure it. It has a form for each strip
    type, built the first time a strip of that type is shown; selecting another strip loads its values into the form
    of its type (`show_strip`).
    """

    def __init__(self, editor: Editor, audio: Audio, show_page: Callable[[str], None]):
        super().__init__(editor, audio)
        self.show_page = show_page
        """Shows one of the global settings, e.g. the Home Assistant connection a `homeassistant` strip uses."""
        self.index = editor.selection
        header = QHBoxLayout()
        self.title = label("", "section")
        header.addWidget(self.title)
        header.addStretch()
        self.moves: list[tuple[QWidget, int]] = []
        for icon, tip, step in (
            ("chevron-left", "Move it to the left", -1),
            ("chevron-right", "Move it to the right", 1),
        ):
            move = flat_button(icon, f"{tip} (or drag it in the preview)")
            move.clicked.connect(lambda _=False, step=step: self.editor.move_strip(self.index, self.index + step))
            header.addWidget(move)
            self.moves.append((move, step))
        self.remove_button = button("delete-outline", "Remove", "error", "danger")
        self.remove_button.setToolTip("Remove the strip: the strips right of it move left, free places are auto strips")
        self.remove_button.clicked.connect(lambda: self.editor.remove_strip(self.index))
        header.addWidget(self.remove_button)
        self.layout_.addWidget(row(header))
        self.hint = label("", "hint")
        self.layout_.addWidget(self.hint)
        self.parts = Stack()
        self.unconfigured, layout = card()
        self.unconfigured_text = label("", wrap=True)
        layout.addWidget(self.unconfigured_text)
        self.configure_button = button("plus", "", "white", "primary")
        self.configure_button.clicked.connect(lambda: self.editor.configure_up_to(self.index))
        buttons = QHBoxLayout()
        buttons.addWidget(self.configure_button)
        buttons.addStretch()
        layout.addWidget(row(buttons))
        self.forms: dict[str | None, StripForm] = {}
        """The form of each strip type shown so far (None: a strip without a known type)."""
        self.layout_.addWidget(self.parts)
        self.layout_.addStretch()
        self._show()

    @property
    def configured(self) -> bool:
        return self.index < len(self.document.strips)

    @property
    def rows(self) -> list[OptionRow]:
        form = self.form
        return [] if form is None else form.rows

    @property
    def types(self) -> QButtonGroup:
        """The buttons of the strip types in the form shown."""
        assert self.form is not None
        return self.form.types

    @property
    def form(self) -> StripForm | None:
        """The form of the strip shown, None while it is not configured."""
        return self.forms.get(self.document.strips[self.index].type) if self.configured else None

    def show_strip(self, index: int) -> None:
        self.index = index
        self._show()
        self.show_problems(self.editor.validation)

    def show_document(self, change: Change) -> None:
        if change.strips:
            self._show()
        elif self.form is not None:
            # e.g. the connection to Home Assistant, a global setting
            self.form.show_globals()

    def _show(self) -> None:
        index = self.index
        set_text(self.title, f"Strip {index + 1}")
        set_text(self.hint, f"These options apply to strip {index + 1} alone.")
        for move, step in self.moves:
            move.setVisible(self.configured)
            move.setEnabled(0 <= index + step < len(self.document.strips))
        self.remove_button.setVisible(self.configured)
        if not self.configured:
            set_text(
                self.unconfigured_text,
                f"Strip {index + 1} is not configured, so it is an <b>auto</b> strip: it takes the next application "
                "that plays and has no strip of its own.",
            )
            set_text(self.configure_button, f"Configure strip {index + 1}")
            self.parts.show_part(self.unconfigured)
            return
        strip = self.document.strips[index]
        form = self.forms.get(strip.type)
        if form is None:
            form = self.forms[strip.type] = StripForm(self, strip.type)
        form.show_strip(strip)
        self.parts.show_part(form)

    def _behavior_max_volume(self) -> object:
        value = self.document.get(("behavior", "max_volume"))
        return BehaviorConfig().max_volume if value is None else value

    def _default_label(self) -> str:
        values = dict(self.document.strips[self.index].values)
        values.pop("label", None)
        return look(values, self.audio(), dict(self.document.aliases))[1]

    def show_problems(self, validation: Validation) -> None:
        form = self.form
        if form is None:
            return
        names = {option_row.option.name for option_row in form.rows}
        form.show_rest(
            [
                problem.message if len(problem.path) == 2 else str(problem)
                for problem in validation.at("strip", self.index)
                if len(problem.path) == 2 or problem.path[2] not in names
            ]
        )
        for option_row in form.rows:
            option_row.show_problems(validation.at("strip", self.index, option_row.option.name))


class StripForm(QWidget):
    """The type of a strip and the options of that type, for whichever strip of the type the page shows."""

    def __init__(self, page: StripPage, strip_type: str | None):
        super().__init__()
        self.page = page
        self.strip_type = strip_type
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.Space.M)
        types = QHBoxLayout()
        types.setSpacing(0)
        self.types = QButtonGroup(self)
        self.type_buttons: dict[str, QPushButton] = {}
        for name in STRIP_TYPES:
            segment = QPushButton(type_title(name))
            theme.set_role(segment, "segment", "variant")
            segment.setCheckable(True)
            segment.setChecked(name == strip_type)
            segment.setToolTip(help_text(strip_type_help(name)))
            segment.clicked.connect(lambda _=False, name=name: page.editor.set_strip_type(page.index, name))
            self.types.addButton(segment)
            self.type_buttons[name] = segment
            types.addWidget(segment)
        types.addStretch()
        layout.addWidget(row(types))
        models = strip_models()
        if strip_type in models:
            layout.addWidget(help_label(strip_type_help(strip_type), "hint", docs.strip_type_link(strip_type)))
        self.kept = help_label("", "help")
        layout.addWidget(self.kept)
        self.problem = label("", "error", wrap=True)
        self.problem.hide()
        layout.addWidget(self.problem)
        self.rows: list[OptionRow] = []
        self.connection: QLabel | None = None
        if strip_type is None or strip_type not in models:
            return
        if strip_type == "homeassistant":
            layout.addWidget(self._connection())
        frame, options_layout = card()
        suggest: dict[str, Suggest] = {"match": lambda: sources.patterns(page.audio())}
        placeholders: dict[str, Callable[[], str]] = {
            "label": page._default_label,
            "min_volume": lambda: "0",
            "max_volume": lambda: f"{page._behavior_max_volume()} (behavior)",
            "encoder": lambda: default_encoder(strip_type),
        }
        if strip_type in ("output", "input"):
            direction = Direction(strip_type)
            suggest["device"] = lambda: sources.devices(page.audio(), direction)
            suggest["profiles"] = lambda: sources.profiles(page.audio(), direction)
            placeholders["device"] = lambda: f"none: the default {strip_type}"
        if strip_type == "homeassistant":
            placeholders["id"] = lambda: f"strip_{page.index + 1}"
        for option in strip_options(strip_type):
            option_row = page._row(
                option,
                lambda name: ("strip", page.index, name),
                suggest.get(option.name),
                placeholders.get(option.name),
                docs.option_link("strip", option.name, strip_type),
                self.rows,
            )
            if option.name == "device":
                # the label shown by default follows the device
                option_row.edited.connect(self._device_edited)
            options_layout.addWidget(option_row)
        if not self.rows:
            text = "An empty strip has no options." if strip_type == "empty" else "The strip has no options."
            options_layout.addWidget(label(text, "hint"))
        layout.addWidget(frame)

    def _device_edited(self) -> None:
        for option_row in self.rows:
            if option_row.option.name == "label":
                option_row.load()

    def _connection(self) -> QFrame:
        """Where the connection to Home Assistant is: a global setting, shared by every `homeassistant` strip."""
        frame, layout = card()
        line = QHBoxLayout()
        self.connection = label("", wrap=True)
        line.addWidget(self.connection, 1)
        self.connection_button = button("cog-outline", "")
        self.connection_button.clicked.connect(lambda: self.page.show_page("mqtt"))
        line.addWidget(self.connection_button)
        layout.addWidget(row(line))
        return frame

    def show_strip(self, strip: StripDraft) -> None:
        """Shows `strip`, a strip of the type of the form."""
        layout = self.page.document.layout
        for name, segment in self.type_buttons.items():
            # the types only layouts have, for the strips of a layout (or for a strip that has one anyway)
            segment.setVisible(not (name in LAYOUT_TYPES and layout is None and name != strip.type))
        if strip.type in self.type_buttons:
            self.type_buttons[strip.type].setChecked(True)
        notes = self._kept(strip)
        set_text(self.kept, "<br>".join(help_html(note) for note in notes))
        self.kept.setVisible(bool(notes))
        self.page._load_rows(self.rows)
        self.show_globals()

    def show_globals(self) -> None:
        """What the strip takes from the global settings: the connection to Home Assistant."""
        if self.connection is None:
            return
        document = self.page.document
        if document.has_section("mqtt"):
            host = document.get(("mqtt", "host"))
            text = f"Connects to Home Assistant through the MQTT broker {host or '(no host yet)'}, like every "
            text += "Home Assistant strip."
            title, icon, color, role = "Connection settings", "cog-outline", None, ""
        else:
            text = "Home Assistant strips need the connection to the MQTT broker of Home Assistant, a global setting."
            title, icon, color, role = "Set up the connection", "plus", "white", "primary"
        set_text(self.connection, text)
        set_text(self.connection_button, title)
        theme.set_icon(self.connection_button, icon, color)
        theme.set_role(self.connection_button, role, "variant")

    def show_rest(self, rest: list[str]) -> None:
        set_text(self.problem, "\n".join(rest))
        self.problem.setVisible(bool(rest))

    @staticmethod
    def _kept(strip: StripDraft) -> list[str]:
        """What the strip keeps of the types it had before (see `StripDraft.kept`), and how to get it back."""
        lines = [
            f"Kept from {type_title(kind)}: {', '.join(f'`{name}`' for name in values)}. Switching back to "
            f"{type_title(kind)} restores them."
            for kind, values in strip.kept.items()
            if values
        ]
        lines += [
            f"The options kept from {type_title(kind)} are no longer readable (the comment in the file was changed "
            "by hand). They stay in the file as they are."
            for kind in strip.unreadable
        ]
        return lines


class LayoutPage(Page):
    """The options of the layout being edited (`[[layout]]`: its name, label and rules), or what the default one is."""

    def __init__(self, editor: Editor, audio: Audio):
        super().__init__(editor, audio)
        header = QHBoxLayout()
        self.title = label("", "section")
        header.addWidget(self.title)
        self.table = label("", "hint")
        header.addWidget(self.table)
        header.addStretch()
        self.moves: list[tuple[QWidget, int]] = []
        for icon, tip, step in (
            ("chevron-left", "Move it to the left: earlier in the order of --next", -1),
            ("chevron-right", "Move it to the right: later in the order of --next", 1),
        ):
            move = flat_button(icon, tip)
            move.clicked.connect(lambda _=False, step=step: self._move(step))
            header.addWidget(move)
            self.moves.append((move, step))
        self.remove_button = button("delete-outline", "Remove layout", "error", "danger")
        self.remove_button.clicked.connect(self.editor.remove_layout)
        header.addWidget(self.remove_button)
        self.layout_.addWidget(row(header))
        about = " ".join((LayoutConfig.__doc__ or "").split())
        self.layout_.addWidget(help_label(about, "hint", docs.page_link("layout")))
        self.layout_.addWidget(self.problem)
        self.parts = Stack()
        self.default, layout = card()
        layout.addWidget(
            label(
                "The default layout: the strips at the top level of the file. The device shows it unless a rule "
                "of another layout matches or another one is chosen. Add layouts with + next to the layouts.",
                wrap=True,
            )
        )
        self.other, layout = card()
        suggest: dict[str, Suggest] = {"apps": lambda: sources.patterns(self.audio())}
        for option in options(LayoutConfig, skip=("strips",)):
            layout.addWidget(
                self._row(
                    option,
                    lambda name: ("layout", name),
                    suggest.get(option.name),
                    link=docs.option_link("layout", option.name),
                )
            )
        self.layout_.addWidget(self.parts)
        self.layout_.addStretch()
        self._show()

    def show_document(self, change: Change) -> None:
        if change.touches(Scope.LAYOUTS):
            self._show()
        elif change.scope is Scope.VALUE and change.path[:2] == ("layout", "name"):
            set_text(self.title, f"Layout {self.document.layout_name}")

    def _show(self) -> None:
        index = self.document.layout
        set_text(self.title, f"Layout {self.document.layout_name}")
        set_text(self.table, "[[layout]]" if index is not None else "[[strip]]")
        for move, step in self.moves:
            move.setVisible(index is not None)
            move.setEnabled(index is not None and 0 <= index + step < len(self.document.layouts))
        self.remove_button.setVisible(index is not None)
        self.parts.show_part(self.default if index is None else self.other)
        self._load_rows(self.rows)

    @property
    def rows(self) -> list[OptionRow]:
        # the default layout has no options
        return [] if self.document.layout is None else self.option_rows

    def _value(self, path: tuple[str | int, ...]) -> Any:
        # the rows are there also while the default layout, which has no options, is edited
        return None if self.document.layout is None else self.document.get(path)

    def _move(self, step: int) -> None:
        assert self.document.layout is not None
        self.editor.move_layout(self.document.layout + step)

    def show_problems(self, validation: Validation) -> None:
        names = {option_row.option.name for option_row in self.rows}
        self._show_rest(
            [
                str(problem)
                for problem in validation.at("layout")
                if len(problem.path) == 1 or problem.path[1] not in names
            ]
        )
        for option_row in self.rows:
            option_row.show_problems(validation.at("layout", option_row.option.name))


class AliasesPage(Page):
    """The names `auto` strips show for applications: a row each, added and removed in place."""

    def __init__(self, editor: Editor, audio: Audio):
        super().__init__(editor, audio)
        self.edits: list[tuple[QLineEdit, QLineEdit]] = []
        self.lines: list[QWidget] = []
        header = QHBoxLayout()
        header.addWidget(label(page_title("aliases"), "section"))
        header.addWidget(label("[aliases]", "hint"))
        header.addStretch()
        self.layout_.addWidget(row(header))
        description = Config.model_fields["aliases"].description or ""
        self.layout_.addWidget(help_label(description, "hint", docs.page_link("aliases")))
        frame, layout = card()
        heading = QHBoxLayout()
        heading.addWidget(label("Application, as the sound server reports it", "help"), 3)
        heading.addWidget(label(f"Label (up to {protocol.LCD_CELL_WIDTH} characters)", "help"), 2)
        heading.addSpacing(64)
        layout.addWidget(row(heading))
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(4)
        layout.addWidget(row(self.rows_layout))
        layout.addWidget(self.problem)
        add = button("plus", "Add alias")
        add.clicked.connect(self._add)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addStretch()
        layout.addWidget(row(buttons))
        self.layout_.addWidget(frame)
        self.layout_.addStretch()
        self._show()

    def show_document(self, change: Change) -> None:
        if change.touches(Scope.ALIASES):
            self._show()

    def _show(self) -> None:
        """As many rows as aliases, with their texts."""
        aliases = self.document.aliases
        while len(self.edits) > len(aliases):
            self._drop(len(self.edits) - 1)
        while len(self.edits) < len(aliases):
            self._line()
        for (name_edit, alias_edit), (name, alias) in zip(self.edits, aliases, strict=True):
            for edit, text in ((name_edit, name), (alias_edit, alias)):
                if edit.text() != text:
                    edit.setText(text)

    def _line(self) -> QLineEdit:
        line = QHBoxLayout()
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("e.g. WEBRTC VoiceEngine")
        alias_edit = QLineEdit()
        alias_edit.setMaxLength(protocol.LCD_CELL_WIDTH)
        alias_edit.setPlaceholderText("e.g. Discord")
        for edit in (name_edit, alias_edit):
            edit.textEdited.connect(self._edited)

        def pick(value: str) -> None:
            name_edit.setText(value)
            self._edited()

        def applications() -> tuple[sources.Suggestion, ...]:
            return sources.applications(self.audio())

        completer(name_edit, applications).activated.connect(pick)
        line.addWidget(name_edit, 3)
        line.addWidget(suggestion_menu(self, applications, pick, "No application plays right now"))
        line.addWidget(alias_edit, 2)
        pair = (name_edit, alias_edit)
        remove = flat_button("close", "Remove the alias")
        remove.clicked.connect(lambda: self._remove(pair))
        line.addWidget(remove)
        self.edits.append(pair)
        holder = row(line)
        self.lines.append(holder)
        self.rows_layout.addWidget(holder)
        return name_edit

    def _drop(self, index: int) -> None:
        del self.edits[index]
        holder = self.lines.pop(index)
        holder.hide()
        holder.deleteLater()

    def _edited(self) -> None:
        self.document.aliases = [(name.text(), alias.text()) for name, alias in self.edits]
        self.editor.edited(Change(Scope.VALUE, ("aliases",)))

    def _add(self) -> None:
        self._line().setFocus()
        self._edited()

    def _remove(self, pair: tuple[QLineEdit, QLineEdit]) -> None:
        self._drop(self.edits.index(pair))
        self._edited()

    def show_problems(self, validation: Validation) -> None:
        for name, alias in self.edits:
            problems = validation.at("aliases", name.text())
            theme.set_role(name, any(problem.kind in ("missing", "duplicate") for problem in problems), "problem")
            theme.set_role(alias, any(problem.kind not in ("missing", "duplicate") for problem in problems), "problem")
        self._show_rest([f"{problem.path[-1]!r}: {problem.message}" for problem in validation.at("aliases")])
