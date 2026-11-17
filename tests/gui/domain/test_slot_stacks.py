"""
The stacks of the slots as the page Device edits them.
"""

from xtouch_daemon.gui.domain.slot_stacks import (
    Row,
    choices,
    controls_text,
    place_options,
    row_of,
    rows,
    stack_value,
)


def test_candidates_are_read_in_each_form():
    assert row_of("out") == Row("out")
    assert row_of("voip if call or gaming") == Row("voip", "call or gaming")
    assert row_of({"show": "auto", "when": "x", "color": "blue"}) == Row("auto", "x", {"color": "blue"})
    assert row_of({"color": "blue"}) == Row("?", "", {"color": "blue"})
    assert row_of(3) == Row("?")
    assert rows({"slots": {"2": ["a if b", "c"]}}, 2) == [Row("a", "b"), Row("c")]
    assert rows({}, 1) == []


def test_conditions_are_chips():
    assert Row("a").chips == ("always",)
    assert Row("a", "call or not gaming").chips == ("call", "not gaming")


def test_stacks_are_written_in_the_smallest_form():
    assert stack_value([]) is None
    assert stack_value([Row("out")]) == "out"
    assert stack_value([Row("voip", "call"), Row("auto")]) == ["voip if call", "auto"]
    assert stack_value([Row("auto", "", {"color": "blue"})]) == [{"show": "auto", "color": "blue"}]
    assert stack_value([Row("a", "b", {"rec": "mute"})]) == [{"show": "a", "when": "b", "rec": "mute"}]


def test_what_a_place_can_show_and_take():
    values = {"channel": {"out": {}, "mic": {}}, "pool": {"auto": {}, "games": {}}}
    assert choices(values) == ["out", "mic", "auto", "games", "-"]
    assert "encoder" in place_options("auto")
    assert "encoder" not in place_options("out")
    assert "color" in place_options("out")


def test_controls_are_text():
    values = {
        "controls": {
            "2": {"select": {"launch": ["mumble", "-m"]}, "when": "not call"},
            "5": [{"select": "toggle:call", "solo": "mode:gaming"}, "broken"],
        }
    }
    assert controls_text(values, 2) == ["select: launch mumble -m (when not call)"]
    assert controls_text(values, 5) == ["select: toggle:call, solo: mode:gaming"]
    assert controls_text(values, 1) == []
