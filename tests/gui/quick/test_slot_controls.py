"""
The controls of a slot (`[controls]`) on the page Slots in Qt Quick: entries and the parts they claim, with the
option rows of the forms for the parts (`entryForm`).
"""

from typing import Any

from tests.gui.quick.slots_helpers import model_rows, page, polish
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.forms.form import Form
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


def form_of(ui: Ui, index: int = 0) -> Form:
    form = controls_of(ui).entryForm(index)
    assert isinstance(form, Form)
    return form


def rows_of(ui: Ui, index: int = 0) -> dict[str, dict[str, Any]]:
    """The rows of the parts of an entry by option name: their `spec` and their `info`."""
    model: Any = form_of(ui, index).rows
    return {spec["name"]: {"spec": spec, "info": info} for _key, spec, info in model.rows}


def led_of(ui: Ui, name: str, index: int = 0) -> str:
    """The placeholder of the part `led` of a button, and `press` for the other."""
    return part_of(ui, name, "led", index)


def part_of(ui: Ui, name: str, part: str, index: int = 0) -> str:
    form = form_of(ui, index)
    loaded = form.buttonLoad(name, rows_of(ui, index)[name]["info"]["value"])
    parts = form.buttonView(name, loaded["texts"], loaded["kept"])["parts"]
    return next(each["placeholder"] for each in parts if each["name"] == part)


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
    form_of(ui, 0).setValue("lcd", "homeassistant")
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
    assert ui.shows("controls_parts")


def test_a_part_added_shows_its_row_with_the_problem_at_it(ui: Ui):
    page(ui).selectSlot(1)
    controls_of(ui).addEntry("meter")
    assert ui.app.editor.document.get(("controls", "1")) == {"meter": {}}
    assert list(rows_of(ui)) == ["meter"]
    # the problem shows at the part: it takes watch or poll
    assert "watch or poll" in "\n".join(rows_of(ui)["meter"]["info"]["problems"])
    assert entries(ui)[0]["title"] == "Meter"
    assert controls_of(ui).addPlaceholder == "Add controls"

    ui.app.editor.undo()
    assert ui.app.editor.document.get(("controls",)) is None
    assert entries(ui) == []


def test_a_part_is_edited_in_place(ui: Ui):
    setup(ui, "1", {"color": "red"})
    document = ui.app.editor.document
    form = form_of(ui)
    form.setValue("color", "blue")
    assert document.get(("controls", "1", "color")) == "blue"
    # the same form: a value changed in place
    assert form_of(ui) is form
    assert rows_of(ui)["color"]["info"]["value"] == "blue"
    form.setValue("color", "homeassistant")
    assert document.get(("controls", "1", "color")) == "homeassistant"
    # Home Assistant names its entities by the id
    assert list(rows_of(ui)) == ["color", "id"]
    assert rows_of(ui)["id"]["info"]["placeholder"] == "slot_1"
    assert rows_of(ui)["color"]["info"]["resetTip"] == "Remove the part: it goes back to what the slot shows"
    # back: the part goes, and its row with it
    form.reset("color")
    assert document.get(("controls",)) is None
    assert entries(ui) == []
    assert rows_of(ui) == {}


def test_parts_are_added_to_an_entry_in_the_order_of_the_device(ui: Ui):
    setup(ui, "2", {"color": "red", "when": "call"}, picked=2)
    (entry,) = entries(ui)
    assert "color" not in [part["name"] for part in entry["missing"]]
    controls_of(ui).addPart(0, "rec")
    assert ui.app.editor.document.get(("controls", "2")) == {"color": "red", "when": "call", "rec": {}}
    assert list(rows_of(ui)) == ["rec", "color"]
    assert rows_of(ui)["rec"]["info"]["problems"] == ["a button takes press, led or both"]
    assert entries(ui)[0]["title"] == "Rec and Color"


def test_problems_of_an_entry_of_a_list_show_at_its_fields(ui: Ui):
    setup(ui, "1", {"color": "red", "when": "call"})
    controls_of(ui).addEntry("lcd")
    assert rows_of(ui, 1)["lcd"]["info"]["problems"]
    assert not rows_of(ui, 0)["color"]["info"]["problems"]
    controls_of(ui).moveEntry(1, -1)
    assert list(rows_of(ui, 0)) == ["lcd"]
    assert list(rows_of(ui, 1)) == ["color"]


def test_a_button_takes_its_press_its_led_or_both(ui: Ui):
    setup(ui, "1", {"rec": "toggle:call"})
    form = form_of(ui)
    document = ui.app.editor.document
    assert rows_of(ui)["rec"]["spec"]["kind"] == "claim"
    assert part_of(ui, "rec", "press") == "As on what the slot shows"
    assert led_of(ui, "rec") == "What the press does"
    loaded = form.buttonLoad("rec", "toggle:call")
    assert loaded["texts"]["press"] == "toggle:call"
    items = form.buttonView("rec", loaded["texts"], loaded["kept"])["parts"][0]["items"]
    assert "toggle:call" in [item["text"] for item in items]

    edit = form.buttonEdit("rec", {"press": "toggle:call", "led": "watch: lamp --follow"}, {})
    form.setValue("rec", edit["value"])
    assert document.get(("controls", "1", "rec")) == {"press": "toggle:call", "led": {"watch": ["lamp", "--follow"]}}
    edit = form.buttonEdit("rec", {"press": "", "led": "watch: lamp --follow"}, {})
    form.setValue("rec", edit["value"])
    assert document.get(("controls", "1", "rec")) == {"led": {"watch": ["lamp", "--follow"]}}
    edit = form.buttonEdit("rec", {"press": "run: notify-send hi", "led": ""}, {})
    form.setValue("rec", edit["value"])
    # the press alone: the short form
    assert document.get(("controls", "1", "rec")) == {"run": ["notify-send", "hi"]}


def test_the_led_of_a_launch_or_a_run_shows_what_the_press_does(ui: Ui):
    setup(ui, "1", {"select": {"launch": ["mumble"]}, "rec": {"run": ["notify-send", "hi"]}, "solo": {"led": "off"}})
    assert led_of(ui, "select") == "What the press does"
    assert led_of(ui, "rec") == "What the press does"
    assert part_of(ui, "solo", "press") == "As on what the slot shows"


def test_a_fader_sets_the_value_of_a_custom_channel(ui: Ui):
    ui.app.editor.document.set(("channel", "screen"), {"type": "custom", "fader": {"set": ["x", "{value}"]}})
    setup(ui, "1", {"fader": {}})
    form = form_of(ui)
    spec = rows_of(ui)["fader"]["spec"]
    assert spec["channel"]
    assert rows_of(ui)["fader"]["info"]["channels"] == ["screen"]
    value = form.bindValue("fader", "channel", {})
    assert value == {"channel": "screen"}
    form.setValue("fader", value)
    assert ui.app.editor.document.get(("controls", "1", "fader")) == {"channel": "screen"}
    form.setValue("fader", {"channel": "other"})
    assert ui.app.editor.document.get(("controls", "1", "fader")) == {"channel": "other"}
    assert rows_of(ui)["fader"]["info"]["problems"]


def test_without_a_custom_channel_a_channel_starts_empty(ui: Ui):
    setup(ui, "1", {"encoder": "homeassistant"})
    form = form_of(ui)
    assert form.bindValue("encoder", "channel", {}) == {"channel": ""}


def test_the_last_part_of_an_entry_of_a_list_goes_with_it_and_one_left_is_a_table(ui: Ui):
    setup(ui, "8", [{"color": "red"}, {"lcd": {"watch": ["clock"]}}], picked=8)
    form_of(ui, 1).reset("lcd")
    assert ui.app.editor.document.get(("controls", "8")) == {"color": "red"}
    assert [entry["title"] for entry in entries(ui)] == ["Color"]


def test_the_rows_of_the_parts_show_in_the_window(ui: Ui):
    setup(ui, "1", {"color": "red", "lcd": {"watch": ["clock"]}})
    ui.window.resize(1280, 2400)
    polish(ui)
    assert ui.shows("row_color")
    assert ui.shows("row_lcd")
