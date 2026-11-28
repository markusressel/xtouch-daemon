"""
The page Settings for QML: a navigation of the sections with options of their own (`[behavior]`, `[device]`,
`[mqtt]`, `[voip]`, ...) and the aliases. Each section is a `SectionBackend` with the `Form` of its options, whether
the file has it (an optional one can be added and removed), and for `[mqtt]` and `[homeassistant]` how the daemon's
connection is doing and a test of the settings before they are saved; `[voip]` shows the plugin of each voice chat
client with its install. The aliases page edits a list of its own.
"""

import html
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon.config.model import Config
from xtouch_daemon.config.sections import HomeAssistantConfig, MqttConfig
from xtouch_daemon.gui.domain import docs, entities, sources
from xtouch_daemon.gui.domain.broker import live_status
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.schema import SECTIONS, Section, options
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.gui.domain.tokens import THEMES, ThemeMode
from xtouch_daemon.gui.domain.voip import client_status, connected_here, install_hint, install_steps
from xtouch_daemon.gui.quick.forms.context import FormContext, forms_of
from xtouch_daemon.gui.quick.forms.form import Form, RowSpec
from xtouch_daemon.gui.quick.forms.suggestions import lines
from xtouch_daemon.gui.quick.models import KeyedListModel
from xtouch_daemon.gui.quick.pages.base import PageBackend
from xtouch_daemon.gui.quick.pages.settings_support import BrokerTester, PluginInstaller, default_installers
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import Snapshot

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.app import App

PAGE_TITLES = {
    "device": "Extender",
    "mqtt": "Home Assistant",
    "switching": "Modes and chord",
    "voip": "Voice chat",
}
"""The names of the settings for people, in the navigation."""
SECTION_TITLES = {"mqtt": "MQTT broker", "homeassistant": "API"}
"""The headings of sections that share a page: the MQTT broker is how Home Assistant is reached, its API how the
entities are."""
SETTINGS_PAGES = ("behavior", "aliases", "mqtt", "homeassistant", "switching", "voip", "device")
"""The settings, the ones changed most often first: `[device]` is set once, if ever."""
SETTINGS_GROUPS = {"mqtt": ("mqtt", "homeassistant")}
"""Sections that share an entry of the navigation and a page, one below the other, by the first of them."""
NO_ANSWER = "Fix the problems of the settings first."


def page_title(name: str) -> str:
    return PAGE_TITLES.get(name, name.capitalize())


def section_title(name: str) -> str:
    """The heading of a section on its page."""
    return SECTION_TITLES.get(name, page_title(name))


def settings_entry(name: str) -> str:
    """The entry of the navigation that shows the section `name`: its own, or the first of its group."""
    return next((first for first, group in SETTINGS_GROUPS.items() if name in group), name)


SETTINGS_NAV = tuple(name for name in SETTINGS_PAGES if settings_entry(name) == name)
"""The entries of the navigation."""


def status_view(status: Status) -> dict[str, str]:
    return {"text": status.text, "tone": status.tone.value, "tip": status.tip}


class Connection(QObject):
    """How the daemon's connection (to the broker, to the API) is doing, and the test of the settings in the editor."""

    viewChanged = pyqtSignal(arguments=[])

    def __init__(self, parent: QObject, live: Status) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self._live = live
        self._tested: Status | None = None
        self._testing = False

    @pyqtProperty("QVariantMap", notify=viewChanged)
    def view(self) -> dict[str, Any]:  # pyright: ignore[reportRedeclaration]
        """`live` (the daemon's: text, tone, tip), `test` (the result of the latest test or None) and `testing`."""
        return {
            "live": status_view(self._live),
            "test": status_view(self._tested) if self._tested is not None else None,
            "testing": self._testing,
        }

    def show_live(self, status: Status) -> None:
        if status != self._live:
            self._live = status
            self.viewChanged.emit()

    def start(self, status: Status) -> None:
        self._testing = True
        self._tested = status
        self.viewChanged.emit()

    def finish(self, status: Status | None) -> None:
        self._testing = False
        self._tested = status
        self.viewChanged.emit()

    def clear(self) -> None:
        """A test of settings that are gone says nothing."""
        if self._tested is not None:
            self._tested = None
            self.viewChanged.emit()


class SectionBackend(QObject):
    """A section with options of its own: its form, and whether the file has it."""

    presentChanged = pyqtSignal(arguments=[])

    def __init__(self, page: SettingsPage, section: Section, context: FormContext) -> None:
        super().__init__(page)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.page = page
        self.section = section
        self.editor = context.editor
        name = section.name
        suggest = {"ignore": lambda: sources.patterns(context.audio())}
        self._form = Form(
            context,
            [
                RowSpec(option, suggest=suggest.get(option.name), link=docs.option_link(name, option.name))
                for option in options(section.model)
            ],
            base=(name,),
            present=lambda: self.editor.document.has_section(name),
            parent=self,
        )
        self._present = self.editor.document.has_section(name)
        self.editor.changed.connect(self._changed)
        self.connection: Connection | None = None

    @pyqtProperty(str, constant=True)
    def name(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self.section.name

    @pyqtProperty(str, constant=True)
    def title(self) -> str:  # pyright: ignore[reportRedeclaration]
        return section_title(self.section.name)

    @pyqtProperty(str, constant=True)
    def help(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self.section.help

    @pyqtProperty(str, constant=True)
    def link(self) -> str:  # pyright: ignore[reportRedeclaration]
        return docs.page_link(self.section.name) or ""

    @pyqtProperty(bool, constant=True)
    def optional(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self.section.optional

    @pyqtProperty(str, constant=True)
    def absent(self) -> str:  # pyright: ignore[reportRedeclaration]
        """What the page says while the file has no such section."""
        if self.section.name == "voip":
            return (
                "There is no [voip] section in the file, so voip strips use its defaults: the participants come from "
                "the plugin of Mumble or TeamSpeak. Add it to change that."
            )
        return f"There is no [{self.section.name}] section in the file."

    @pyqtProperty(str, constant=True)
    def note(self) -> str:  # pyright: ignore[reportRedeclaration]
        return "A changed name takes a restart of the service." if self.section.name == "device" else ""

    @pyqtProperty(bool, notify=presentChanged)
    def present(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._present

    @pyqtProperty(QObject, constant=True)
    def form(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._form

    @pyqtProperty(QObject, constant=True)  # pyright: ignore[reportArgumentType]
    def live(self) -> QObject | None:  # pyright: ignore[reportRedeclaration, reportArgumentType]
        """How the connection of the section is doing and its test; None for a section with none."""
        return self.connection

    def _changed(self, change: Change) -> None:
        present = self.editor.document.has_section(self.section.name)
        if present != self._present:
            self._present = present
            self.presentChanged.emit()
            if not present and self.connection is not None:
                self.connection.clear()

    @pyqtSlot()
    def add(self) -> None:
        self.editor.add_section(self.section.name)

    @pyqtSlot()
    def remove(self) -> None:
        self.editor.remove_section(self.section.name)


class MqttSection(SectionBackend):
    """`[mqtt]`, with the connection of the daemon to the broker and a test of the settings in the editor."""

    def __init__(self, page: SettingsPage, section: Section, context: FormContext, tester: BrokerTester) -> None:
        super().__init__(page, section, context)
        self.tester = tester
        self.connection = Connection(self, live_status(None))
        tester.finished.connect(self._tested)

    @pyqtSlot()
    def test(self) -> None:
        """Tries the settings in the editor (see `try_broker`)."""
        assert self.connection is not None
        try:
            config = MqttConfig.model_validate(self.editor.document.get(("mqtt",)) or {})
        except ValidationError:
            self.connection.finish(Status(NO_ANSWER, Tone.BAD))
            return
        self.connection.start(Status(f"Connecting to {config.host}:{config.port}…", Tone.NEUTRAL))
        self.tester.start(config)

    def _tested(self, status: Status) -> None:
        assert self.connection is not None
        # a result that comes after the section was removed has nowhere to go
        self.connection.finish(status if self.editor.document.has_section("mqtt") else None)

    def show_live(self, snapshot: Snapshot | None) -> None:
        assert self.connection is not None
        self.connection.show_live(live_status(snapshot))


class HomeAssistantSection(SectionBackend):
    """`[homeassistant]`: the connection to the API and a test; the entities a test finds are the suggestions."""

    def __init__(self, page: SettingsPage, section: Section, context: FormContext) -> None:
        super().__init__(page, section, context)
        self.context = context
        self.connection = Connection(self, entities.live_status(None))
        context.entity_source.tested.connect(self._tested)

    @pyqtSlot()
    def test(self) -> None:
        """Tries the settings in the editor (see `entities.try_home_assistant`)."""
        assert self.connection is not None
        try:
            config = HomeAssistantConfig.model_validate(self.editor.document.get(("homeassistant",)) or {})
        except ValidationError:
            self.connection.finish(Status(NO_ANSWER, Tone.BAD))
            return
        self.connection.start(Status(f"Connecting to {config.url}…", Tone.NEUTRAL))
        self.context.entity_source.test(config)

    def _tested(self, status: Status) -> None:
        assert self.connection is not None
        self.connection.finish(status if self.editor.document.has_section("homeassistant") else None)

    def show_live(self, snapshot: Snapshot | None) -> None:
        assert self.connection is not None
        self.connection.show_live(entities.live_status(snapshot))
        self.context.entity_source.show_live(snapshot)


class PluginBackend(QObject):
    """The plugin of a voice chat client: whether it is connected, the steps to set it up, and its install."""

    viewChanged = pyqtSignal(arguments=[])

    def __init__(self, installer: PluginInstaller, parent: QObject) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.installer = installer
        self.client = installer.client
        self.setup = installer.setup()
        """The setup of the plugin: looked up when the page shows and after an install, not with every snapshot of the
        daemon (60 a second), as it searches the disk."""
        self.snapshot: Snapshot | None = None
        self.outcome: Status | None = None
        self.installing = False
        self._view: dict[str, Any] = {}
        installer.finished.connect(self._installed)
        self._render()

    @pyqtProperty("QVariantMap", notify=viewChanged)
    def view(self) -> dict[str, Any]:  # pyright: ignore[reportRedeclaration]
        return self._view

    @pyqtProperty(str, constant=True)
    def name(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self.client.name

    def look_up(self) -> None:
        self.setup = self.installer.setup()
        self._render()

    def show_live(self, snapshot: Snapshot | None) -> None:
        self.snapshot = snapshot
        self._render()

    @pyqtSlot()
    def install(self) -> None:
        self.installing = True
        self.outcome = Status("Preparing the plugin…", Tone.NEUTRAL)
        self._render()
        self.installer.start()

    def _installed(self, status: Status) -> None:
        self.installing = False
        self.outcome = status
        self.look_up()

    def _render(self) -> None:
        client, setup = self.client, self.setup
        hint = install_hint(client, setup)
        link = f'&emsp;<a href="{html.escape(docs.guide_link(client.guide))}">Learn&nbsp;more&nbsp;↗</a>'
        # a client that is not installed (and whose plugin is not connected) gets a line only
        compact = not setup.client and not connected_here(self.snapshot, client)
        live = Status("not installed", Tone.NEUTRAL, hint) if compact else client_status(self.snapshot, client)
        if compact:
            steps = f"{html.escape(hint)}{link}"
        else:
            items = "".join(f"<li>{html.escape(step)}</li>" for step in install_steps(client, setup))
            steps = f"Set up the plugin once:<ol>{items}</ol>{html.escape(hint)}{link}"
        view = {
            "name": client.name,
            "pill": status_view(live),
            "detail": "" if compact else live.tip,
            "compact": compact,
            "steps": steps,
            "installEnabled": setup.installable and not self.installing,
            "installTip": hint,
            "outcome": status_view(self.outcome) if self.outcome is not None else None,
            "installing": self.installing,
        }
        if view != self._view:
            self._view = view
            self.viewChanged.emit()


class VoipSection(SectionBackend):
    """`[voip]`, with the plugin of each client: they show without the section too (voip strips work without it)."""

    def __init__(
        self, page: SettingsPage, section: Section, context: FormContext, installers: Sequence[PluginInstaller]
    ) -> None:
        super().__init__(page, section, context)
        self.boxes = [PluginBackend(installer, self) for installer in installers]

    @pyqtProperty("QVariantList", constant=True)
    def plugins(self) -> list[QObject]:  # pyright: ignore[reportRedeclaration]
        return list(self.boxes)

    def look_up(self) -> None:
        for box in self.boxes:
            box.look_up()

    def show_live(self, snapshot: Snapshot | None) -> None:
        for box in self.boxes:
            box.show_live(snapshot)


class AliasesBackend(QObject):
    """
    The names `auto` strips show for applications: a row each, edited in place. The file gets the rows with a name,
    each name once; the others stay here, marked, until they have one.
    """

    rowsChanged = pyqtSignal(arguments=[])
    restChanged = pyqtSignal(arguments=[])

    def __init__(self, page: SettingsPage, context: FormContext) -> None:
        super().__init__(page)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.context = context
        self.editor = context.editor
        self._rows: list[list[str]] = []  # [key, name, alias]
        self._next = 0
        self._model = KeyedListModel(self)
        self._rest: list[str] = []
        self._show_document()
        self.editor.changed.connect(self._changed)

    @pyqtProperty(QObject, constant=True)
    def rows(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """The rows `{ name, alias, nameProblem, aliasProblem }` by their keys."""
        return self._model

    @pyqtProperty("QStringList", notify=restChanged)
    def rest(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        return self._rest

    @pyqtProperty(str, constant=True)
    def help(self) -> str:  # pyright: ignore[reportRedeclaration]
        return Config.model_fields["aliases"].description or ""

    @pyqtProperty(str, constant=True)
    def link(self) -> str:  # pyright: ignore[reportRedeclaration]
        return docs.page_link("aliases") or ""

    @pyqtProperty(int, constant=True)
    def labelWidth(self) -> int:  # pyright: ignore[reportRedeclaration]
        return protocol.LCD_CELL_WIDTH

    def _new_key(self) -> str:
        self._next += 1
        return f"alias_{self._next}"

    def _document_pairs(self) -> list[tuple[str, str]]:
        return list(self.editor.document.get(("aliases",), {}).items())

    def _show_document(self) -> None:
        """As many rows as aliases, with their texts: only the texts that differ are set."""
        pairs = self._document_pairs()
        del self._rows[len(pairs) :]
        while len(self._rows) < len(pairs):
            self._rows.append([self._new_key(), "", ""])
        for row, (name, alias) in zip(self._rows, pairs, strict=True):
            row[1], row[2] = name, alias
        self._show()

    def _changed(self, change: Change) -> None:
        if change.touches(Scope.ALIASES):
            self._show_document()
        else:
            self._show()

    def _show(self) -> None:
        """The rows with their problems: a name that is empty or twice, an alias the file's validation faults."""
        validation = self.editor.validation
        names = [name for _, name, _ in self._rows]
        self._model.show(
            [
                (
                    key,
                    {
                        "name": name,
                        "alias": alias,
                        "nameProblem": not name or names.count(name) > 1,
                        "aliasProblem": bool(validation.at("aliases", name)),
                    },
                )
                for key, name, alias in self._rows
            ]
        )
        rest = [f"{problem.path[-1]!r}: {problem.message}" for problem in validation.at("aliases")]
        if "" in names:
            rest.append("'': the name of the application is missing")
        rest.extend(
            f"{name!r}: twice, the file keeps the first"
            for name in dict.fromkeys(names)
            if names.count(name) > 1 and name
        )
        if rest != self._rest:
            self._rest = rest
            self.restChanged.emit()

    def _edited(self) -> None:
        aliases: dict[str, str] = {}
        for _, name, alias in self._rows:
            aliases.setdefault(name, alias)
        aliases.pop("", None)
        document = self.editor.document
        if aliases:
            document.set(("aliases",), aliases)
        else:
            document.unset(("aliases",))
        self.editor.edited(Change(Scope.VALUE, ("aliases",)))

    def _row(self, key: str) -> list[str] | None:
        return next((row for row in self._rows if row[0] == key), None)

    @pyqtSlot(str, str)
    def setName(self, key: str, text: str) -> None:
        if (row := self._row(key)) is not None and row[1] != text:
            row[1] = text
            self._edited()

    @pyqtSlot(str, str)
    def setAlias(self, key: str, text: str) -> None:
        if (row := self._row(key)) is not None and row[2] != text[: protocol.LCD_CELL_WIDTH]:
            row[2] = text[: protocol.LCD_CELL_WIDTH]
            self._edited()

    @pyqtSlot(result=str)  # pyright: ignore[reportArgumentType]
    def add(self) -> str:
        """Adds an empty row (it is in the file once it has a name); returns its key for the focus."""
        key = self._new_key()
        self._rows.append([key, "", ""])
        self._edited()
        return key

    @pyqtSlot(str)
    def remove(self, key: str) -> None:
        if (row := self._row(key)) is not None:
            self._rows.remove(row)
            self._edited()

    @pyqtSlot(str, str, result="QVariantMap")
    def suggestions(self, text: str, mode: str) -> dict[str, Any]:
        """The applications that play now, for the name of an alias."""
        found = sources.filtered(text, sources.applications(self.context.audio()))
        colors = THEMES[ThemeMode(mode)] if mode in ThemeMode._value2member_map_ else THEMES[ThemeMode.DARK]
        return lines(found, text, colors, "No application plays right now")


class SettingsPage(PageBackend):
    """The page Settings: its sections (`section(name)`), the aliases and the page shown (`current`)."""

    currentChanged = pyqtSignal(arguments=[])
    revealed = pyqtSignal(str, str, arguments=["section", "option"])
    """The window showed an option (`reveal`): its section is `current` now, and its form shows it."""

    def __init__(self, app: App, installers: Sequence[PluginInstaller] | None = None) -> None:
        super().__init__(app)
        self.context = forms_of(app)
        self.editor = app.editor
        deps = app.deps
        self.tester = BrokerTester(deps.try_broker)
        if installers is None:
            installers = deps.plugin_installers if deps.plugin_installers is not None else default_installers()  # pyright: ignore[reportAssignmentType]
        self._sections: dict[str, SectionBackend] = {}
        for name, section in SECTIONS.items():
            if name == "mqtt":
                self._sections[name] = MqttSection(self, section, self.context, self.tester)
            elif name == "homeassistant":
                self._sections[name] = HomeAssistantSection(self, section, self.context)
            elif name == "voip":
                self._sections[name] = VoipSection(self, section, self.context, installers)  # pyright: ignore[reportArgumentType]
            else:
                self._sections[name] = SectionBackend(self, section, self.context)
        self._aliases = AliasesBackend(self, self.context)
        self._current = SETTINGS_NAV[0]
        self.snapshot: Snapshot | None = None
        self.context.settingsWanted.connect(lambda: self.showSection("homeassistant"))

    # -- what QML shows ---------------------------------------------------------------------------------------------

    @pyqtProperty("QVariantList", constant=True)
    def entries(self) -> list[dict[str, str]]:  # pyright: ignore[reportRedeclaration]
        """The navigation: `name` and `title` of each page of the settings."""
        return [{"name": name, "title": page_title(name)} for name in SETTINGS_NAV]

    @pyqtProperty("QVariantMap", constant=True)
    def sections(self) -> dict[str, QObject]:  # pyright: ignore[reportRedeclaration]
        """The sections with options of their own, by name."""
        return dict(self._sections)

    @pyqtProperty(QObject, constant=True)
    def aliases(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._aliases

    @pyqtProperty(str, notify=currentChanged)
    def current(self) -> str:  # pyright: ignore[reportRedeclaration]
        """The entry of the navigation shown."""
        return self._current

    @pyqtSlot(str)
    def showSection(self, name: str) -> None:
        """Shows the page of a section (`homeassistant` is on the page of `mqtt`); the app shows this page too."""
        entry = settings_entry(name)
        if entry not in SETTINGS_NAV:
            return
        self.app.showPage("settings")
        if entry != self._current:
            self._current = entry
            self.currentChanged.emit()
        if entry == "voip":
            voip = self._sections["voip"]
            assert isinstance(voip, VoipSection)
            voip.look_up()
            voip.show_live(self.snapshot)

    @pyqtSlot("QVariantList")
    def reveal(self, path: list[str]) -> None:
        """Shows the option at `path` of the document (`["device", "name"]`, `["aliases", "Discord"]`), focused."""
        if not path:
            return
        section, option = str(path[0]), str(path[1]) if len(path) > 1 else ""
        if section not in self._sections and section != "aliases":
            return
        self.showSection(section)
        if section in self._sections and option:
            self._sections[section].form.reveal(option)  # pyright: ignore[reportAttributeAccessIssue]
        self.revealed.emit(section, option)

    def show_live(self, snapshot: Snapshot | None) -> None:
        """How the daemon is doing now (its latest snapshot): its connections, shown on the pages of them."""
        self.snapshot = snapshot
        for section in self._sections.values():
            if isinstance(section, MqttSection | HomeAssistantSection | VoipSection):
                section.show_live(snapshot)
