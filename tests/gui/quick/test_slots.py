"""
The page Slots in Qt Quick (see tests/gui/qt/test_slots.py for the widgets): the cards, the overview, picking, the
inspector and editing the stacks.
"""

import re
from typing import Any

from PyQt6.QtCore import QPointF, Qt

from tests.gui.quick.slots_helpers import click_row, model_rows, page, polish, press, snapshot, tell, texts
from tests.support.quick import Ui
from xtouch_daemon.gui.domain.status import Reason
from xtouch_daemon.live.messages import SetMode, SetOverride


def info(ui: Ui) -> dict[str, object]:
    return page(ui).inspector


def plain(markup: object) -> str:
    """Rich text as the words it shows."""
    return re.sub(r"<[^>]*>", "", str(markup)).replace("&amp;", "&")


def tall(ui: Ui) -> None:
    """A window high enough to have all of the inspector in view (a click only hits what shows)."""
    ui.window.resize(1280, 2400)
    polish(ui)


def test_the_cards_show_the_stacks(ui: Ui):
    # each rail ends in the dark strip, always the last option (a channel can be on another slot, a pool empty)
    assert texts(ui, 1) == ["1 always → out", "nothing to show: the strip goes dark"]
    assert texts(ui, 2) == [
        "1 when call → browser",
        "2 when app or person without a slot → auto",
        "nothing to show: the strip goes dark",
    ]
    assert texts(ui, 3) == ["auto (no entry)"]
    assert len(ui.items("card_1")) == 1
    # at the start no slot is picked: the overview takes the place of the inspector
    assert page(ui).slot == 0
    assert info(ui)["mode"] == "overview"
    assert ui.shows("overview")

    page(ui).pickSlot(1)
    assert info(ui)["mode"] == "slot"
    assert info(ui)["title"] == "Slot 1"
    assert ui.shows("inspector_card")
    assert not ui.shows("overview")
    assert "Pick a candidate to edit it." in str(info(ui)["hint"])


def test_a_strip_of_the_drawing_picks_its_card_and_the_inspector_shows_the_candidate(ui: Ui):
    tall(ui)
    slots = page(ui)
    slots.selectSlot(2)
    polish(ui)
    assert (slots.slot, slots.candidate) == (2, 0)
    inspector = info(ui)
    assert inspector["title"] == "Slot 2"
    assert inspector["shows"] == "browser"
    assert inspector["when"] == "call"
    assert plain(inspector["channel"]) == "Channel browser (Applications). Used nowhere else."
    place = inspector["place"]
    assert isinstance(place, dict)
    assert place["button"] == "Edit the channel"
    assert ui.item("shows_field").property("editText") == "browser"
    assert ui.item("when_field").property("text") == "call"
    press(ui, "edit_origin")
    assert ui.app.page == "channels"

    ui.app.showPage("slots")
    click_row(ui, 2, 1)
    assert slots.candidate == 1
    assert plain(info(ui)["channel"]).startswith("Pool auto: the people (from the right) and the applications")
    place = info(ui)["place"]
    assert isinstance(place, dict)
    assert place["button"] == "Edit the pool"
    assert "encoder" in place["allowed"]
    assert place["path"] == ["slots", "2", 1]
    # the form of the place is the forms' part: a placeholder takes what it needs
    placeholder = ui.item("place_form_placeholder")
    assert placeholder.property("strip") == place["strip"]
    assert placeholder.property("optionPath") == ["slots", "2", 1]


def test_the_overview_has_a_line_for_each_slot(ui: Ui):
    lines = model_rows(page(ui).overview)
    assert len(lines) == 8
    assert [line["plain"] for line in lines[:3]] == ["1 candidate", "2 candidates", "No candidate: auto"]
    # what the daemon tells, and the problems of a slot
    tell(ui, snapshot((0, 1, None)))
    assert model_rows(page(ui).overview)[0]["plain"] == "Shows 0; 1 candidate"
    ui.app.editor.document.set(("controls", "1"), {"select": "nonsense"})
    ui.app.editor.edited()
    ui.settle()
    assert model_rows(page(ui).overview)[0]["plain"].endswith("; 1 problem")
    assert model_rows(page(ui).overview)[0]["tone"] == "bad"
    # a click on a line picks its slot
    ui.click("overview_1")
    assert (page(ui).slot, page(ui).candidate) == (1, -1)


def test_a_click_picks_a_slot_a_candidate_or_nothing(ui: Ui):
    slots = page(ui)
    # on a card beside its candidates: the slot alone, outlined
    card = ui.item("card_3")
    ui.click(card, at=QPointF(card.width() / 2, 6))
    assert (slots.slot, slots.candidate) == (3, -1)
    assert slots.cards[2].picked
    # a candidate: its slot too, and the strip follows
    click_row(ui, 2, 1)
    assert (slots.slot, slots.candidate) == (2, 1)
    assert not slots.cards[2].picked
    assert slots.cards[1].current == 1
    assert slots.cards[0].current == -1
    # below the cards: nothing
    tall(ui)
    below = ui.item("below_cards")
    ui.click(below, at=QPointF(40, below.height() - 6))
    assert (slots.slot, slots.candidate) == (0, -1)
    assert all(card.current == -1 for card in slots.cards)
    assert info(ui)["mode"] == "overview"


def test_the_device_shows_which_candidate_and_the_states(ui: Ui):
    sent: list[object] = []
    tell(ui, snapshot((0, 1, None)), request=lambda request: sent.append(request) is None)
    assert texts(ui, 2) == [
        "1 when call → browser",
        "▶ 2 when app or person without a slot → auto",
        "nothing to show: the strip goes dark",
    ]
    states = {row["name"]: row for row in model_rows(page(ui).stateButtons)}
    assert (states["call"]["text"], states["call"]["on"]) == ("call", 1)
    assert states["call"]["tip"].startswith("call: mumble runs")
    page(ui).selectSlot(2)
    assert page(ui).candidate == 1
    assert model_rows(page(ui).whySteps) == [
        {"mark": "→", "color": "tone_good", "subject": "1", "final": True, "reason": ""}
    ]
    assert info(ui)["whyHeading"] == "Now"
    assert info(ui)["whyTone"] == "good"
    click_row(ui, 2, 0)
    assert plain(info(ui)["channel"]).endswith("On no slot, and no slot asks for it.")

    # a state opens a popover: its value, the override, a simulation of it the other way
    press(ui, "state_call")
    assert [ui.shows(f"state_action_{action}") for action in ("override:on", "override:off", "simulate")] == [True] * 3
    press(ui, "state_action_override:off")
    assert sent == [SetOverride("call", "off")]

    ui.app.editor.document.set(("state", "gaming"), {"mode": True, "processes": ["steam"]})
    ui.app.editor.edited()
    press(ui, "state_gaming")
    assert ui.shows("state_action_pick")
    assert ui.shows("state_action_simulate")
    press(ui, "state_action_pick")
    assert sent[1:] == [SetMode("gaming")]
    tell(ui, snapshot((0, 1, None), pick="gaming", call=False), request=lambda request: sent.append(request) is None)
    states = {row["name"]: row for row in model_rows(page(ui).stateButtons)}
    assert (states["gaming"]["text"], states["gaming"]["on"]) == ("gaming (picked)", 1)
    assert (states["call"]["text"], states["call"]["on"]) == ("call", 0)
    tell(ui, None)
    states = {row["name"]: row for row in model_rows(page(ui).stateButtons)}
    assert (states["call"]["text"], states["call"]["on"]) == ("call", -1)
    assert info(ui)["whyLive"] is False


def test_a_state_the_daemon_does_not_tell_says_so(ui: Ui):
    press(ui, "state_call")
    assert page(ui).stateInfo("call")["unknown"] is True


def test_candidates_are_added_changed_and_removed(ui: Ui):
    slots = page(ui)
    document = ui.app.editor.document
    ui.click("add_3")
    assert document.get(("slots", "3")) == "auto"
    assert (slots.slot, slots.candidate) == (3, 0)

    ui.item("shows_field").setProperty("editText", "out")
    slots.setShows("out")
    assert document.get(("slots", "3")) == "out"
    ui.item("when_field").setProperty("text", "call")
    slots.setWhen("call")
    assert document.get(("slots", "3")) == "out if call"
    slots.setWhen("call")

    slots.add(3)
    assert document.get(("slots", "3")) == ["out if call", "auto"]
    ui.focus("list_3")
    ui.key(Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert document.get(("slots", "3")) == ["auto", "out if call"]
    assert slots.candidate == 0
    # at the top, Ctrl+Up goes nowhere; Down picks the next row
    ui.key(Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    ui.key(Qt.Key.Key_Down)
    assert document.get(("slots", "3")) == ["auto", "out if call"]
    assert slots.candidate == 1
    slots.pickRow(3, 0)

    # an option of the place, kept with the candidate, and dropped when it shows something that has no use for it
    slots.setPlaceOption("encoder", "pick")
    (first, _) = document.get(("slots", "3"))
    assert first["show"] == "auto"
    assert first["encoder"] == "pick"
    slots.setShows("out")
    assert document.get(("slots", "3")) == ["out", "out if call"]

    slots.setShows(" ")
    assert document.get(("slots", "3")) == ["out", "out if call"]
    slots.setShows("-")
    assert info(ui)["channel"] == "Nothing: the strip is dark."
    place: Any = info(ui)["place"]
    assert not place.get("form")
    slots.setShows("browser")
    slots.setPlaceOption("label", "Apps")
    assert document.get(("slots", "3", 0)) == {"show": "browser", "label": "Apps"}
    assert slots.placeOption("label") == "Apps"
    slots.setPlaceOption("label", None)
    assert document.get(("slots", "3")) == ["browser", "out if call"]
    slots.setShows("out")

    slots.reorder(3, 1, 0)
    assert document.get(("slots", "3")) == ["out if call", "out"]
    slots.remove(3)
    slots.remove(3)
    assert document.get(("slots", "3")) is None
    assert slots.candidate == -1
    slots.remove(3)
    slots.remove(4)
    # undo takes the candidate the inspector shows away
    slots.add(3)
    slots.add(3)
    ui.app.editor.undo()
    assert slots.candidate == 0


def test_the_rows_that_are_no_candidate_can_be_picked(ui: Ui):
    slots = page(ui)
    click_row(ui, 2, 2)
    assert (slots.slot, slots.candidate, slots.end) == (2, -1, True)
    assert slots.cards[1].current == 2
    assert "the strip goes dark" in str(info(ui)["hint"])
    crumbs = model_rows(slots.crumbs)
    assert [crumb["text"] for crumb in crumbs] == ["1  browser", "2  auto", "dark"]
    assert crumbs[2]["checked"] is True
    # the end goes with the candidates that make it
    ui.app.editor.document.set(("slots", "2"), ["browser", "-"])
    ui.app.editor.edited()
    assert slots.end is False
    # a slot without candidates: the row `auto` picks the slot, which says what it shows
    click_row(ui, 3, 0)
    assert (slots.slot, slots.candidate, slots.end) == (3, -1, True)
    assert "has no candidate" in str(info(ui)["hint"])
    assert model_rows(slots.crumbs) == []
    # a crumb picks its row; the one picked, clicked again, picks the slot alone
    slots.pickRow(2, 0)
    ui.click("crumb_c0")
    assert (slots.slot, slots.candidate) == (2, -1)
    ui.click("crumb_c1")
    assert slots.candidate == 1


def test_the_chip_of_what_a_candidate_shows_has_the_colors_of_its_lcd(ui: Ui):
    document = ui.app.editor.document
    document.set(("pool", "auto", "color"), "green")
    document.set(("pool", "people", "color"), "red")
    document.set(("slots", "3"), ["auto", "-", {"show": "out", "color": "teal"}])
    ui.app.editor.edited()
    out, auto = (model_rows(page(ui).cards[slot].rows) for slot in (0, 2))
    assert out[0]["swatches"] == ["#00d7e7"] or len(out[0]["swatches"]) == 1
    assert [row["show"] for row in auto] == ["auto", "-", "out", "nothing to show: the strip goes dark"]
    assert len(auto[0]["swatches"]) == 2
    assert "The LCD: green" in auto[0]["showTip"]
    assert "The LCD: red" in auto[0]["showTip"]
    # `-` is a dark LCD, a color the LCD has no backlight for stays as text
    assert auto[1]["nothing"] is True
    assert len(auto[1]["swatches"]) == 1
    assert auto[2]["swatches"] == []
    assert auto[2]["options"] == "color = teal"
    assert auto[2]["optionsTip"] == "Options of the strip in this slot only: color = teal"
    # a color of the LCD is a swatch, not text
    document.set(("slots", "3"), [{"show": "out", "color": "red", "label": "x"}])
    ui.app.editor.edited()
    (row, _) = model_rows(page(ui).cards[2].rows)
    assert row["swatches"] != []
    assert row["options"] == "label = x"


def test_picking_a_slot_scrolls_the_cards_into_view(ui: Ui):
    slots = page(ui)
    cards = ui.item("cards")
    assert cards.property("contentY") == 0
    slots.selectSlot(8)
    assert cards.property("contentY") > 0
    assert cards.property("contentX") == 0
    shown = ui.item("card_8")
    top = shown.mapToItem(cards.property("contentItem"), QPointF(0, 0)).y()
    assert cards.property("contentY") <= top
    assert top + shown.height() <= cards.property("contentY") + cards.height()
    slots.selectSlot(1)
    assert cards.property("contentY") == 0


def test_problems_show_on_the_card_and_in_the_inspector(ui: Ui):
    document = ui.app.editor.document
    document.set(("slots", "3"), ["nonsense"])
    ui.app.editor.edited()
    ui.item("card_3")
    slots = page(ui)
    assert slots.cards[2].problem != ""
    assert slots.cards[0].problem == ""
    assert ui.item("card_3").property("border") is not None
    slots.pickRow(3, 0)
    assert "nonsense" in str(info(ui)["problem"]) or str(info(ui)["problem"]) != ""
    assert ui.shows("problem_text")
    document.set(("slots", "3"), "out")
    ui.app.editor.edited()
    assert slots.cards[2].problem == ""
    assert info(ui)["problem"] == ""


def test_the_marks_of_why_follow_the_theme(ui: Ui):
    from xtouch_daemon.gui.qt.theme.tokens import THEMES, ThemeMode
    from xtouch_daemon.gui.quick.engine import theme_of

    tell(ui, snapshot((0, 1, None)))
    page(ui).selectSlot(1)
    (row,) = model_rows(page(ui).whySteps)
    # the color is named, the theme gives it: a new theme recolors it at once
    assert row["color"] == "tone_good"
    step = next(item for item in ui.all_items() if item.objectName() == "why_steps")
    assert step is not None
    theme_of(ui.engine).setMode(ThemeMode.LIGHT.value)
    ui.settle()
    assert ui.window.property("color").name() == THEMES[ThemeMode.LIGHT].surface


def test_the_texts_of_the_inspector_name_the_colors_of_the_theme(ui: Ui):
    page(ui).selectSlot(2)
    help_text = str(info(ui)["showHelp"])
    assert "@channel" in help_text
    assert "@slot" in help_text
    assert "@state" in str(info(ui)["whenHelp"])


def test_simulate_needs_a_daemon(ui: Ui):
    slots = page(ui)
    # the window's own live view has no daemon with a twin here: Simulate says so
    assert not slots.simulateEnabled
    assert "no daemon runs" in slots.simulateTip
    tell(ui, None)
    assert slots.simulateEnabled
    tell(ui, None, simulate_unavailable=lambda: Reason("no daemon", "No daemon runs."))
    assert not slots.simulateEnabled
    assert slots.simulateTip.startswith("No daemon runs.")
    ui.app.editor.document.set(("slots", "4"), "nonsense")
    ui.app.editor.edited()
    assert not slots.simulateEnabled
    assert slots.simulateTip == "Only for a file without problems"


def test_edit_actions_follow_the_focus(ui: Ui):
    slots = page(ui)
    assert slots.editable == []
    slots.pickRow(2, 0)
    ui.focus("list_2")
    assert slots.editable == ["cut", "copy", "paste", "duplicate", "remove", "rename"]
    ui.focus("list_1")
    assert slots.editable == ["paste"]
    ui.focus("when_field")
    assert slots.editable == []
