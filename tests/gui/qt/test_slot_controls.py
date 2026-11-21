"""
The editor of the controls of a slot (`[controls]`) on the page Slots: entries, the parts they set, When and Id, and
the problems at their fields.
"""

from tests.support.gui import plain
from xtouch_daemon.gui.qt.fields.binding import CHANNEL, PROGRAM
from xtouch_daemon.gui.qt.fields.buttons import ButtonField, parts_of
from xtouch_daemon.gui.qt.fields.choice import Choice
from xtouch_daemon.gui.qt.pages.slot_controls import EntryBox, SlotControls
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.slots.model import CONTROL_BUTTONS


def controls(window: MainWindow, slot: int = 1) -> SlotControls:
    window.slots_page.select_slot(slot)
    return window.slots_page.slot_controls


def pick(choice: Choice, text: str) -> None:
    """Picks an entry of a drop-down as a click does."""
    index = choice.findText(text)
    assert index >= 0, text
    choice.setCurrentIndex(index)
    choice.activated.emit(index)


def box(window: MainWindow, index: int = 0, slot: int = 1) -> EntryBox:
    return (
        window.slots_page.slot_controls.boxes[index]
        if slot == window.slots_page.slot
        else controls(window, slot).boxes[index]
    )


def setup(window: MainWindow, slot: str, value: object) -> None:
    window.document.set(("controls", slot), value)
    window.editor.edited()


def test_a_slot_without_controls_offers_its_parts(window: MainWindow):
    page = controls(window)
    assert page.title.text() == "Controls of slot 1"
    assert plain(page.help.text()).startswith("[controls] claims no part of slot 1.")
    assert page.boxes == []
    assert page.add.placeholderText() == "Add a part"
    assert [page.add.itemText(index) for index in range(page.add.count())][-3:] == ["Meter", "Color", "LCD line"]

    pick(page.add, "Meter")
    assert window.document.get(("controls", "1")) == {"meter": {}}
    (entry,) = page.boxes
    assert list(entry.rows) == ["meter", "id"]
    assert entry.rows["meter"].binding.mode == PROGRAM
    # the problem shows at the option of the program it is about
    assert not entry.rows["meter"].binding.rows["watch"].error.isHidden()
    assert entry.rows["id"].isHidden()
    assert page.add.placeholderText() == "Add controls"
    assert entry.title.text() == "Meter"

    window.editor.undo()
    assert window.document.get(("controls",)) is None
    assert window.slots_page.slot_controls.boxes == []


def test_a_part_is_edited_in_place(window: MainWindow):
    setup(window, "1", {"color": "red"})
    entry = box(window, slot=1)
    row = entry.rows["color"]
    row.colors.picked.emit("blue")
    assert window.document.get(("controls", "1", "color")) == "blue"
    # the same form: a value changed in place
    assert box(window) is entry
    row.binding.bind_to("homeassistant")
    assert window.document.get(("controls", "1", "color")) == "homeassistant"
    # Home Assistant names its entities by the id
    assert not entry.rows["id"].isHidden()
    assert entry.rows["id"].line.placeholderText() == "slot_1"
    # back: the part goes, and its row with it
    entry.rows["color"].reset.click()
    assert window.document.get(("controls",)) is None
    assert window.slots_page.slot_controls.boxes == []


def test_parts_are_added_to_an_entry(window: MainWindow):
    setup(window, "2", {"color": "red", "when": "call"})
    entry = box(window, slot=2)
    assert entry.when.text() == "call"
    assert "Color" not in [entry.add.itemText(index) for index in range(entry.add.count())]
    pick(entry.add, "Rec")
    assert window.document.get(("controls", "2")) == {"color": "red", "when": "call", "rec": {}}
    entry = box(window, slot=2)
    assert list(entry.rows) == ["rec", "color", "id"]
    assert plain(entry.rows["rec"].error.text()) == "a button takes press, led or both"
    assert entry.title.text() == "Rec and Color"


def test_when_of_an_entry(window: MainWindow):
    setup(window, "1", {"color": "red"})
    entry = box(window)
    entry.when.setText("nothing_here")
    entry.when.editingFinished.emit()
    assert window.document.get(("controls", "1", "when")) == "nothing_here"
    assert not entry.when_error.isHidden()
    entry.when.setText("call")
    entry.when.editingFinished.emit()
    assert entry.when_error.isHidden()
    entry.when.setText("")
    entry.when.editingFinished.emit()
    assert window.document.get(("controls", "1")) == {"color": "red"}


def test_several_entries_are_a_list(window: MainWindow):
    setup(window, "1", {"color": "red", "when": "call"})
    page = controls(window)
    pick(page.add, "LCD line")
    assert window.document.get(("controls", "1")) == [{"color": "red", "when": "call"}, {"lcd": {}}]
    first, second = page.boxes
    assert (first.title.text(), second.title.text()) == ("1. Color", "2. LCD line")
    assert not first.up.isEnabled()
    assert first.down.isEnabled()
    # problems of an entry of the list show at its fields
    assert not second.rows["lcd"].binding.rows["watch"].error.isHidden()

    second.up.click()
    assert window.document.get(("controls", "1")) == [{"lcd": {}}, {"color": "red", "when": "call"}]
    page.boxes[0].rows["lcd"].binding.bind_to("homeassistant")
    assert window.document.get(("controls", "1", 0, "lcd")) == "homeassistant"
    page.boxes[0].remove.click()
    # one left: a table again
    assert window.document.get(("controls", "1")) == {"color": "red", "when": "call"}
    assert page.boxes[0].up.isHidden()


def test_an_entry_that_claims_nothing_says_so(window: MainWindow):
    setup(window, "1", {"when": "call"})
    entry = box(window)
    assert entry.title.text() == "Nothing"
    assert plain(entry.error.text()).startswith("claims nothing")


def test_a_button_takes_its_press_its_led_or_both(window: MainWindow):
    setup(window, "1", {"rec": "toggle:call"})
    field = box(window).rows["rec"].buttons
    assert isinstance(field, ButtonField)
    assert field.claim
    assert field.combos["press"].currentText() == "toggle:call"
    assert field.combos["led"].placeholderText() == "What the press does"
    assert "toggle:call" in [field.combos["press"].itemText(index) for index in range(field.combos["press"].count())]

    field.combos["led"].setEditText("watch: lamp --follow")
    assert window.document.get(("controls", "1", "rec")) == {
        "press": "toggle:call",
        "led": {"watch": ["lamp", "--follow"]},
    }
    field.combos["press"].setEditText("")
    assert window.document.get(("controls", "1", "rec")) == {"led": {"watch": ["lamp", "--follow"]}}
    field.combos["press"].setEditText("run: notify-send hi")
    field.combos["led"].setEditText("")
    # the press alone: the short form
    assert window.document.get(("controls", "1", "rec")) == {"run": ["notify-send", "hi"]}


def test_the_short_forms_of_a_button_of_the_controls():
    for button in CONTROL_BUTTONS:
        assert parts_of(button, "toggle:call", claim=True) == {"press": "toggle:call"}
        assert parts_of(button, {"launch": ["x"]}, claim=True) == {"press": {"launch": ["x"]}}
        assert parts_of(button, {"led": "off"}, claim=True) == {"led": "off"}
        assert parts_of(button, 3, claim=True) == {}
    # on a channel a word is the LED
    assert parts_of("rec", "muted") == {"led": "muted"}


def test_a_fader_sets_the_value_of_a_custom_channel(window: MainWindow):
    window.document.set(("channel", "screen"), {"type": "custom", "fader": {"set": ["x", "{value}"]}})
    setup(window, "1", {"fader": {}})
    binding = box(window).rows["fader"].binding
    assert "A channel" in [action.text() for action in binding.menu.actions()]
    binding.bind_to(CHANNEL)
    assert window.document.get(("controls", "1", "fader")) == {"channel": "screen"}
    assert binding.mode == CHANNEL
    assert not binding.channel.isHidden()
    assert binding.program.isHidden()
    assert binding.channel.currentText() == "screen"
    assert binding.word() is None
    binding.channel.setEditText("other")
    binding.channel.lineEdit().editingFinished.emit()  # pyright: ignore[reportOptionalMemberAccess]
    assert window.document.get(("controls", "1", "fader")) == {"channel": "other"}
    assert plain(box(window).rows["fader"].error.text())
    # the same name again changes nothing
    binding.channel.lineEdit().editingFinished.emit()  # pyright: ignore[reportOptionalMemberAccess]
    assert window.document.get(("controls", "1", "fader")) == {"channel": "other"}


def test_without_a_custom_channel_a_channel_starts_empty(window: MainWindow):
    setup(window, "1", {"encoder": "homeassistant"})
    binding = box(window).rows["encoder"].binding
    binding.bind_to(CHANNEL)
    assert window.document.get(("controls", "1", "encoder")) == {"channel": ""}
    assert binding.bind.toolTip() == "Bound to a channel: click to change"
    binding.bind_to("words")
    assert window.document.get(("controls",)) is None


def test_an_unbound_part_says_what_it_can_be_bound_to(window: MainWindow):
    setup(window, "1", {"color": "red", "fader": "homeassistant"})
    rows = box(window).rows
    assert rows["color"].binding.bind.toolTip() == "Bind it to Home Assistant or a program of your own"
    assert rows["fader"].binding.bind.toolTip() == "Bound to Home Assistant: click to change"


def test_the_last_part_of_an_entry_of_a_list_goes_with_it_and_one_left_is_a_table(window: MainWindow):
    setup(window, "8", [{"color": "red"}, {"lcd": {"watch": ["clock"]}}])
    page = controls(window, 8)
    page.boxes[1].rows["lcd"].reset.click()
    assert window.document.get(("controls", "8")) == {"color": "red"}
    assert [entry.title.text() for entry in page.boxes] == ["Color"]


def test_the_led_of_a_launch_or_a_run_shows_what_the_press_does(window: MainWindow):
    setup(
        window, "1", {"select": {"launch": ["mumble"]}, "rec": {"run": ["notify-send", "hi"]}, "solo": {"led": "off"}}
    )
    rows = box(window).rows
    assert rows["select"].buttons.combos["led"].placeholderText() == "What the press does"
    assert rows["rec"].buttons.combos["led"].placeholderText() == "What the press does"
    assert rows["solo"].buttons.combos["press"].placeholderText() == "As on what the slot shows"
