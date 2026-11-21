"""
The controls of a slot as the editor of the page Slots sees them.
"""

from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.domain.schema import Kind, controls_options
from xtouch_daemon.gui.domain.slot_controls import (
    START,
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
from xtouch_daemon.slots.model import CONTROL_PARTS, ControlsConfig

VALUES = {
    "controls": {
        "3": {"rec": "toggle:call", "meter": {"watch": ["cpu"]}},
        "8": [{"color": "red", "when": "call"}, "broken", {"lcd": "homeassistant"}],
    }
}


def test_a_slot_has_one_entry_or_a_list():
    assert entries(VALUES, 3) == [{"rec": "toggle:call", "meter": {"watch": ["cpu"]}}]
    # a value that is no table is left out: its problem says why
    assert entries(VALUES, 8) == [{"color": "red", "when": "call"}, {"lcd": "homeassistant"}]
    assert entries(VALUES, 1) == []
    assert (listed(VALUES, 3), listed(VALUES, 8), listed(VALUES, 1)) == (False, True, False)
    # copies: an edit of them is not one of the file
    entries(VALUES, 3)[0]["rec"] = "x"
    assert VALUES["controls"]["3"]["rec"] == "toggle:call"  # pyright: ignore[reportIndexIssue]


def test_the_entries_go_back_into_the_file():
    assert controls_value([]) is None
    assert controls_value([{"rec": "off"}]) == {"rec": "off"}
    assert controls_value([{"rec": "off"}, {"solo": "off"}]) == [{"rec": "off"}, {"solo": "off"}]
    assert entry_path(3, 0, as_list=False) == ("controls", "3")
    assert entry_path(3, 1, as_list=True) == ("controls", "3", 1)


def test_the_parts_of_an_entry_in_the_order_of_the_device():
    entry = {"meter": {}, "when": "call", "rec": "off"}
    assert parts(entry) == ["rec", "meter"]
    assert missing(entry) == ["fader", "encoder", "select", "solo", "color", "lcd"]
    assert entry_text(entry) == "Rec and Meter"
    assert entry_text({"fader": {}, "select": {}, "lcd": {}}) == "Fader, Select and LCD line"
    assert entry_text({"color": "red"}) == "Color"
    assert entry_text({"when": "call"}) == "Nothing"


def test_a_part_starts_with_what_its_field_shows():
    assert set(START) == set(CONTROL_PARTS)
    # a color is complete; the others say at their fields what they still need
    assert ControlsConfig.model_validate({"color": START["color"]}).color == "white"


def test_home_assistant_needs_the_id():
    assert uses_home_assistant({"fader": "homeassistant"})
    assert uses_home_assistant({"rec": {"led": "homeassistant"}})
    assert uses_home_assistant({"select": {"press": "homeassistant"}})
    assert not uses_home_assistant({"rec": {"led": "off"}, "meter": {"watch": ["x"]}, "id": "desk"})


def test_entries_move_within_the_list():
    found = [{"a": 1}, {"b": 2}, {"c": 3}]
    assert moved(found, 2, -1) == [{"a": 1}, {"c": 3}, {"b": 2}]
    assert moved(found, 0, 1) == [{"b": 2}, {"a": 1}, {"c": 3}]
    # at the ends it stays
    assert moved(found, 0, -1) == found


def test_the_problems_of_an_entry_that_no_field_shows():
    problems = [
        Problem(("controls", "3", 1), "claims nothing", "value_error"),
        Problem(("controls", "3", 1, "rec", "press"), "bad", "value_error"),
        Problem(("controls", "3", 1, "when"), "no state", "value_error"),
        Problem(("controls", "3", 0), "other", "value_error"),
    ]
    assert [problem.message for problem in entry_problems(problems, ("controls", "3", 1))] == ["claims nothing"]


def test_what_the_fields_offer():
    values = {
        "channel": {"screen": {"type": "custom"}, "out": {"type": "output"}, "odd": "x"},
        "state": {"call": {}, "gaming": {"mode": True}},
    }
    assert custom_channels(values) == ["screen"]
    assert modes_and_states(values) == ["cycle_modes", "mode:gaming", "mode:default", "toggle:call", "toggle:gaming"]
    assert modes_and_states({"state": {"call": {}}}) == ["toggle:call"]


def test_the_options_of_an_entry():
    options = {option.name: option for option in controls_options()}
    assert list(options) == [*CONTROL_PARTS, "when", "id"]
    assert options["fader"].kind == Kind.BINDING
    assert options["fader"].channel
    assert options["fader"].home_assistant
    assert "push" not in [column.name for column in options["fader"].columns]
    assert "push" in [column.name for column in options["encoder"].columns]
    assert options["fader"].meaning("homeassistant").startswith("Changes a number entity")
    assert options["rec"].kind == Kind.CLAIM
    press, led = options["rec"].columns
    assert (press.kind, press.choices) == (Kind.ACTION, ("homeassistant", "cycle_modes"))
    assert press.meaning("cycle_modes")
    assert (led.kind, led.base, led.choices) == (Kind.BINDING, Kind.CHOICE, ("off", "press", "homeassistant"))
    assert [column.name for column in led.columns] == ["watch"]
    assert (options["meter"].kind, options["meter"].base) == (Kind.BINDING, None)
    assert options["color"].base == Kind.COLOR
    assert not options["meter"].channel
    assert options["when"].kind == Kind.TEXT
