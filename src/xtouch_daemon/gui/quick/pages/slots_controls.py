"""
The controls of the slot picked (`[controls].<n>`) for QML: a row per entry with its `when`, the parts it sets and
what can still be added. Edits go through the editor like the others: a step to undo, then the file. The fields of
the parts are the option rows of a `Form` per entry (`entryForm(index)`): it reads and writes the entry in the file,
and a part removed with its reset button takes its row away.
"""

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.schema import Kind, controls_options
from xtouch_daemon.gui.domain.slot_controls import (
    PART_TITLES,
    START,
    Entry,
    controls_value,
    custom_channels,
    entries,
    entry_path,
    entry_problems,
    entry_text,
    listed,
    missing,
    modes_and_states,
    moved,
    parts,
    uses_home_assistant,
)
from xtouch_daemon.gui.domain.slot_stacks import targets
from xtouch_daemon.gui.domain.slots_document import OptionPath, Validation
from xtouch_daemon.gui.qt.editor import Editor
from xtouch_daemon.gui.quick.forms.buttons import ButtonLogic
from xtouch_daemon.gui.quick.forms.context import FormContext
from xtouch_daemon.gui.quick.forms.form import Form, RowSpec
from xtouch_daemon.gui.quick.models import KeyedListModel
from xtouch_daemon.gui.quick.pages.slots_data import rich
from xtouch_daemon.slots.model import DEFAULT

OPTIONS = {option.name: option for option in controls_options()}
"""The options of an entry of `[controls]`, by name: its parts, `when` and `id`."""
WHEN_HELP = (
    "The entry acts while this condition of states and modes holds. Empty means always. Of several entries, the "
    "first whose condition holds acts."
)
"""The help under When of an entry."""
PRESS_UNSET = "As on what the slot shows"
"""The placeholder of a press an entry leaves unset: a press goes to what the slot shows."""
REMOVE_PART = "Remove the part: it goes back to what the slot shows"
"""What the reset button of a part says."""


def section_help(slot: int) -> str:
    """The help under the title of the controls."""
    return (
        f"Parts of slot {slot} that act the same whatever the slot shows. While its `when` holds, an entry overrides "
        "what the slot shows."
    )


def empty_help(slot: int) -> str:
    """What the controls say while the slot has none."""
    return f"`[controls]` claims no part of slot {slot}. Add a part, e.g. a meter that always shows the CPU load."


def help_of(option: str) -> str:
    """The help of a part as a plain tooltip."""
    return OPTIONS[option].help.replace("`", "")


def link(text: str, guide: str) -> str:
    """`text` as rich text, ending in the link to a guide."""
    return f'{rich(text)} <a href="{docs.guide_link(guide)}">Learn more</a>'


class SlotControls(QObject):
    """The controls of one slot at a time (`show_slot`), for the inspector."""

    changed = pyqtSignal(arguments=[])

    def __init__(self, editor: Editor, context: Callable[[], FormContext], parent: QObject | None = None) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]
        self.editor = editor
        self.context = context
        """Finds the context of the forms: made when the first form is (after the pages)."""
        self._forms: dict[int, tuple[Form, tuple[str, ...]]] = {}
        """The form of the parts of each entry, with the parts its rows are for."""
        self.slot = 1
        self._entries = KeyedListModel(self)
        self._error = ""
        self._help = ""

    # -- what QML shows -------------------------------------------------------------------------------------------

    @pyqtProperty(QObject, constant=True)
    def entries(self) -> KeyedListModel:  # pyright: ignore[reportRedeclaration]
        return self._entries

    @pyqtProperty(str, notify=changed)
    def title(self) -> str:  # pyright: ignore[reportRedeclaration]
        return f"Controls of slot {self.slot}"

    @pyqtProperty(str, notify=changed)
    def help(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._help

    @pyqtProperty(str, notify=changed)
    def error(self) -> str:  # pyright: ignore[reportRedeclaration]
        """The problems of the controls as a whole (not of an entry), a line each."""
        return self._error

    @pyqtProperty(str, notify=changed)
    def addPlaceholder(self) -> str:  # pyright: ignore[reportRedeclaration]
        return "Add controls" if self._entries.rows else "Add a part"

    @pyqtProperty(str, notify=changed)
    def addTip(self) -> str:  # pyright: ignore[reportRedeclaration]
        if self._entries.rows:
            return "A new entry that claims a part of the slot, e.g. for another `when`"
        return "Claims a part of the slot, whatever it shows"

    @pyqtProperty("QVariantList", constant=True)
    def addChoices(self) -> list[dict[str, str]]:  # pyright: ignore[reportRedeclaration]
        """The parts a new entry can claim."""
        return [{"text": title, "name": name, "tip": help_of(name)} for name, title in PART_TITLES.items()]

    @pyqtProperty("QVariantList", notify=changed)
    def whenStates(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        """The states and modes the condition of an entry may name."""
        return [*self._values().get("state", {}), DEFAULT]

    @pyqtProperty("QVariantList", notify=changed)
    def whenTargets(self) -> list[str]:  # pyright: ignore[reportRedeclaration]
        return targets(self._values())

    # -- showing --------------------------------------------------------------------------------------------------

    def _values(self) -> dict[str, Any]:
        return self.editor.document.values

    def path(self, index: int) -> OptionPath:
        return entry_path(self.slot, index, listed(self._values(), self.slot))

    def show_slot(self, slot: int) -> None:
        """Shows the controls of the slot, as the file has them now."""
        self.slot = slot
        self.refresh()

    def refresh(self) -> None:
        """Shows the controls again (the file changed): rows come, go or change in place."""
        found = entries(self._values(), self.slot)
        self._show_forms(found)
        self._help = link(section_help(self.slot) if found else empty_help(self.slot), "controls")
        rows: list[tuple[str, dict[str, Any]]] = []
        for index, entry in enumerate(found):
            rows.append((f"entry{index}", self._row(index, entry, len(found))))
        self._entries.show(rows)
        self.show_problems(self.editor.validation)
        self.changed.emit()

    # -- the forms of the parts -----------------------------------------------------------------------------------

    @pyqtSlot(int, result=QObject)  # pyright: ignore[reportArgumentType]
    def entryForm(self, index: int) -> QObject | None:
        """The form of the parts of the entry `index` (the option rows of the forms)."""
        found = self._forms.get(index)
        return found[0] if found is not None else None

    def _show_forms(self, found: list[Entry]) -> None:
        """A form per entry; its rows change in place while the parts stay, they come and go with the parts."""
        for index, (form, names) in self._forms.items():
            if index >= len(found) and names:
                # the delegate of a removed entry may still show it while it goes: its rows go, the form stays
                self._forms[index] = form, ()
                form.set_specs([])
        for index, entry in enumerate(found):
            names = (*parts(entry), *(["id"] if "id" in entry or uses_home_assistant(entry) else []))
            path = tuple(str(each) if isinstance(each, str) else each for each in self.path(index))
            previous = self._forms.get(index)
            if previous is None:
                form = Form(self.context(), base=path)
                form.edited.connect(lambda name, index=index: self._edited(index, name))
            else:
                form = previous[0]
                form.base = path
            if previous is None or previous[1] != names:
                self._forms[index] = form, names
                form.set_specs([self._spec(index, name) for name in names])
            else:
                form.refresh()

    def _spec(self, index: int, name: str) -> RowSpec:
        """The row of a part of an entry (or its `id`), as the device names the part."""
        option = OPTIONS[name]
        spec = RowSpec(
            option,
            title=PART_TITLES.get(name, option.title),
            link=docs.guide_link("controls"),
            reset_tip=REMOVE_PART if name != "id" else "Unset",
            put=lambda value: self.put((*self.path(index), name), value),
            placeholder=(lambda: f"slot_{self.slot}") if name == "id" else None,
        )
        if option.kind == Kind.CLAIM:
            spec.buttons = ButtonLogic(
                name,
                option.columns,
                claim=True,
                extra=lambda: modes_and_states(self._values()),
                inherited=lambda part: self._button_placeholder(index, name, part),
            )
        elif option.kind == Kind.BINDING and option.channel:
            spec.channels = lambda: custom_channels(self._values())
        return spec

    def _button_placeholder(self, index: int, name: str, part: str) -> str:
        """What a press or an LED the entry leaves unset does: as the slot shows it, or what the press does."""
        found = entries(self._values(), self.slot)
        value = found[index].get(name) if index < len(found) else None
        # a press: an action, `{ launch }`, `{ run }` or `{ service }`, or the `press` of a table
        pressed = isinstance(value, str) or (
            isinstance(value, dict) and bool({"press", "launch", "run", "service"} & set(value))  # pyright: ignore[reportUnknownArgumentType]
        )
        return "What the press does" if part == "led" and pressed else PRESS_UNSET

    def _edited(self, index: int, name: str) -> None:
        """A field of a part edited the file: a part that went takes its row away, else the entry's title may change."""
        found = entries(self._values(), self.slot)
        if index < len(found) and found[index].get(name) is not None:
            self.refresh()
        else:
            self.editor.edited(Change(Scope.SLOTS, ("controls", str(self.slot))))

    def _row(self, index: int, entry: Entry, count: int) -> dict[str, Any]:
        return {
            "index": index,
            "title": (f"{index + 1}. " if count > 1 else "") + entry_text(entry),
            "many": count > 1,
            "canUp": index > 0,
            "canDown": index < count - 1,
            "when": str(entry.get("when") or ""),
            "parts": [{"name": name, "title": PART_TITLES.get(name, OPTIONS[name].title)} for name in parts(entry)],
            "hasId": "id" in entry or uses_home_assistant(entry),
            "path": list(self.path(index)),
            "missing": [{"text": PART_TITLES[name], "name": name, "tip": help_of(name)} for name in missing(entry)],
            "whenHelp": link(WHEN_HELP, "conditions"),
            "whenError": "",
            "error": "",
        }

    def show_problems(self, validation: Validation) -> None:
        problems = validation.at("controls", str(self.slot))
        rows = self._entries.rows
        updated: list[tuple[str, dict[str, Any]]] = []
        for key, row in rows:
            path = self.path(row["index"])
            when = [p.message for p in problems if p.path[: len(path) + 1] == (*path, "when")]
            rest = [p.message for p in entry_problems(problems, path)]
            updated.append((key, {**row, "whenError": "\n".join(when), "error": "\n".join(rest)}))
        if [row for _, row in updated] != [row for _, row in rows]:
            self._entries.show(updated)
        # of the slot as a whole: a list that is no list of tables, ...
        whole = [
            problem.message
            for problem in problems
            if problem.path == ("controls", str(self.slot)) and listed(self._values(), self.slot)
        ]
        error = "\n".join(whole)
        if error != self._error:
            self._error = error
            self.changed.emit()

    # -- editing --------------------------------------------------------------------------------------------------

    def _write(self, found: list[Entry]) -> None:
        value = controls_value(found)
        if value is None:
            self.editor.document.unset(("controls", str(self.slot)))
        else:
            self.editor.document.set(("controls", str(self.slot)), value)
        self.editor.edited(Change(Scope.SLOTS, ("controls", str(self.slot))))

    @pyqtSlot(str)
    def addEntry(self, name: str) -> None:
        """A new entry that claims the part `name`, as it starts (see `START`)."""
        if name in START:
            self._write([*entries(self._values(), self.slot), {name: START[name]}])

    @pyqtSlot(int, str)
    def addPart(self, index: int, name: str) -> None:
        """Adds a part to an entry, as it starts."""
        found = entries(self._values(), self.slot)
        if name in START and 0 <= index < len(found):
            found[index][name] = START[name]
            self._write(found)

    @pyqtSlot(int)
    def removeEntry(self, index: int) -> None:
        found = entries(self._values(), self.slot)
        if 0 <= index < len(found):
            del found[index]
            self._write(found)

    @pyqtSlot(int, int)
    def moveEntry(self, index: int, offset: int) -> None:
        found = entries(self._values(), self.slot)
        if 0 <= index < len(found) and 0 <= index + offset < len(found):
            self._write(moved(found, index, offset))

    @pyqtSlot(int, str)
    def setWhen(self, index: int, text: str) -> None:
        when = text.strip()
        found = entries(self._values(), self.slot)
        if 0 <= index < len(found) and when != (found[index].get("when") or ""):
            self.put((*self.path(index), "when"), when or None)
            self.editor.edited(Change(Scope.VALUE, (*self.path(index), "when")))

    def put(self, path: OptionPath, value: Any) -> None:
        """Sets a value of an entry (None: removes it; a list left with one entry becomes a table again)."""
        if value is None:
            self.editor.document.unset(path)
            found = entries(self._values(), self.slot)
            if len(found) == 1 and listed(self._values(), self.slot):
                self.editor.document.set(("controls", str(self.slot)), found[0])
        else:
            self.editor.document.set(path, value)
