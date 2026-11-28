"""The page States in Qt Quick: the list, add, duplicate, rename, remove, sources or a condition, the history."""

from typing import Any

from PyQt6.QtCore import Qt

from tests.gui.quick.conftest import MakeUi
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.pages.states import StatesPage


def page(ui: Ui) -> StatesPage:
    """The backend of the page States, shown."""
    ui.app.showPage("states")
    ui.settle()
    states = ui.app.states
    assert isinstance(states, StatesPage)
    return states


def listed(states: StatesPage) -> list[dict[str, Any]]:
    return [dict(values) for _, values in states.entries.rows]  # pyright: ignore[reportAttributeAccessIssue]


def test_the_list_shows_the_states_and_picks_the_first(ui: Ui):
    states = page(ui)
    assert [row["name"] for row in listed(states)] == ["call"]
    assert states.selection == "call"
    assert ui.shows("state_title")
    assert not ui.shows("states_empty")


def test_a_click_picks_a_state(ui: Ui):
    states = page(ui)
    states.add("kind:mode")
    assert states.selection != "call"
    ui.click("entry_call")
    assert states.selection == "call"


def test_add_makes_a_state_a_mode_or_a_usual_one(ui: Ui):
    states = page(ui)
    ui.click("entry_add")
    ui.click("menu_kind:mode")
    assert states.selection is not None
    assert ui.app.editor.document.get(("state", states.selection, "mode")) is True
    ui.click("entry_add")
    ui.click("menu_template:gaming")
    assert states.selection == "gaming"
    assert "gaming" in states.states


def test_duplicate_and_remove(ui: Ui):
    states = page(ui)
    ui.click("entry_duplicate")
    assert len(listed(states)) == 2
    assert states.selection != "call"
    ui.click("entry_remove")
    assert [row["name"] for row in listed(states)] == ["call"]


def test_the_last_state_removed_says_how_to_start(ui: Ui):
    states = page(ui)
    ui.click("entry_remove")
    assert listed(states) == []
    assert ui.shows("states_empty")


def test_an_id_that_is_taken_is_a_problem_and_a_new_one_renames(ui: Ui):
    states = page(ui)
    states.add("kind:state")
    other = states.selection
    assert other is not None
    assert states.rename("call") is False
    assert states.idProblem
    assert states.rename("night") is True
    assert states.idProblem == ""
    assert states.selection == "night"
    assert other not in states.states


def test_sources_show_and_a_source_is_added_from_the_menu(ui: Ui):
    states = page(ui)
    assert ui.shows("sources_hint")
    ui.click("add_source")
    ui.click("menu_apps")
    assert "apps" in states.added


def test_switching_to_a_condition_asks_before_it_removes_the_sources(ui: Ui):
    states = page(ui)
    document = ui.app.editor.document
    ui.click("on_while_condition")
    assert ui.shows("switch_confirm")
    assert "voice chat" in plain_text(ui, "switch_text")
    # nothing changed yet
    assert document.get(("state", "call", "voice_chat")) is True
    ui.click("switch_cancel")
    assert document.get(("state", "call", "voice_chat")) is True
    assert not states.inspector["composed"]
    ui.click("on_while_condition")
    ui.click("switch_confirm")
    assert document.get(("state", "call", "voice_chat")) is None
    assert states.inspector["composed"]


def plain_text(ui: Ui, name: str) -> str:
    return str(ui.items(name)[0].property("text"))


def test_switching_back_to_sources_drops_the_condition(ui: Ui):
    states = page(ui)
    document = ui.app.editor.document
    ui.click("on_while_condition")
    ui.click("switch_confirm")
    # the condition is typed into the field, which has the focus after the switch
    ui.type("gaming")
    ui.key(Qt.Key.Key_Return)
    assert document.get(("state", "call", "when")) == "gaming"
    ui.click("on_while_sources")
    assert ui.shows("switch_confirm")
    ui.click("switch_confirm")
    assert document.get(("state", "call", "when")) is None
    assert not states.inspector["composed"]


def test_a_state_becomes_a_mode_and_back(ui: Ui):
    states = page(ui)
    document = ui.app.editor.document
    ui.click("kind_mode")
    assert document.get(("state", "call", "mode")) is True
    ui.click("kind_state")
    assert document.get(("state", "call", "mode")) is None
    assert states.selection == "call"


def test_without_a_daemon_the_list_has_no_dot(ui: Ui):
    states = page(ui)
    assert listed(states)[0]["dot"] is None


def test_the_empty_file_has_no_state_to_pick(make_ui: MakeUi, path: Any):
    path.write_text("[channel.out]\ntype = 'output'\n")
    ui = make_ui(path)
    states = page(ui)
    assert states.selection is None
    assert ui.shows("states_empty")
    assert ui.app.editor.document.get(("state",)) in (None, {})
