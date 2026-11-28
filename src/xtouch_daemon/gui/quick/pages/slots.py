"""
The page Slots for QML: the state bar and Simulate, a card per slot with its candidates on a rail, and the inspector
of the slot and the candidate picked (or the overview while nothing is). QML only shows them and moves.

What the page needs from outside (the live view of the daemon, the twin, the sound server) is a `Live`: the window
sets `SlotsPage.live` and calls `show_live(snapshot)` for each snapshot of the daemon.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]
from PyQt6.QtGui import QGuiApplication

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.channels import CHANNEL_TYPES, uses
from xtouch_daemon.gui.domain.clipboard import candidates_text, parse_candidates
from xtouch_daemon.gui.domain.places import Origin, Source, origin
from xtouch_daemon.gui.domain.simulate import Inputs, WhatIf
from xtouch_daemon.gui.domain.slot_controls import modes_and_states
from xtouch_daemon.gui.domain.slot_stacks import (
    EMPTY,
    Row,
    choice_groups,
    ends_dark,
    member_summary,
    place_options,
    pool_kind,
    pool_strip,
    pool_text,
    reasons,
    rows,
    stack_value,
    targets,
    why_steps,
)
from xtouch_daemon.gui.domain.slots_document import Validation
from xtouch_daemon.gui.domain.states import OVERRIDES
from xtouch_daemon.gui.domain.status import Reason
from xtouch_daemon.gui.quick.forms.context import forms_of
from xtouch_daemon.gui.quick.forms.form import Form
from xtouch_daemon.gui.quick.forms.places import place_specs
from xtouch_daemon.gui.quick.models import KeyedListModel
from xtouch_daemon.gui.quick.pages import slots_condition, slots_sound
from xtouch_daemon.gui.quick.pages.base import PageBackend
from xtouch_daemon.gui.quick.pages.slots_cards import SlotCard
from xtouch_daemon.gui.quick.pages.slots_controls import SlotControls, link
from xtouch_daemon.gui.quick.pages.slots_data import (
    card_rows,
    crumb_rows,
    hint_text,
    overview_row,
    rich,
    rich_lines,
    why_rows,
    why_tone,
)
from xtouch_daemon.gui.quick.pages.slots_simulate import (
    SIMULATE_TIP,
    WhatIfGroup,
    counted,
    state_rows,
    what_if_rows,
    with_mode,
)
from xtouch_daemon.gui.quick.pages.sound import sounding
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import Request, SetMode, SetOverride, SlotsState, SlotView, Snapshot
from xtouch_daemon.slots.model import AUTO, BUILT_IN, DEFAULT
from xtouch_daemon.slots.why import where

if TYPE_CHECKING:
    from xtouch_daemon.gui.quick.app import App

SHOWS_HELP = (
    "What the slot shows while this candidate wins: a channel, a pool (`apps`, `people`, `auto`, ...) or `-` for a "
    "dark strip. A pool with none left for the slot leaves it to the candidate below (a pool or `-`)."
)
"""The help under Shows (see Writing help in `AGENTS.md`)."""
WHEN_HELP = (
    "The slot shows this candidate while the condition holds and no candidate above it does. Empty means always. "
    "It takes states, modes, `present`, `and`, `or`, `not` and parentheses, e.g. `call and not gaming`."
)
"""The help under When."""
GROUPS = ("Mode", "States", "Channels", "Pools")
"""The groups of what-ifs, in the order they show."""

slots_condition.register()
slots_sound.register()


@dataclass
class Live:
    """What the page reaches outside of itself: the window sets them (`SlotsPage.live`); tests give fakes."""

    snapshot: Callable[[], Snapshot | None] = lambda: None
    """The last snapshot of the daemon, None without one."""
    request: Callable[[Request], bool] = lambda _: False
    """Sends a request to the daemon (`live.send`)."""
    twin_slots: Callable[[], SlotsState | None] = lambda: None
    """The slots of the virtual twin of the window (the preview in the GUI)."""
    simulate_unavailable: Callable[[], Reason | None] = lambda: None
    """Why Simulate can't run, None when it can."""
    shows_twin: Callable[[], bool] = lambda: False
    """Whether the drawing of the device shows the twin."""
    audio: Callable[[], AudioState] = AudioState
    """The sound server as the window last read it."""
    show_channel: Callable[[str], None] | None = None
    """Opens a channel on the page Channels (by default: shows that page)."""
    show_pool: Callable[[str], None] | None = None
    extra: dict[str, Any] = field(default_factory=dict[str, Any])


def _help(text: str) -> str:
    return rich_lines(text)


class SlotsPage(PageBackend):
    what_if: WhatIf | None = None
    """What Simulate shows, None while the cards show what the daemon tells."""
    what_if_start: WhatIf | None = None
    """Where Simulate started: reality, as the daemon told it then (see `WhatIf.of_live`)."""

    slotChanged = pyqtSignal(arguments=[])
    candidateChanged = pyqtSignal(arguments=[])
    simulatedChanged = pyqtSignal(arguments=[])
    simulated = pyqtSignal(arguments=[])
    """Simulate started, changed or ended: the virtual twin runs `what_if` (see `TwinSession`), or ends."""
    inspectorChanged = pyqtSignal(arguments=[])
    barChanged = pyqtSignal(arguments=[])
    scrollRequested = pyqtSignal(int, arguments=["slot"])
    """The card of a slot should be in view (a strip of the drawing was clicked)."""
    focusRequested = pyqtSignal(int, arguments=["slot"])
    """The list of the card of a slot gets the keyboard focus."""
    shownEdit = pyqtSignal(arguments=[])
    focusShows = pyqtSignal(arguments=[])
    """The field Shows of the inspector should get the focus (F2) and select its text."""

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.live = Live()
        extra = app.deps.extra.get("slots_live")
        if isinstance(extra, Live):
            self.live = extra
        self.editor = app.editor
        self._slot = 0
        self._candidate: int | None = None
        self._end = False
        self._focused = 0
        self.shown_live: object = None
        self._note = ""
        self._cards = [SlotCard(number, self) for number in range(1, protocol.STRIPS + 1)]
        self._states = KeyedListModel(self)
        self._groups = [WhatIfGroup(title, self) for title in GROUPS]
        self._crumbs = KeyedListModel(self)
        self._why = KeyedListModel(self)
        self._overview = KeyedListModel(self)
        self._place: Form | None = None
        self._controls = SlotControls(self.editor, lambda: forms_of(app), self)
        self._inspector: dict[str, Any] = {}
        self._simulate_state: tuple[bool, str] = (False, "")
        self._actions: dict[str, Callable[[], None]] = {}
        self.place_origin: Origin | None = None
        self.editor.changed.connect(self._changed)
        self._show()

    # -- what QML reads -------------------------------------------------------------------------------------------

    @pyqtProperty(int, notify=slotChanged)
    def slot(self) -> int:  # pyright: ignore[reportIncompatibleMethodOverride]
        """The slot picked (1..8), 0 for none: the drawing of the device marks its strip."""
        return self._slot

    @pyqtProperty(int, notify=candidateChanged)
    def candidate(self) -> int:  # pyright: ignore[reportRedeclaration]
        """The candidate picked of the slot, -1 for none."""
        return -1 if self._candidate is None else self._candidate

    @pyqtProperty(bool, notify=candidateChanged)
    def end(self) -> bool:  # pyright: ignore[reportRedeclaration]
        """The row that is no candidate is picked: the dark end of the rail, or `auto` of an empty slot."""
        return self._end

    @pyqtProperty("QVariantList", constant=True)
    def cards(self) -> list[SlotCard]:  # pyright: ignore[reportRedeclaration]
        return list(self._cards)

    @pyqtProperty(QObject, constant=True)
    def stateButtons(self) -> KeyedListModel:  # pyright: ignore[reportRedeclaration]
        return self._states

    @pyqtProperty("QVariantList", constant=True)
    def whatIfGroups(self) -> list[WhatIfGroup]:  # pyright: ignore[reportRedeclaration]
        return list(self._groups)

    @pyqtProperty(QObject, constant=True)
    def crumbs(self) -> KeyedListModel:  # pyright: ignore[reportRedeclaration]
        return self._crumbs

    @pyqtProperty(QObject, constant=True)
    def whySteps(self) -> KeyedListModel:  # pyright: ignore[reportRedeclaration]
        return self._why

    @pyqtProperty(QObject, constant=True)
    def overview(self) -> KeyedListModel:  # pyright: ignore[reportRedeclaration]
        return self._overview

    @pyqtProperty(QObject, constant=True)
    def controls(self) -> SlotControls:  # pyright: ignore[reportRedeclaration]
        return self._controls

    @pyqtProperty("QVariantMap", notify=inspectorChanged)
    def inspector(self) -> dict[str, Any]:  # pyright: ignore[reportRedeclaration]
        """What the inspector shows: see `_show_inspector`."""
        return self._inspector

    @pyqtProperty(bool, notify=simulatedChanged)
    def simulating(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self.what_if is not None

    @pyqtProperty(bool, notify=barChanged)
    def simulateEnabled(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self._simulate_state[0]

    @pyqtProperty(str, notify=barChanged)
    def simulateTip(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._simulate_state[1]

    @pyqtProperty(str, notify=barChanged)
    def deviceNote(self) -> str:  # pyright: ignore[reportRedeclaration]
        """Where Simulate shows (the place of the preview), beside the what-ifs."""
        return self._note

    @pyqtProperty(str, constant=True)
    def entries(self) -> str:  # pyright: ignore[reportRedeclaration]
        """What the list of the page holds, for the Edit menu."""
        return "candidates"

    # -- the document ---------------------------------------------------------------------------------------------

    def _changed(self, change: Change) -> None:
        """The document changed: shows what it touches, as the widgets do."""
        if change.scope is Scope.VALUE and change.path[:1] in (("slots",), ("controls",)):
            # an option of the place or of the controls, from a row of the inspector: it shows it already
            self._show_cards()
            self._show_problems()
        else:
            self._show()

    def _show(self) -> None:
        config = self.editor.validation.config
        if self.what_if is not None and config is None:
            self.simulate(None)
        self._show_simulate_button()
        self._show_state_bar()
        self._show_cards()
        self._show_inspector()

    @property
    def values(self) -> dict[str, Any]:
        return self.editor.document.values

    def shown_slots(self, snapshot: Snapshot | None = None) -> SlotsState | None:
        """What the cards show: the slots of what the drawing shows, the twin's or the device's."""
        snapshot = snapshot if snapshot is not None else self.live.snapshot()
        if self.live.shows_twin():
            return self.live.twin_slots()
        return snapshot.slots if snapshot is not None else None

    def _views(self) -> dict[int, SlotView]:
        slots = self.shown_slots()
        return {view.slot: view for view in slots.slots} if slots is not None else {}

    def _dark(self, slot: int) -> bool:
        """Whether the strip of `slot` is dark: none of its candidates has anything to show (as the daemon tells)."""
        view = self._views().get(slot)
        return view is not None and (view.candidate is None or (view.pool is not None and view.member is None))

    # -- the bar --------------------------------------------------------------------------------------------------

    def _show_simulate_button(self) -> None:
        """Simulate needs a file without problems and a daemon with a twin for it; the button says what is missing."""
        config = self.editor.validation.config
        reason = self.live.simulate_unavailable()
        if config is None:
            tip = "Only for a file without problems"
        elif reason is not None:
            tip = f"{reason.why}\n\n{SIMULATE_TIP}"
        else:
            tip = SIMULATE_TIP
        state = ((config is not None and reason is None) or self.what_if is not None, tip)
        if state != self._simulate_state:
            self._simulate_state = state
            self.barChanged.emit()

    def _show_state_bar(self) -> None:
        self.shown_live = None
        self.show_live(self.live.snapshot())

    def show_place(self, note: str) -> None:
        """Where Simulate shows (the place of the preview): the note in its bar."""
        if note != self._note:
            # the twin's slots instead of the device's, or back
            self.shown_live = None
            self._note = note
            self.barChanged.emit()

    def show_live(self, snapshot: Snapshot | None) -> None:
        """
        The states in the bar (the device's: the bar picks its mode and overrides), and the dot on the candidates the
        drawing shows (the device's, or the preview's), when they changed.
        """
        sounding().show(snapshot.sounding if snapshot is not None else ())
        self._show_simulate_button()
        slots = self.shown_slots(snapshot)
        real = snapshot.slots if snapshot is not None else None
        live = (
            (*((state.name, state.value, state.override) for state in real.states), real.mode_pick)
            if real is not None
            else None,
            tuple(view.candidate for view in slots.slots) if slots is not None else None,
        )
        if live == self.shown_live:
            return
        self.shown_live = live
        self._states.show(state_rows(self.editor.document, real))
        self._show_cards()
        self._show_why()
        if self._slot == 0:
            self._show_overview()
        else:
            # the dot on the candidate shown, and the end of the rail while the strip is dark
            stack = rows(self.values, self._slot)
            self._show_crumbs(stack)
            self._show_hint(stack)

    # -- the cards ------------------------------------------------------------------------------------------------

    def _end_row(self, slot: int) -> int:
        """The row of a card that is no candidate (the dark end, or `auto` of an empty slot), -1 for none."""
        count = len(rows(self.values, slot))
        return count if ends_dark(rows(self.values, slot)) or not count else -1

    def _show_cards(self) -> None:
        live = self._views()
        audio = self.live.audio()
        for slot, card in enumerate(self._cards, start=1):
            view = live.get(slot)
            candidates = rows(self.values, slot)
            shown_candidate = view.candidate if view is not None else None
            member = member_summary(view, audio, self.shown_slots())
            # a pool with nothing to hand out (or no candidate at all): none of them shows, the strip is dark
            dark = self._dark(slot)
            if dark:
                shown_candidate = None
            reached = len(candidates) if dark else shown_candidate
            why = reasons(candidates, reached, view.why if view is not None else (), self.values)
            card.model.show(card_rows(candidates, shown_candidate, why, self.values, dark, member))
            end_row = self._end_row(slot)
            current = -1
            if slot == self._slot and self._candidate is not None and self._candidate < len(candidates):
                current = self._candidate
            elif slot == self._slot and self._end:
                # gone only with the candidates that make it (see `ends_dark`)
                self._end = end_row >= 0
                current = end_row
            problems = self.editor.validation.at("slots", str(slot)) + self.editor.validation.at("controls", str(slot))
            card.show(current, slot == self._slot, "\n".join(str(problem) for problem in problems), len(candidates))

    # -- the inspector --------------------------------------------------------------------------------------------

    def _show_inspector(self) -> None:
        self._show_problems_of_controls()
        if self._slot == 0:
            self._show_overview()
            self._clear_place_form()
            self._set_inspector({"mode": "overview"})
            return
        stack = rows(self.values, self._slot)
        if self._candidate is not None and self._candidate >= len(stack):
            self._candidate = len(stack) - 1 if stack else None
        self._controls.show_slot(self._slot)
        self._show_crumbs(stack)
        self.place_origin = None
        info: dict[str, Any] = {
            "mode": "slot",
            "title": f"Slot {self._slot}",
            "hasCandidate": self._candidate is not None,
            "place": {},
            **self._why_info(),
            **self._hint_info(stack),
        }
        if self._candidate is not None:
            info.update(self._candidate_info(stack[self._candidate]))
        self._show_place_form(info["place"])
        info["problem"] = self._problem_text(info["place"])
        self._set_inspector(info)

    def _candidate_info(self, candidate: Row) -> dict[str, Any]:
        values = self.values
        groups: list[dict[str, Any]] = []
        for title, names in choice_groups(values):
            if title and names:
                groups.append({"text": title, "header": True})
            groups.extend({"text": name, "header": False} for name in names)
        channel = self.editor.document.get(("channel", candidate.show))
        if isinstance(channel, dict):
            kind = CHANNEL_TYPES.get(str(channel.get("type")))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            elsewhere = [use for use in uses(values, candidate.show) if use != f"slot {self._slot}"]
            text = (
                f"Channel {candidate.show} ({kind.title if kind else '?'}). "
                + (f"Also used in: {', '.join(elsewhere)}." if elsewhere else "Used nowhere else.")
                + self._channel_why(candidate.show)
            )
            strip = kind.strip if kind else None
        else:
            text = (
                "Nothing: the strip is dark."
                if candidate.show == EMPTY
                else pool_text(values, candidate.show) + self._channel_why(candidate.show)
            )
            strip = pool_strip(candidate.show, values)
        place = origin(values, candidate.show)
        self.place_origin = place
        info: dict[str, Any] = {
            "shows": candidate.show,
            "when": candidate.when,
            "showChoices": groups,
            "showHelp": _link(SHOWS_HELP, "slots"),
            "whenHelp": _link(WHEN_HELP, "conditions"),
            "channel": _help(text),
            "conditionStates": [*values.get("state", {}), DEFAULT],
            "conditionTargets": targets(values),
        }
        if place is not None:
            own = pool_kind(values, candidate.show) == "apps" and candidate.show not in BUILT_IN
            # the channels of a pool of channels bring their own look: its place has none
            form = strip is not None and place.source is not Source.CHANNELS
            info["place"] = {
                "title": f"Look in slot {self._slot}",
                "parts": _link(place.parts, "slots"),
                "button": "Edit the channel" if place.source is Source.CHANNEL else "Edit the pool",
                "form": form,
                "strip": strip or "",
                "allowed": sorted(place_options(candidate.show, values)),
                "pick": not own,
                "key": f"{strip}:{int(not own)}:{','.join(sorted(place_options(candidate.show, values)))}",
            }
        return info

    def _channel_why(self, name: str) -> str:
        slots = self.shown_slots()
        if slots is None:
            return ""
        # the sentence before it names the channel or pool already, the box says whether it is now or what if
        now = where(slots, name)
        return f"\n{now[:1].upper()}{now[1:]}."

    def _set_inspector(self, info: dict[str, Any]) -> None:
        if info != self._inspector:
            self._inspector = info
            self.inspectorChanged.emit()

    def _show_why(self) -> None:
        if self._slot:
            self._set_inspector({**self._inspector, **self._why_info()})

    def _why_info(self) -> dict[str, Any]:
        """Why the slot shows what it shows, a step a line (`xtouch-daemon why <slot>`); only with a daemon."""
        live = self.shown_slots()
        view = self._views().get(self._slot) if live is not None else None
        steps = why_steps(view.why) if view is not None else ()
        heading = "What if" if self.what_if is not None else "Preview" if self.live.shows_twin() else "Now"
        self._why.show(why_rows(steps))
        return {
            "whyLive": live is not None,
            "whyHeading": heading,
            "whyEmpty": f"The daemon tells nothing about slot {self._slot}." if not steps else "",
            "whyTone": why_tone(steps).value,
        }

    def _show_crumbs(self, stack: list[Row]) -> None:
        """`Slot 3 › 1 games › 2 apps › dark`: the candidates in order, the one picked checked, the one shown dotted."""
        view = self._views().get(self._slot)
        shown = view.candidate if view is not None else None
        # the candidate it came to, which has nothing for it: the strip is dark
        dark = view is not None and view.pool is not None and view.member is None
        self._crumbs.show(
            crumb_rows(stack, self._candidate, shown, dark, self._end, self._dark(self._slot), ends_dark(stack))
        )

    def _show_hint(self, stack: list[Row]) -> None:
        self._set_inspector({**self._inspector, **self._hint_info(stack)})

    def _hint_info(self, stack: list[Row]) -> dict[str, Any]:
        text = hint_text(self._slot, stack, self._candidate, self._end, self._dark(self._slot))
        return {"hint": _help(text)}

    def _show_overview(self) -> None:
        """A line for each slot: what it shows now (while the daemon tells it), its candidates and its problems."""
        live = self.shown_slots()
        views = self._views()
        lines: list[tuple[str, dict[str, Any]]] = []
        for slot in range(1, protocol.STRIPS + 1):
            problems = len(
                self.editor.validation.at("slots", str(slot)) + self.editor.validation.at("controls", str(slot))
            )
            view = views.get(slot) if live is not None else None
            steps = why_steps(view.why) if view is not None else ()
            lines.append(overview_row(slot, len(rows(self.values, slot)), problems, steps))
        self._overview.show(lines)

    def _problem_text(self, place: dict[str, Any]) -> str:
        """The problems that belong to no option row of the place (those show on their rows)."""
        validation = self.editor.validation
        if self._slot == 0:
            return ""
        if self._candidate is None:
            return "\n".join(str(problem) for problem in validation.at("slots", str(self._slot)))
        here = validation.at("slots", str(self._slot), self._candidate)
        names = set(place.get("allowed", [])) if place.get("form") else set()
        return "\n".join(problem.message for problem in here if problem.path[3:4] not in [(name,) for name in names])

    def _show_problems(self) -> None:
        self.show_problems(self.editor.validation)

    def _show_problems_of_controls(self) -> None:
        if self._slot:
            self._controls.show_problems(self.editor.validation)

    def show_problems(self, validation: Validation) -> None:
        """The problems of the document, on the cards, in the inspector and in the controls."""
        self._controls.show_problems(validation)
        if self._slot == 0:
            self._show_overview()
            return
        problem = self._problem_text(self._inspector.get("place") or {})
        if problem != self._inspector.get("problem", ""):
            self._set_inspector({**self._inspector, "problem": problem})

    # -- picking --------------------------------------------------------------------------------------------------

    def _pick(self, slot: int, candidate: int | None, end: bool = False) -> None:
        was = (self._slot, self._candidate, self._end)
        self._slot, self._candidate, self._end = slot, candidate, end
        self._show_cards()
        self._show_inspector()
        self._announce(was)

    def _announce(self, was: tuple[int, int | None, bool] | None) -> None:
        if was is None or was[0] != self._slot:
            self.slotChanged.emit()
        if was is None or was[1:] != (self._candidate, self._end):
            self.candidateChanged.emit()

    @pyqtSlot(int)
    def selectSlot(self, slot: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """
        A strip of the drawing was clicked: its card, with the candidate the device shows, or the end of the rail
        while the strip is dark. 0 picks nothing.
        """
        if not 1 <= slot <= protocol.STRIPS:
            self.unpick()
            return
        view = self._views().get(slot)
        count = len(rows(self.values, slot))
        candidate = view.candidate if view is not None and view.candidate is not None else 0 if count else None
        # the end of the rail while the strip is dark: it shows that
        end = self._dark(slot) and self._end_row(slot) >= 0
        self._pick(slot, None if end else candidate, end)
        # the focus stays where it is (on the drawing, whose arrow keys pick the next strip)
        self.scrollRequested.emit(slot)

    @pyqtSlot(int, int)
    def pickRow(self, slot: int, row: int) -> None:
        """A row of a card was clicked, or reached with the keys: a candidate, or the row that is none."""
        if not 1 <= slot <= protocol.STRIPS or row < 0:
            return
        count = len(rows(self.values, slot))
        end = row >= count
        if end and self._end_row(slot) < 0:
            return
        self._pick(slot, None if end else row, end)

    @pyqtSlot(int)
    def pickSlot(self, slot: int) -> None:
        """The card of a slot was clicked beside its candidates: the slot alone, with no candidate."""
        self._pick(slot, None)
        self.focusRequested.emit(slot)

    @pyqtSlot()
    def unpick(self) -> None:
        """Nothing picked: no card is outlined, none has a row highlighted, the overview shows."""
        self._pick(0, None)

    @pyqtSlot(int)
    def pickCrumb(self, row: int) -> None:
        """A crumb picks its row of the card; the one picked, clicked again, picks the slot alone."""
        if self._slot == 0:
            return
        if self._crumbs.rows and 0 <= row < len(self._crumbs.rows) and self._crumbs.rows[row][1]["checked"]:
            self.pickSlot(self._slot)
        else:
            self.pickRow(self._slot, row)

    # -- editing --------------------------------------------------------------------------------------------------

    def _put(self, slot: int, stack: list[Row]) -> None:
        value = stack_value(stack)
        if value is None:
            self.editor.document.unset(("slots", str(slot)))
        else:
            self.editor.document.set(("slots", str(slot)), value)

    def _write(self, slot: int, stack: list[Row], candidate: int | None) -> None:
        self._put(slot, stack)
        was = (self._slot, self._candidate, self._end)
        self._slot, self._candidate, self._end = slot, candidate, False
        self.editor.edited(Change(Scope.SLOTS, ("slots", str(slot))))
        self._announce(was)

    @pyqtSlot(int)
    def add(self, slot: int) -> None:
        """A new candidate at the end of the stack: `auto` (Ctrl+Up moves it up)."""
        stack = rows(self.values, slot)
        stack.append(Row(AUTO))
        self._write(slot, stack, len(stack) - 1)

    @pyqtSlot(int)
    def remove(self, slot: int) -> None:
        """Removes the candidate picked in the slot (the last one when none is)."""
        stack = rows(self.values, slot)
        if not stack:
            return
        index = self._candidate if slot == self._slot and self._candidate is not None else len(stack) - 1
        del stack[index]
        self._write(slot, stack, min(index, len(stack) - 1) if stack else None)

    @pyqtSlot(int, int, int)
    def reorder(self, slot: int, source: int, target: int) -> None:
        """Moves the candidate `source` of a slot to `target` (dragged, or with Ctrl+Up/Down); it stays picked."""
        stack = rows(self.values, slot)
        if source == target or not (0 <= source < len(stack) and 0 <= target < len(stack)):
            return
        stack.insert(target, stack.pop(source))
        # the rows of the card move (they slide), then the rest of the document is shown
        self._cards[slot - 1].model.move(source, target)
        self._write(slot, stack, target)

    @pyqtSlot(int, int)
    def moveCandidate(self, slot: int, step: int) -> None:
        """Ctrl+Up/Down: the candidate picked one place up (-1) or down (1); the end of the rail stays."""
        if slot == self._slot and self._candidate is not None and not self._end:
            self.reorder(slot, self._candidate, self._candidate + step)

    def _insert(self, slot: int, candidates: list[Row]) -> int:
        """Puts candidates after the one picked in the slot (at the end when none is), picks the first; how many."""
        if not candidates:
            return 0
        stack = rows(self.values, slot)
        index = self._candidate + 1 if slot == self._slot and self._candidate is not None else len(stack)
        stack[index:index] = candidates
        self._write(slot, stack, index)
        return len(candidates)

    @pyqtSlot(str)
    def setShows(self, text: str) -> None:
        """What the candidate picked shows (from the field Shows)."""
        if self._candidate is None:
            return
        candidate = rows(self.values, self._slot)[self._candidate]
        show = text.strip()
        if show and show != candidate.show:
            self._replace(Row(show, candidate.when, candidate.options))

    @pyqtSlot(str)
    def setWhen(self, text: str) -> None:
        """The condition of the candidate picked (from the field When)."""
        if self._candidate is None:
            return
        candidate = rows(self.values, self._slot)[self._candidate]
        when = text.strip()
        if when != candidate.when:
            self._replace(Row(candidate.show, when, candidate.options))

    def _replace(self, candidate: Row) -> None:
        assert self._candidate is not None
        stack = rows(self.values, self._slot)
        # options that the new place does not take go
        allowed = place_options(candidate.show, self.values)
        stack[self._candidate] = Row(
            candidate.show, candidate.when, {key: value for key, value in candidate.options.items() if key in allowed}
        )
        self._write(self._slot, stack, self._candidate)

    # -- the place of the candidate: the option rows of its form ------------------------------------------------------

    @pyqtProperty(QObject, constant=True)
    def placeForm(self) -> Form:  # pyright: ignore[reportRedeclaration]
        """The option rows of the place of the candidate picked ("Look in slot N")."""
        return self._place_form()

    def _place_form(self) -> Form:
        """The form of the place, made when it is first needed (the context of the forms is made after the pages)."""
        if self._place is None:
            self._place = Form(forms_of(self.app))
        return self._place

    def _place_option(self, name: str) -> Any:
        """An option of the place of the candidate picked (None for none)."""
        if self._candidate is None:
            return None
        stack = rows(self.values, self._slot)
        return stack[self._candidate].options.get(name) if self._candidate < len(stack) else None

    def _set_place_option(self, name: str, value: Any) -> None:
        """Sets an option of the place of the candidate picked (None removes it); the form edits through this."""
        if self._candidate is None:
            return
        stack = rows(self.values, self._slot)
        candidate = stack[self._candidate]
        options = {key: each for key, each in candidate.options.items() if key != name}
        if value is not None:
            options[name] = value
        stack[self._candidate] = Row(candidate.show, candidate.when, options)
        self._put(self._slot, stack)

    def _clear_place_form(self) -> None:
        if self._place is not None:
            self._place.set_specs([])

    def _show_place_form(self, place: dict[str, Any]) -> None:
        """The rows of the place of the candidate picked: they change in place while it is the same kind of place."""
        origin = self.place_origin
        if origin is None or self._candidate is None or not place.get("form"):
            self._clear_place_form()
            return
        form = self._place_form()
        form.strip = place["strip"]
        form.base = ("slots", str(self._slot), self._candidate)
        form.set_specs(
            place_specs(
                origin,
                self._slot,
                place["strip"],
                frozenset(place["allowed"]),
                place["pick"],
                self._place_option,
                self._set_place_option,
                lambda: modes_and_states(self.values),
            )
        )

    @pyqtSlot()
    def editOrigin(self) -> None:
        """Opens the channel or the pool the candidate picked shows on the page Channels."""
        place = self.place_origin
        if place is None:
            return
        opener = self.live.show_channel if place.source is Source.CHANNEL else self.live.show_pool
        if opener is not None:
            opener(place.show)
        self.app.showPage("channels")

    # -- the Edit menu --------------------------------------------------------------------------------------------

    @pyqtSlot(int, bool)
    def cardFocus(self, slot: int, focused: bool) -> None:
        """The list of a card got or lost the keyboard focus: the Edit menu works on its candidates."""
        focus = slot if focused else 0 if self._focused == slot else self._focused
        if focus != self._focused:
            self._focused = focus
            self.editableChanged.emit()

    def _focused_candidate(self) -> Row | None:
        """The candidate picked in the card that has the focus, None for none."""
        if self._focused == 0 or self._focused != self._slot or self._candidate is None:
            return None
        return rows(self.values, self._slot)[self._candidate]

    def editable_actions(self) -> list[str]:
        if self._focused == 0:
            return []
        actions = ["paste"]
        if self._focused_candidate() is not None:
            actions = ["cut", "copy", "paste", "duplicate", "remove", "rename"]
        return actions

    @pyqtSlot(str)
    def edit(self, action: str) -> None:
        candidate = self._focused_candidate()
        if action == "paste" and self._focused:
            text = QGuiApplication.clipboard().text()  # pyright: ignore[reportOptionalMemberAccess]
            self._insert(self._focused, parse_candidates(text))
        elif candidate is None:
            return
        elif action in ("copy", "cut"):
            QGuiApplication.clipboard().setText(candidates_text([candidate]))  # pyright: ignore[reportOptionalMemberAccess]
            if action == "cut":
                self.remove(self._slot)
        elif action == "duplicate":
            self._insert(self._slot, [candidate])
        elif action == "remove":
            self.remove(self._slot)
        elif action == "rename":
            # a candidate has no id: the focus goes to what it shows
            self.focusShows.emit()

    @pyqtSlot("QVariantList")
    def reveal(self, path: list[str]) -> None:
        """Shows the option at `path` of the document: picks its slot (and candidate) of `slots` and `controls`."""
        if len(path) >= 2 and path[0] in ("slots", "controls") and path[1].isdigit():
            slot = int(path[1])
            if 1 <= slot <= protocol.STRIPS:
                if path[0] == "slots" and len(path) >= 3 and path[2].isdigit():
                    self.pickRow(slot, int(path[2]))
                else:
                    self.pickSlot(slot)
                self.scrollRequested.emit(slot)

    # -- simulate -------------------------------------------------------------------------------------------------

    def _now(self) -> WhatIf:
        """Reality as a what-if, as the daemon tells it: where Simulate starts."""
        snapshot = self.live.snapshot()
        return WhatIf.of_live(snapshot.slots if snapshot is not None else None)

    @pyqtSlot(bool)
    def toggleSimulate(self, on: bool) -> None:
        """The button Simulate was clicked."""
        self.simulate(self._now() if on else None)

    def simulate(self, what_if: WhatIf | None) -> None:
        """Shows what the slots would show in `what_if`; None goes back to what the daemon tells."""
        config = self.editor.validation.config
        if config is None or (what_if is not None and self.live.simulate_unavailable() is not None):
            what_if = None
        if what_if is None or self.what_if is None:
            # where it starts: reality, as the daemon tells it when it opens
            self.what_if_start = self._now() if what_if is not None else None
        was = self.what_if is not None
        self.what_if = what_if
        if config is not None and what_if is not None:
            inputs = Inputs.of(config.slots)
            groups = what_if_rows(inputs, what_if, self.what_if_start or WhatIf())
            for group in self._groups:
                group.show(groups[group.title])
        if was != (what_if is not None):
            self.simulatedChanged.emit()
        self.shown_live = None
        self._show_simulate_button()
        self.show_live(self.live.snapshot())
        self.simulated.emit()

    @pyqtSlot(str, bool)
    def whatIfToggle(self, name: str, flip: bool) -> None:
        if self.what_if is not None:
            self.simulate(self.what_if.toggled(name, flip))

    @pyqtSlot(str)
    def whatIfMode(self, mode: str) -> None:
        if self.what_if is not None and mode != self.what_if.mode:
            self.simulate(with_mode(self.what_if, mode))

    @pyqtSlot(str, int)
    def whatIfCount(self, name: str, value: int) -> None:
        if self.what_if is not None:
            self.simulate(counted(self.what_if, name, value))

    # -- the states of the bar ------------------------------------------------------------------------------------

    @pyqtSlot(str, result="QVariantMap")
    def stateInfo(self, name: str) -> dict[str, Any]:
        """
        What the popover of a state says: the state as the daemon tells it, its override (real: the device and Home
        Assistant follow it) and what the slots would show with it the other way (Simulate: nothing changes).
        """
        snapshot = self.live.snapshot()
        slots = snapshot.slots if snapshot is not None else None
        state = next((state for state in slots.states if state.name == name), None) if slots is not None else None
        self._actions = {}
        if slots is None or state is None:
            return {"name": name, "unknown": True, "entries": []}
        why = state.source or "none of its sources is on"
        entries: list[dict[str, Any]] = [
            {
                "title": "",
                "status": "on" if state.value else "off",
                "tone": "good" if state.value else "neutral",
                "text": rich(f"{why[:1].upper()}{why[1:]}."),
                "actions": [],
            }
        ]
        if state.mode:
            picked = slots.mode_pick == name
            actions: list[dict[str, str]] = []
            if picked:
                actions.append({"id": "back", "text": "Back to the rules"})
                self._actions["back"] = lambda: self.override(name, "auto")
            if slots.mode != name:
                actions.append({"id": "pick", "text": f"Pick {name}"})
                self._actions["pick"] = lambda: self.override(name, "on")
            entries.append(
                {
                    "title": "Override",
                    "status": "picked by hand" if picked else "by the rules",
                    "tone": "warn" if picked else "neutral",
                    "text": rich(
                        "Real: the device and Home Assistant follow a mode picked by hand "
                        "until the rules want another one."
                    ),
                    "actions": actions,
                }
            )
        else:
            actions = []
            for choice in OVERRIDES:
                if choice != state.override:
                    key = f"override:{choice}"
                    actions.append({"id": key, "text": f"Override: {choice}" if choice != "auto" else "Back to auto"})
                    self._actions[key] = lambda choice=choice: self.override(name, choice)
            entries.append(
                {
                    "title": "Override",
                    "status": state.override,
                    "tone": "neutral" if state.override == "auto" else "warn",
                    "text": rich("Real: the device and Home Assistant follow an override until it is back on `auto`."),
                    "actions": actions,
                }
            )
        what_if = WhatIf.of_live(slots)
        if state.mode:
            mode = DEFAULT if slots.mode == name else name
            what_if = dataclasses.replace(what_if, mode=mode)
            simulate = "Simulate no mode" if mode == DEFAULT else f"Simulate {name} as the mode"
        else:
            what_if = what_if.toggled(name, flip=False)
            simulate = f"Simulate it {'off' if state.value else 'on'}"
        self._actions["simulate"] = lambda: self.simulate(what_if)
        entries.append(
            {
                "title": "Simulate",
                "status": "",
                "tone": "neutral",
                "text": "What the slots would show with it the other way, without changing anything.",
                "actions": [{"id": "simulate", "text": simulate}],
            }
        )
        return {"name": name, "unknown": False, "entries": entries}

    @pyqtSlot(str)
    def stateAction(self, action: str) -> None:
        """An action of the popover of a state (of `stateInfo`)."""
        found = self._actions.get(action)
        if found is not None:
            found()

    def override(self, name: str, value: str) -> None:
        """Asks the daemon to override a state, or to pick a mode (`auto`: the rules decide again)."""
        if self.editor.document.get(("state", name, "mode")):
            self.live.request(SetMode(name if value == "on" else "auto"))
        else:
            self.live.request(SetOverride(name, value))


_link = link
