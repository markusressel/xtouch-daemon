"""
The controls of a slot (`[controls]`) on the page Slots in Qt Quick: entries and the parts they claim. The option
rows of the parts are the forms' (see the placeholder `SlotControlParts`), so the tests here stop at the entry.
"""

from typing import Any

from tests.gui.quick.slots_helpers import model_rows, page, polish
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.pages.slots_controls import SlotControls


def setup(ui: Ui, slot: str, value: Any, picked: int = 1) -> None:
    ui.app.editor.document.set(("controls", slot), value)
    ui.app.editor.edited()
    page(ui).selectSlot(picked)
    polish(ui)


def controls_of(ui: Ui) -> SlotControls:
    controls = page(ui).controls
    assert isinstance(controls, SlotControls)
    return controls


def entries(ui: Ui) -> list[dict[str, Any]]:
    return model_rows(controls_of(ui).entries)


def test_a_slot_without_controls_offers_its_parts(ui: Ui):
    page(ui).selectSlot(1)
    controls = controls_of(ui)
    assert controls.title == "Controls of slot 1"
    assert "claims no part of" in controls.help
    assert entries(ui) == []
    assert controls.addPlaceholder == "Add a part"
    assert [choice["text"] for choice in controls.addChoices][-3:] == ["Meter", "Color", "LCD line"]
    controls.addEntry("meter")
    assert ui.app.editor.document.get(("controls", "1")) == {"meter": {}}
    (entry,) = entries(ui)
    assert entry["title"] == "Meter"
    assert [part["name"] for part in entry["parts"]] == ["meter"]
    assert controls.addPlaceholder == "Add controls"
    ui.app.editor.undo()
    assert ui.app.editor.document.get(("controls",)) is None
    assert entries(ui) == []


def test_parts_are_added_to_an_entry(ui: Ui):
    setup(ui, "2", {"color": "red", "when": "call"}, picked=2)
    (entry,) = entries(ui)
    assert entry["when"] == "call"
    assert "Color" not in [part["text"] for part in entry["missing"]]
    controls_of(ui).addPart(0, "rec")
    assert ui.app.editor.document.get(("controls", "2")) == {"color": "red", "when": "call", "rec": {}}
    (entry,) = entries(ui)
    assert entry["title"] == "Rec and Color"


def test_when_of_an_entry(ui: Ui):
    setup(ui, "1", {"color": "red"})
    controls = controls_of(ui)
    doc = ui.app.editor.document
    controls.setWhen(0, "nothing_here")
    assert doc.get(("controls", "1", "when")) == "nothing_here"
    assert entries(ui)[0]["whenError"]
    controls.setWhen(0, "call")
    assert entries(ui)[0]["whenError"] == ""
    controls.setWhen(0, "")
    assert doc.get(("controls", "1")) == {"color": "red"}


def test_several_entries_are_a_list_that_moves(ui: Ui):
    setup(ui, "1", {"color": "red", "when": "call"})
    controls = controls_of(ui)
    doc = ui.app.editor.document
    controls.addEntry("lcd")
    assert doc.get(("controls", "1")) == [{"color": "red", "when": "call"}, {"lcd": {}}]
    first, second = entries(ui)
    assert (first["title"], second["title"]) == ("1. Color", "2. LCD line")
    assert not first["canUp"]
    assert first["canDown"]
    controls.moveEntry(1, -1)
    assert doc.get(("controls", "1")) == [{"lcd": {}}, {"color": "red", "when": "call"}]
    controls.setOption(["controls", "1", 0, "lcd"], "homeassistant")
    assert doc.get(("controls", "1", 0, "lcd")) == "homeassistant"
    controls.removeEntry(0)
    assert doc.get(("controls", "1")) == {"color": "red", "when": "call"}
    assert not entries(ui)[0]["many"]


def test_an_entry_that_claims_nothing_says_so(ui: Ui):
    setup(ui, "1", {"when": "call"})
    (entry,) = entries(ui)
    assert entry["title"] == "Nothing"
    assert entry["error"].startswith("claims nothing")


def test_the_entries_show_in_the_inspector(ui: Ui):
    setup(ui, "1", {"color": "red"})
    ui.window.resize(1280, 2400)
    polish(ui)
    assert ui.shows("entry_0")
    assert ui.shows("controls_parts_placeholder")
