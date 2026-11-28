"""
The page States for QML: the modes, then the other states, in a list with a dot for what the daemon says right now,
and on the right what the one picked is: a mode or a state, its sources or a condition (never both), its delays, what
the daemon says about it (since when, from which source), its override and the last day. The forms of its options are in
`states_form`, the words and the rows of the list in `states_data`; QML shows it and animates it.

The window hooks in with `show_live(snapshot)` (the dots, the override) and `live` (`StatesLive`: the latest snapshot
and a way to send a request to the daemon). The question that comes with switching a state between sources and a
condition is answered on the page (`switchQuestion`, `confirmSwitch`, `cancelSwitch`).
"""

from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.clipboard import Tables, parse_tables, tables_text
from xtouch_daemon.gui.domain.states import describe_live, live_state, ordered, state_uses
from xtouch_daemon.gui.quick.forms.context import forms_of
from xtouch_daemon.gui.quick.models import KeyedListModel
from xtouch_daemon.gui.quick.pages.base import PageBackend
from xtouch_daemon.gui.quick.pages.channels_support import ID, NO_ID, PaneShare, clipboard_text, set_clipboard_text
from xtouch_daemon.gui.quick.pages.states_data import (
    DELAYS,
    EMPTY,
    HINT,
    KIND_HELP,
    MODE_ONLY,
    NO_SOURCES,
    NOT_USED,
    ON_WHILE_HELP,
    SOME_SOURCES,
    SOURCES,
    SWITCHES,
    TEMPLATES,
    WHEN_HELP,
    add_menu,
    is_set,
    list_rows,
    override_segments,
    segments,
    source_menu,
)
from xtouch_daemon.gui.quick.pages.states_form import StateForm, state_forms
from xtouch_daemon.live.messages import Request, SetMode, SetOverride, Snapshot
from xtouch_daemon.slots.model import DEFAULT

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.app import App


@dataclass
class StatesLive:
    """What the page reaches outside of itself: the window sets them (`StatesPage.live`); tests give fakes."""

    snapshot: Callable[[], Snapshot | None] = lambda: None
    """The last snapshot of the daemon, None without one."""
    request: Callable[[Request], bool] = lambda _: False
    """Sends a request to the daemon (an override, a mode picked); False without a daemon."""


class StatesPage(PageBackend):
    """See the module. `selection` is the name of the state picked, None while there is none."""

    selectionChanged = pyqtSignal(arguments=[])
    inspectorChanged = pyqtSignal(arguments=[])
    liveChanged = pyqtSignal(arguments=[])
    idProblemChanged = pyqtSignal(arguments=[])
    questionChanged = pyqtSignal(arguments=[])
    renameRequested = pyqtSignal(arguments=[])
    """The id of the state picked should get the keyboard focus, its text selected (F2)."""
    whenRequested = pyqtSignal(arguments=[])
    """The field of the condition should get the keyboard focus."""

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.editor = app.editor
        self.context = forms_of(app)
        self.live = StatesLive()
        extra = app.deps.extra.get("states_live")
        if isinstance(extra, StatesLive):
            self.live = extra
        self._pane = PaneShare("states", self)
        self.selection: str | None = None
        self.arranged: str | None = None
        """The state the form was last arranged for: another one closes the delays again and forgets added sources."""
        self.added: set[str] = set()
        """Sources added to the state shown that have no value yet."""
        self.composed: dict[str, bool] = {}
        """States set to Condition (or Sources) that have neither a condition nor sources yet."""
        self.delays_open = False
        self._entries = KeyedListModel(self)
        self._inspector: dict[str, Any] = {}
        self._live: dict[str, Any] = {}
        self._shown_values: tuple[bool, ...] | None = None
        self._id_problem = ""
        self._list_focused = False
        self._question: dict[str, Any] = {}
        self._pending: tuple[bool, list[str]] | None = None
        self.mode_form, self.sources_form, self.delays_form = state_forms(
            self.context, self._shows, lambda: ("state", self.selection or "")
        )
        for form in self.forms:
            form.edited.connect(self._edited)
        self.editor.changed.connect(self._changed)
        self._show()

    @property
    def forms(self) -> tuple[StateForm, StateForm, StateForm]:
        return self.mode_form, self.sources_form, self.delays_form

    # -- what QML reads -------------------------------------------------------------------------------------------

    @pyqtProperty(QObject, constant=True)
    def entries(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """The list: the modes, then the states (`states_data.list_rows`)."""
        return self._entries

    @pyqtProperty(QObject, constant=True)
    def tools(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self.context

    @pyqtProperty(QObject, constant=True)
    def pane(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self._pane

    @pyqtProperty(QObject, constant=True)
    def modeForm(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """The form of `label` and `priority`, shown for a mode."""
        return self.mode_form

    @pyqtProperty(QObject, constant=True)
    def sourcesForm(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """The form of the sources: those the state has, or that were just added."""
        return self.sources_form

    @pyqtProperty(QObject, constant=True)
    def delaysForm(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        """The form of the delays and `persist`: shown while the section is open."""
        return self.delays_form

    @pyqtProperty(str, constant=True)
    def hint(self) -> str:  # pyright: ignore[reportRedeclaration]
        return HINT

    @pyqtProperty(str, constant=True)
    def hintLink(self) -> str:  # pyright: ignore[reportRedeclaration]
        return docs.page_link("states") or ""

    @pyqtProperty(str, constant=True)
    def conditionLink(self) -> str:  # pyright: ignore[reportRedeclaration]
        return docs.guide_link("conditions")

    @pyqtProperty(str, notify=selectionChanged)
    def current(self) -> str:  # pyright: ignore[reportRedeclaration]
        """The name of the state picked, "" for none."""
        return self.selection or ""

    @pyqtProperty(int, notify=selectionChanged)
    def currentIndex(self) -> int:  # pyright: ignore[reportRedeclaration]
        keys = self._entries.keys()
        return keys.index(self.selection) if self.selection in keys else -1

    @pyqtProperty("QVariantMap", notify=inspectorChanged)
    def inspector(self) -> dict[str, Any]:  # pyright: ignore[reportRedeclaration]
        """What the right of the page shows of the state picked (see `_show_inspector`)."""
        return self._inspector

    @pyqtProperty("QVariantMap", notify=liveChanged)
    def liveInfo(self) -> dict[str, Any]:  # pyright: ignore[reportRedeclaration]
        """What the daemon says about the state: `text`, the override `segments`, the `history` of the last day."""
        return self._live

    @pyqtProperty(str, notify=idProblemChanged)
    def idProblem(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._id_problem

    @pyqtProperty("QVariantMap", notify=questionChanged)
    def switchQuestion(self) -> dict[str, Any]:  # pyright: ignore[reportRedeclaration]
        """The question about switching between sources and a condition (`title`, `text` as rich text), {} for none."""
        return self._question

    @property
    def states(self) -> dict[str, Any]:
        return self.editor.document.get(("state",), {})

    def _state(self, name: str | None = None) -> dict[str, Any]:
        found = self.states.get(name or self.selection or "")
        return found if isinstance(found, dict) else {}

    def _shows(self, option: str) -> bool:
        """Whether the row of `option` shows: label and priority of a mode, a source that is set, open delays."""
        state = self._state()
        if option in MODE_ONLY:
            return bool(state.get("mode"))
        if option in SOURCES:
            return is_set(state.get(option)) or option in self.added
        return self.delays_open

    # -- the document ---------------------------------------------------------------------------------------------

    def _changed(self, change: Change) -> None:
        if change.touches(Scope.STATES):
            self._show()
        else:
            # the forms show their own values; what shows of the state beside them may change
            self._show_list()
            self._show_inspector()
            self._show_live()
        self.editableChanged.emit()

    def _show(self) -> None:
        """After a change of the states: the state picked is still there (or the first one), everything shows."""
        names = ordered(self.states)
        if self.selection not in names:
            self.selection = names[0] if names else None
        name = self.selection
        if name != self.arranged:
            # another state: its delays open if it has any, sources added to the last one are gone
            self.arranged = name
            self.added = set()
            self.delays_open = name is not None and any(self._state(name).get(delay) is not None for delay in DELAYS)
            self._set_id_problem("")
        for form in self.forms:
            form.retarget(("state", name or ""))
        self._show_list()
        self._arrange()
        self.selectionChanged.emit()
        self.editableChanged.emit()

    def _arrange(self) -> None:
        """What fits the state shown: mode or not, sources or a condition, which rows show."""
        for form in self.forms:
            form.refresh()
        self._show_inspector()
        self._show_live()

    def _show_list(self) -> None:
        self._entries.show(list_rows(self.states, self.editor.validation, self.live.snapshot()))

    def _show_inspector(self) -> None:
        name = self.selection
        if name is None:
            inspector: dict[str, Any] = {"empty": True, "emptyText": EMPTY}
        else:
            state = self._state(name)
            mode = bool(state.get("mode"))
            composed = "when" in state or self.composed.get(name, False)
            shown = [source for source in SOURCES if is_set(state.get(source)) or source in self.added]
            others = [other for other in self.states if other != name]
            when = [problem.message for problem in self.editor.validation.at("state", name, "when")]
            inspector = {
                "empty": False,
                "emptyText": EMPTY,
                "name": name,
                "mode": mode,
                "title": "Mode" if mode else "State",
                "where": list(state_uses(self.editor.document.values, name)),
                "none": NOT_USED,
                "kind": segments((("state", "State"), ("mode", "Mode")), "mode" if mode else "state"),
                "kindHelp": KIND_HELP,
                "onWhile": segments(
                    (("sources", "Sources"), ("condition", "Condition")), "condition" if composed else "sources"
                ),
                "onWhileHelp": ON_WHILE_HELP,
                "composed": composed,
                "sourcesHint": SOME_SOURCES if shown else NO_SOURCES,
                "canAddSource": len(shown) < len(SOURCES),
                "when": str(state.get("when") or ""),
                "whenStates": [*others, DEFAULT],
                "whenError": "\n".join(when),
                "whenHelp": WHEN_HELP,
                "delaysOpen": self.delays_open,
                "problem": self._rest(name),
            }
        if inspector != self._inspector:
            self._inspector = inspector
            self.inspectorChanged.emit()

    def _rest(self, name: str) -> str:
        """The problems of the state that no row shows: its whole, or an option the model doesn't know."""
        names = {*MODE_ONLY, *SOURCES, *DELAYS, "when", "mode"}
        found = [
            problem.message if len(problem.path) == 2 else str(problem)
            for problem in self.editor.validation.at("state", name)
            if len(problem.path) == 2 or problem.path[2] not in names
        ]
        return "\n".join(found)

    def _show_live(self) -> None:
        """What the daemon says about the state, and its override (of a mode: whether it was picked by hand)."""
        name = self.selection
        snapshot = self.live.snapshot()
        if name is None:
            live: dict[str, Any] = {"text": "", "segments": [], "history": [], "hasHistory": False}
        else:
            state = live_state(snapshot, name)
            picked = snapshot.slots.mode_pick if snapshot is not None and snapshot.slots is not None else None
            mode = bool(self._state(name).get("mode"))
            live = {
                "text": describe_live(state),
                "segments": override_segments(mode, name, state, picked),
                "history": [[at, on] for at, on in state.history] if state is not None else [],
                "hasHistory": state is not None and bool(state.history),
            }
        if live != self._live:
            self._live = live
            self.liveChanged.emit()

    def show_live(self, snapshot: Snapshot | None) -> None:
        """The dots of the list, only when a value changed (the live view tells 20 times a second), the override."""
        values = tuple(state.value for state in snapshot.slots.states) if snapshot and snapshot.slots else None
        if values != self._shown_values:
            self._shown_values = values
            self._show_list()
        self._show_live()

    # -- picking --------------------------------------------------------------------------------------------------

    def select(self, name: str) -> None:
        self.selection = name
        self._show()

    @pyqtSlot(str)
    def pick(self, key: str) -> None:
        """An entry of the list was clicked (its name)."""
        if key in self.states:
            self.select(key)

    @pyqtSlot(int)
    def step(self, direction: int) -> None:
        """The next (or previous) entry of the list: the arrow keys."""
        names = self._entries.keys()
        if self.selection in names:
            self.select(names[max(0, min(len(names) - 1, names.index(self.selection) + direction))])

    def show_state(self, name: str) -> None:
        if name in self.states:
            self.select(name)

    @pyqtSlot("QVariantList")
    def reveal(self, path: list[str]) -> None:
        """Shows the option at `path` (`["state", "call", "delay_on"]`): picks its state, opens it, focuses the row."""
        if len(path) < 2 or path[0] != "state" or path[1] not in self.states:
            return
        self.select(str(path[1]))
        if len(path) < 3:
            return
        option = str(path[2])
        if option == "when":
            self.composed[self.selection or ""] = True
            self._arrange()
            QTimer.singleShot(0, self.whenRequested.emit)
            return
        if option in DELAYS:
            self.delays_open = True
        if option in SOURCES:
            self.added.add(option)
        self._arrange()
        form = self.mode_form if option in MODE_ONLY else self.sources_form if option in SOURCES else self.delays_form
        QTimer.singleShot(0, lambda: form.reveal(option))

    # -- adding and removing --------------------------------------------------------------------------------------

    @pyqtSlot(result="QVariantList")
    def addEntries(self) -> list[dict[str, Any]]:
        return add_menu()

    @pyqtSlot(str)
    def add(self, action: str) -> None:
        """An entry of the menu Add: `kind:mode`, `kind:state` or `template:<id>`."""
        what, _, rest = action.partition(":")
        if what == "kind":
            self.add_state(rest == "mode")
        elif what == "template":
            for _text, name, mode, options, _detail in TEMPLATES:
                if name == rest:
                    self.add_state(mode, name, dict(options))

    def add_state(self, mode: bool, name: str | None = None, options: dict[str, Any] | None = None) -> None:
        self.select(self.editor.add_state(mode, name, options))

    @pyqtSlot()
    def remove(self) -> None:
        if self.selection is not None:
            self.editor.remove_state(self.selection)

    @pyqtSlot()
    def duplicate(self) -> None:
        self._add(self._picked_table())

    def _picked_table(self) -> Tables:
        """The state picked, as tables to copy; none without one."""
        if self.selection is None:
            return {}
        return {"state": {self.selection: self.editor.document.get(("state", self.selection)) or {}}}

    def _add(self, tables: Tables) -> int:
        """Adds the states, picks the first one; how many."""
        added = self.editor.add_tables(tables)
        if added:
            self.select(added[0][1])
        return len(added)

    # -- renaming -------------------------------------------------------------------------------------------------

    @pyqtSlot(str, result=bool)  # pyright: ignore[reportArgumentType]
    def rename(self, new: str) -> bool:
        """Another id for the state picked (conditions and controls follow); False for one that can't be."""
        name = self.selection
        if name is None:
            return False
        if new == name:
            self._set_id_problem("")
            return True
        if not ID.fullmatch(new) or new in self.states or new == DEFAULT:
            self._set_id_problem(NO_ID.format(new))
            return False
        self._set_id_problem("")
        self.selection = new
        self.editor.rename_state(name, new)
        return True

    def _set_id_problem(self, text: str) -> None:
        if text != self._id_problem:
            self._id_problem = text
            self.idProblemChanged.emit()

    # -- the form -------------------------------------------------------------------------------------------------

    @pyqtSlot(bool)
    def setMode(self, mode: bool) -> None:
        """A mode, or a state: a state has no label and no priority, so they go."""
        name = self.selection
        if name is None:
            return
        document = self.editor.document
        if mode:
            document.set(("state", name, "mode"), True)
        else:
            for option in ("mode", *MODE_ONLY):
                document.unset(("state", name, option))
        self.editor.edited(Change(Scope.STATES))

    @pyqtSlot(bool)
    def setComposed(self, composed: bool) -> None:
        """On while a condition holds, or while sources are on: what the other way had goes, after a question."""
        name = self.selection
        if name is None:
            return
        state = self._state(name)
        dropped = [source for source in SOURCES if source in state] if composed else ["when"] * ("when" in state)
        if dropped:
            self._question = self._ask(composed, state, dropped)
            self._pending = (composed, dropped)
            self.questionChanged.emit()
            self._arrange()
        else:
            self._switch(composed, dropped)

    @staticmethod
    def _ask(composed: bool, state: dict[str, Any], dropped: list[str]) -> dict[str, Any]:
        """The question: a state is on by sources or by a condition, so what the state had the other way goes."""
        if composed:
            items = "".join(f"<li>{escape(SOURCES[source])}</li>" for source in dropped)
            return {
                "title": "Condition instead of sources",
                "text": "A state follows its sources or a condition, not both. "
                f"A condition removes its sources:<ul>{items}</ul>",
                "accept": "Remove and switch",
            }
        return {
            "title": "Sources instead of a condition",
            "text": "A state follows its sources or a condition, not both. Sources remove its condition "
            f"<code>{escape(str(state['when']))}</code>.",
            "accept": "Remove and switch",
        }

    @pyqtSlot()
    def confirmSwitch(self) -> None:
        pending, self._pending = self._pending, None
        if pending is not None:
            self._clear_question()
            self._switch(*pending)

    @pyqtSlot()
    def cancelSwitch(self) -> None:
        """The question was answered with Cancel: the old choice stays."""
        if self._pending is not None:
            self._pending = None
            self._clear_question()
            self._arrange()

    def _clear_question(self) -> None:
        if self._question:
            self._question = {}
            self.questionChanged.emit()

    def _switch(self, composed: bool, dropped: list[str]) -> None:
        name = self.selection
        assert name is not None
        self.composed[name] = composed
        self.added = set()
        for option in dropped:
            self.editor.document.unset(("state", name, option))
        if dropped:
            self.editor.edited(Change(Scope.STATES))
        else:
            self._arrange()
        if composed:
            self.whenRequested.emit()

    @pyqtSlot(result="QVariantList")
    def sourceEntries(self) -> list[dict[str, Any]]:
        """The menu Add source: the sources the state does not show yet."""
        state = self._state()
        return source_menu([source for source in SOURCES if is_set(state.get(source)) or source in self.added])

    @pyqtSlot(str)
    def addSource(self, source: str) -> None:
        name = self.selection
        if name is None or source not in SOURCES:
            return
        if source in SWITCHES:
            # a switch is the source once it is on: nothing else to fill in
            self.editor.document.set(("state", name, source), True)
            self.editor.edited(Change(Scope.VALUE, ("state", name, source)))
        else:
            self.added.add(source)
        self._arrange()

    def _edited(self, option: str) -> None:
        """A field of a form changed the document: a source that was removed is not just added any more."""
        if option in SOURCES and self._state().get(option) is None:
            self.added.discard(option)
            self._arrange()

    @pyqtSlot(bool)
    def setDelaysOpen(self, open: bool) -> None:
        if open != self.delays_open:
            self.delays_open = open
            self._arrange()

    @pyqtSlot(str)
    def setWhen(self, text: str) -> None:
        """The condition was typed: nothing is unset."""
        name = self.selection
        if name is None:
            return
        when = text.strip()
        if when == str(self._state(name).get("when") or ""):
            return
        self.composed[name] = True
        if when:
            self.editor.document.set(("state", name, "when"), when)
        else:
            self.editor.document.unset(("state", name, "when"))
        self.editor.edited(Change(Scope.VALUE, ("state", name, "when")))

    # -- the daemon -----------------------------------------------------------------------------------------------

    @pyqtSlot(str)
    def override(self, value: str) -> None:
        """Asks the daemon to override the state, or to pick the mode (`auto`: the rules decide again)."""
        name = self.selection
        if name is None:
            return
        if self._state(name).get("mode"):
            self.live.request(SetMode(name if value == "on" else "auto"))
        else:
            self.live.request(SetOverride(name, value))

    # -- the Edit menu --------------------------------------------------------------------------------------------

    @pyqtSlot(bool)
    def listFocus(self, focused: bool) -> None:
        """The list got or lost the keyboard focus: the Edit menu works on its entry."""
        if focused != self._list_focused:
            self._list_focused = focused
            self.editableChanged.emit()

    def editable_actions(self) -> list[str]:
        if not self._list_focused:
            return []
        if self.selection is None:
            return ["paste"]
        return ["cut", "copy", "paste", "duplicate", "remove", "rename"]

    @pyqtSlot(str)
    def edit(self, action: str) -> None:
        if action == "paste":
            self._add(parse_tables(clipboard_text(), ("state",)))
        elif self.selection is None:
            return
        elif action in ("copy", "cut"):
            set_clipboard_text(tables_text(self._picked_table()))
            if action == "cut":
                self.remove()
        elif action == "duplicate":
            self.duplicate()
        elif action == "remove":
            self.remove()
        elif action == "rename":
            self.renameRequested.emit()
