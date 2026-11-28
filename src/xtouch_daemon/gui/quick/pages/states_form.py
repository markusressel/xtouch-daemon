"""
The forms of the page States. A state has three groups of options that the page arranges between its own controls:
`label` and `priority` of a mode, its sources (shown only where set or just added, each with a button that removes
it), and the delays. Each group is a form of its own over the same state; `rule` says which of its rows show.
"""

from collections.abc import Callable, Mapping
from typing import Any

from PyQt6.QtCore import QObject

from xtouch_daemon.gui.domain import sources
from xtouch_daemon.gui.domain.schema import options
from xtouch_daemon.gui.quick.forms.context import FormContext
from xtouch_daemon.gui.quick.forms.form import Form, RowSpec
from xtouch_daemon.gui.quick.pages.states_data import DELAYS, MODE_ONLY, SOURCES
from xtouch_daemon.slots.model import StateConfig
from xtouch_daemon.slots.states import delay_off_for

Rule = Callable[[str], bool]
"""Whether the row of an option shows."""


class StateForm(Form):
    """A form of a group of the options of a state: `rule(name)` says which of its rows show now."""

    def __init__(self, context: FormContext, specs: list[RowSpec], rule: Rule, parent: QObject) -> None:
        self.rule = rule
        self.removing = {spec.name for spec in specs if spec.name in SOURCES}
        super().__init__(context, specs, base=("state", ""), parent=parent)

    def _state(self, spec: RowSpec, values: Mapping[str, Any], problems: list[Any]) -> dict[str, Any]:
        state = super()._state(spec, values, problems)
        state["visible"] = bool(state["visible"]) and self.rule(spec.name)
        if spec.name in self.removing:
            # a source goes with its button, also while it has no value yet
            state.update(resettable=True, resetTip="Remove this source", resetIcon="delete-outline")
        return state


def state_forms(
    context: FormContext, rule: Rule, where: Callable[[], tuple[str, ...]]
) -> tuple[StateForm, StateForm, StateForm]:
    """
    The forms of the mode (`label`, `priority`), of the sources and of the delays, for the state picked (`where()`
    is its place in the document: the page points the forms at it with `retarget`).
    """
    found = {option.name: option for option in options(StateConfig)}
    document = context.editor.document
    patterns = {
        "apps": lambda: sources.patterns(context.audio()),
        "recording": lambda: sources.patterns(context.audio()),
    }

    def delay_off() -> str:
        # by default as the kind of the state: a mode, a state with sources, or one with a condition
        state = document.get(where()) or {}
        return f"{delay_off_for(bool(state.get('mode')), state.get('when') is not None):g}"

    def spec(name: str) -> RowSpec:
        return RowSpec(found[name], suggest=patterns.get(name), placeholder=delay_off if name == "delay_off" else None)

    return (
        StateForm(context, [spec(name) for name in MODE_ONLY], rule, context),
        StateForm(context, [spec(name) for name in SOURCES], rule, context),
        StateForm(context, [spec(name) for name in DELAYS], rule, context),
    )
