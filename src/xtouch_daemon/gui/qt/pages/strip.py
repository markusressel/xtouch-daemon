"""
The page of the selected strip: its type, and the form of the options of that type.
"""

from collections.abc import Callable

from PyQt6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from xtouch_daemon.audio.model import Direction
from xtouch_daemon.config.legacy.strips import LEGACY_STRIP_TYPES as STRIP_TYPES
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.values import DEFAULT_LAYOUT, default_encoder
from xtouch_daemon.gui.domain import docs, inherit, sources
from xtouch_daemon.gui.domain.changes import Change
from xtouch_daemon.gui.domain.drafts import StripDraft, Validation
from xtouch_daemon.gui.domain.looks import look
from xtouch_daemon.gui.domain.schema import strip_models, strip_options, strip_type_help
from xtouch_daemon.gui.domain.voip import participants
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import (
    Suggest,
    TableSuggest,
    flat_button,
    help_html,
    help_label,
    help_text,
    label,
)
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.pages.base import LAYOUT_TYPES, Audio, Page, Stack, button, card, row, set_text, type_title
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import Snapshot


class StripPage(Page):
    """
    The strip selected in the preview: its type and its options, or how to configure it. It has a form for each strip
    type, built the first time a strip of that type is shown; selecting another strip loads its values into the form
    of its type (`show_strip`).
    """

    def __init__(
        self,
        editor: Editor,
        audio: Audio,
        show_page: Callable[[str], None],
        snapshot: Callable[[], Snapshot | None] = lambda: None,
    ):
        super().__init__(editor, audio)
        self.show_page = show_page
        """Shows one of the global settings, e.g. the Home Assistant connection a `homeassistant` strip uses."""
        self.snapshot = snapshot
        """The live view of the daemon now, e.g. for the people in the voice chat."""
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
        self.remove_button.setToolTip(
            "Remove the strip: its place becomes an auto strip, the other strips stay where they are"
        )
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
            move.setEnabled(0 <= index + step < max(len(self.document.strips), protocol.STRIPS))
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


EXCLUSIVE_GROUPS = {"one": ("device", "profiles"), "choices": ("choices",)}
"""The options of a device strip that exclude each other: one device (or several) with profiles, or choices."""
EXCLUSIVE = {name: group for group, names in EXCLUSIVE_GROUPS.items() for name in names}


class StripForm(QWidget):
    """The type of a strip and the options of that type, for whichever strip of the type the page shows."""

    def __init__(self, page: StripPage, strip_type: str | None):
        super().__init__()
        self.page = page
        self.strip_type = strip_type
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Space.M)
        types = QHBoxLayout()
        types.setSpacing(0)
        self.types = QButtonGroup(self)
        self.type_buttons: dict[str, QPushButton] = {}
        for name in STRIP_TYPES:
            segment = QPushButton(type_title(name))
            set_role(segment, "segment", "variant")
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
        table_suggest: dict[str, TableSuggest] = {}
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
            choices: TableSuggest = {
                "device": lambda _line: sources.devices(page.audio(), direction),
                "card": lambda _line: sources.cards(page.audio()),
                "profile": lambda line: sources.card_profiles(page.audio(), str(line.get("card", ""))),
            }
            table_suggest["choices"] = choices
            placeholders["device"] = lambda: f"none: the default {strip_type}"
        if strip_type == "homeassistant":
            placeholders["id"] = lambda: f"strip_{page.index + 1}"
        if strip_type == "inherit":
            suggest["layout"] = lambda: inherit.layouts(page.document)
            suggest["strip"] = lambda: inherit.strips(page.document, page._value(("strip", page.index, "layout")))
            placeholders["layout"] = lambda: DEFAULT_LAYOUT
            placeholders["strip"] = lambda: "the strip at this place"
        if strip_type == "voip":
            suggest["person"] = lambda: participants(page.snapshot())
            placeholders["person"] = lambda: "none: part of the group"
        if strip_type in ("apps", "auto", "voip"):
            # one entry per part: the program first, then each argument
            placeholders["launch"] = lambda: "none: Select starts nothing; the program, then each argument"
        for option in strip_options(strip_type):
            option_row = page._row(
                option,
                lambda name: ("strip", page.index, name),
                table_suggest.get(option.name) or suggest.get(option.name),
                placeholders.get(option.name),
                docs.option_link("strip", option.name, strip_type),
                self.rows,
            )
            if option.name in ("device", "person"):
                # the label shown by default follows the device, or the person
                option_row.edited.connect(self._device_edited)
            if option.name in EXCLUSIVE:
                option_row.edited.connect(self._show_exclusive)
            options_layout.addWidget(option_row)
        if not self.rows:
            text = "An empty strip has no options." if strip_type == "empty" else "The strip has no options."
            options_layout.addWidget(label(text, "hint"))
        layout.addWidget(frame)

    def _show_exclusive(self) -> None:
        """
        `choices` or `device` and `profiles`: the ones in use, both while none is set (or both are, which is a
        problem). What is hidden keeps its values.
        """
        strip = self.page.document.strips[self.page.index] if self.page.configured else None
        values = strip.values if strip is not None else {}
        in_use = {group for group, names in EXCLUSIVE_GROUPS.items() if any(values.get(name) for name in names)}
        for option_row in self.rows:
            group = EXCLUSIVE.get(option_row.option.name)
            hidden = group is not None and len(in_use) == 1 and group not in in_use
            if option_row.isHidden() != hidden:
                option_row.setHidden(hidden)

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
        self._show_exclusive()
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
        set_icon(self.connection_button, icon, color)
        set_role(self.connection_button, role, "variant")

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
