"""
The page of the layout being edited: its name, its rules and the layout it switches from.
"""

from typing import Any

from PyQt6.QtWidgets import QHBoxLayout, QWidget

from xtouch_daemon.config.layout import LayoutConfig
from xtouch_daemon.gui.domain import docs, sources
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.drafts import Validation
from xtouch_daemon.gui.domain.schema import options
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.qt.fields.basics import Suggest, flat_button, help_label, label
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.pages.base import Audio, Page, Stack, button, card, row, set_text


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
