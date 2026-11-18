"""
The stacks of the slots as the page Device edits them.
"""

from xtouch_daemon.audio.model import AudioState, Device, Direction
from xtouch_daemon.gui.domain.slot_stacks import (
    Row,
    choices,
    controls_text,
    member_summary,
    place_options,
    pool_strip,
    row_of,
    row_state,
    rows,
    stack_value,
)
from xtouch_daemon.live.messages import SlotsState, SlotView


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
    # the channels, the built-in pools, the pools of the file, nothing
    assert choices(values) == ["out", "mic", "auto", "apps", "people", "devices", "games", "-"]
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


def test_candidates_stand_against_the_one_shown():
    assert [row_state(index, 1, False) for index in range(3)] == ["passed", "shown", "unreached"]
    assert [row_state(index, None, False) for index in range(2)] == ["", ""]
    assert [row_state(index, None, True) for index in range(2)] == ["passed", "passed"]


def test_pools_hand_out_strips_of_their_kind():
    assert pool_strip("-") is None
    assert [pool_strip(pool) for pool in ("apps", "auto", "people", "devices")] == ["auto", "auto", "voip", "output"]
    assert pool_strip("games") == "apps"


def test_what_a_pool_hands_out_and_who_waits():
    headset = Device("bt_headset", "Headset", Direction.OUTPUT, 50, False, True)
    view = SlotView(slot=3, candidate=0, channel=None, pool="devices", member="device:bt_headset", why=())
    slots = SlotsState(mode="default", mode_pick=None, slots=(view,), states=(), waiting={"apps": ("app:mpv",)})
    assert member_summary(view, AudioState(outputs=(headset,)), slots) == ("Headset", "")
    app = SlotView(slot=4, candidate=0, channel=None, pool="auto", member="app:firefox", why=())
    assert member_summary(app, AudioState(), slots) == ("firefox", "Waiting: mpv.")
    assert member_summary(app, AudioState(), None) == ("firefox", "")
    assert member_summary(SlotView(1, 0, "out", None, None, ()), AudioState(), slots) is None
    assert member_summary(None, AudioState(), slots) is None
