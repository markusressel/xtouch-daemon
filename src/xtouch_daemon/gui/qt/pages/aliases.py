"""
The page of the aliases: the names `auto` strips show for applications.
"""

from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from xtouch_daemon.config.model import Config
from xtouch_daemon.gui.domain import docs, sources
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.slots_document import Validation
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import completer, flat_button, help_label, label, suggestion_menu
from xtouch_daemon.gui.qt.pages.base import Audio, Page, button, card, page_title, row
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.hardware import protocol


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
        aliases: list[tuple[str, str]] = list(self.document.get(("aliases",), {}).items())
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
        """The file gets the rows with a name, each name once; the others stay here, marked, until they have one."""
        aliases: dict[str, str] = {}
        for name, alias in self.edits:
            aliases.setdefault(name.text(), alias.text())
        aliases.pop("", None)
        if aliases:
            self.document.set(("aliases",), aliases)
        else:
            self.document.unset(("aliases",))
        self.editor.edited(Change(Scope.VALUE, ("aliases",)))

    def _add(self) -> None:
        self._line().setFocus()
        self._edited()

    def _remove(self, pair: tuple[QLineEdit, QLineEdit]) -> None:
        self._drop(self.edits.index(pair))
        self._edited()

    def show_problems(self, validation: Validation) -> None:
        names = [name.text() for name, _ in self.edits]
        for name, alias in self.edits:
            text = name.text()
            set_role(name, not text or names.count(text) > 1, "problem")
            set_role(alias, bool(validation.at("aliases", text)), "problem")
        rest = [f"{problem.path[-1]!r}: {problem.message}" for problem in validation.at("aliases")]
        if "" in names:
            rest.append("'': the name of the application is missing")
        rest.extend(
            f"{name!r}: twice, the file keeps the first"
            for name in dict.fromkeys(names)
            if names.count(name) > 1 and name
        )
        self._show_rest(rest)
