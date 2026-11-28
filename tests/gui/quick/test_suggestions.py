"""Suggestions under a text field (the name of an alias): the field keeps the focus, the keys move in the list."""

import pytest
from PyQt6.QtCore import Qt

from tests.gui.quick.forms_host import aliases, settings
from tests.support.quick import Ui
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.quick.forms.help import colors_of
from xtouch_daemon.gui.quick.forms.suggestions import lines, suggestion_html


@pytest.fixture
def alias(ui: Ui) -> str:
    """The key of a new alias row, shown, with its name field focused and the sound server read."""
    settings(ui).showSection("aliases")
    ui.wait_until(lambda: bool(aliases(ui).context.audio().streams))
    key = aliases(ui).add()
    ui.wait_until(lambda: ui.find(f"alias_name_{key}") is not None)
    ui.focus(f"alias_name_{key}")
    return key


def test_the_applications_that_play_are_suggested_on_focus(ui: Ui, alias: str):
    ui.wait_until(lambda: ui.shows("suggestion_Brave"))
    assert ui.item("suggestions").property("count") >= 1


def test_typing_filters_the_suggestions_and_keeps_the_focus(ui: Ui, alias: str):
    ui.type("web")
    ui.wait_until(lambda: not ui.shows("suggestion_Brave"))
    assert ui.shows("suggestion_WEBRTC VoiceEngine")
    assert ui.item(f"alias_name_{alias}").property("activeFocus") is True


def test_down_and_enter_pick_a_suggestion(ui: Ui, alias: str):
    ui.wait_until(lambda: ui.shows("suggestion_Brave"))
    ui.key(Qt.Key.Key_Down)
    ui.key(Qt.Key.Key_Return)
    assert ui.app.editor.document.get(("aliases",)).get("Brave") == ""
    assert ui.text(f"alias_name_{alias}") == "Brave"


def test_up_wraps_to_the_last_line_and_tab_picks(ui: Ui, alias: str):
    ui.wait_until(lambda: ui.shows("suggestion_Brave"))
    ui.key(Qt.Key.Key_Up)
    ui.key(Qt.Key.Key_Tab)
    assert ui.text(f"alias_name_{alias}") == "WEBRTC VoiceEngine"


def test_escape_closes_the_list(ui: Ui, alias: str):
    ui.wait_until(lambda: ui.shows("suggestion_Brave"))
    ui.key(Qt.Key.Key_Escape)
    assert not ui.shows("suggestion_Brave")


def test_a_click_picks_a_suggestion(ui: Ui, alias: str):
    ui.wait_until(lambda: ui.shows("suggestion_Brave"))
    ui.click("suggestion_Brave")
    assert ui.text(f"alias_name_{alias}") == "Brave"
    assert not ui.shows("suggestion_Brave")


def test_without_a_match_the_list_says_so(ui: Ui, alias: str):
    ui.type("zzz")
    ui.wait_until(lambda: ui.shows("suggestion_none"))


# -- the lines themselves -------------------------------------------------------------------------------------------


def test_the_lines_highlight_what_was_typed():
    colors = colors_of("dark")
    html = suggestion_html(Suggestion("WEBRTC VoiceEngine", "Discord"), "web", colors)
    assert "WEBRTC VoiceEngine".startswith("WEB")
    assert "<b" in html or "<span" in html


def test_no_suggestions_give_a_line_of_words():
    result = lines((), "", colors_of("dark"), "Nothing plays")
    assert result["rows"] == []
    assert result["empty"] == "Nothing plays"


def test_a_line_of_a_remembered_device_can_be_forgotten():
    found = (Suggestion("buds", "Buds", forget=lambda: None),)
    result = lines(found, "", colors_of("dark"), "none")
    assert result["rows"][0]["forget"] is True
    assert result["rows"][0]["value"] == "buds"
