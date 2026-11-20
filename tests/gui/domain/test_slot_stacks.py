"""
The stacks of the slots as the page Device edits them.
"""

from xtouch_daemon.audio.model import AudioState, Device, Direction
from xtouch_daemon.gui.domain.slot_stacks import (
    Row,
    Step,
    StepKind,
    choices,
    controls_text,
    free_text,
    free_words,
    lcd_colors,
    member_summary,
    member_text,
    place_options,
    pool_strip,
    pool_text,
    presence_words,
    readable,
    reasons,
    row_of,
    row_state,
    rows,
    stack_value,
    why_steps,
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
            "7": {"encoder": {"command": {"set": ["brightness", "-b", "{value}"]}}},
            "8": {"fader": {"command": {"set": "brightness -b {value}"}}},
        }
    }
    assert controls_text(values, 2) == ["select: launch mumble -m (when not call)"]
    assert controls_text(values, 5) == ["select: toggle:call, solo: mode:gaming"]
    assert controls_text(values, 7) == ["encoder: command brightness -b {value}"]
    assert controls_text(values, 8) == ["fader: command brightness -b {value}"]
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


VALUES = {
    "channel": {
        "browser": {"type": "apps", "color": "blue", "tags": ["media"]},
        "out": {"type": "output"},
        "mum": {"type": "person"},
        "lights": {"type": "homeassistant", "color": "yellow"},
        "radio": {"type": "apps", "tags": ["media"]},
    },
    "pool": {
        "media": {"channels": ["media"]},
        "games": {"kind": "apps", "color": "green", "from": "right"},
        "friends": {"kind": "people"},
        "people": {"color": "magenta"},
    },
}


def test_present_reads_in_words_of_what_it_asks_about():
    assert readable("present", "browser", VALUES) == ("browser plays", True)
    assert readable("not present(out)", "browser", VALUES) == ("out is not connected", True)
    assert readable("call and present(mum)", "x", VALUES) == ("call and mum is in the voice chat", False)
    # a condition that doesn't parse is shown as it is, as no question of presence alone
    assert readable("call and", "x", VALUES) == ("call and", False)
    assert [presence_words(VALUES, name) for name in ("apps", "people", "devices", "auto", "media", "lights")] == [
        "an application plays",
        "someone is in the voice chat",
        "another device is connected",
        "something plays or someone is in the voice chat",
        "a channel of media is there",
        "lights is present",
    ]
    assert [presence_words(VALUES, name, negated=True) for name in ("apps", "people", "devices", "auto")] == [
        "no application plays",
        "nobody is in the voice chat",
        "no other device is connected",
        "nothing plays and nobody is in the voice chat",
    ]
    assert presence_words(VALUES, "media", negated=True) == "no channel of media is there"
    assert presence_words(VALUES, "lights", negated=True) == "lights is absent"


def test_why_a_candidate_above_the_one_shown_did_not_win():
    candidates = [Row("browser", "gaming"), Row("apps"), Row("radio"), Row("out")]
    why = (
        "browser if gaming: doesn't hold (gaming: off, present: no)",
        "apps: none left for this slot",
        "radio: on slot 3",
        "shows out",
    )
    assert reasons(candidates, 3, why, VALUES) == {
        0: "gaming: off, browser doesn't play",
        1: "no app without a slot",
        2: "radio is on slot 3",
    }
    assert reasons(candidates, None, why, VALUES) == {}
    assert reasons([Row("out")], 1, ("out: something else",), VALUES) == {0: "something else"}


def test_what_a_pool_needs_and_hands_out_in_words():
    assert [free_words(VALUES, name) for name in ("apps", "people", "devices", "auto", "media")] == [
        "app without a slot",
        "person without a slot",
        "device without a slot",
        "app or person without a slot",
        "media channel without a slot",
    ]
    assert [free_text(VALUES, name).split(" ")[0] for name in ("apps", "people", "devices", "auto", "media")] == [
        "An",
        "Someone",
        "A",
        "An",
        "A",
    ]
    assert pool_text(VALUES, "people") == (
        "Pool people: the people of the voice chat without a slot of their own, in their order, from the right."
    )
    assert pool_text(VALUES, "games") == "Pool games: the applications of its list that play, from the right."
    assert pool_text(VALUES, "friends") == "Pool friends: the listed people of the voice chat, from the right."
    assert pool_text(VALUES, "media") == "Pool media: the next present channel of its list, from the left."
    assert "the people first" in pool_text(VALUES, "auto")
    assert pool_text(VALUES, "apps").startswith("Pool apps: the applications that play and have no slot")
    assert pool_text(VALUES, "devices").startswith("Pool devices: the outputs and inputs")


def test_the_colors_of_the_lcd_and_where_they_come_from():
    assert lcd_colors(VALUES, Row("-")) == (("off", "nothing: the LCD is dark"),)
    assert lcd_colors(VALUES, Row("out", options={"color": "red"})) == (("red", "color of this candidate"),)
    assert lcd_colors(VALUES, Row("browser")) == (("blue", "[channel.browser]"),)
    assert lcd_colors(VALUES, Row("out")) == (("white", "[channel.out]: not set, white"),)
    assert lcd_colors(VALUES, Row("auto")) == (
        ("white", "applications: [pool.auto]: not set, white"),
        ("magenta", "people: [pool.people]"),
    )
    assert lcd_colors(VALUES, Row("apps")) == (("white", "[pool.apps]: not set, white"),)
    assert lcd_colors(VALUES, Row("games")) == (("green", "[pool.games]"),)
    # a pool of channels: the colors of its channels
    assert lcd_colors(VALUES, Row("media")) == (("blue", "[channel.*] of browser"), ("white", "[channel.*] of radio"))
    assert lcd_colors(VALUES, Row("nothing_known")) == ()


def test_the_trace_of_a_slot_in_steps():
    assert why_steps(
        ("browser if gaming: doesn't hold", "held", "shows auto:app:firefox", "shows nothing: no candidate holds")
    ) == (
        Step(StepKind.PASSED, "browser if gaming", "doesn't hold"),
        Step(StepKind.HELD, "Held", "it keeps what it shows: touched, or within its dwell"),
        Step(StepKind.SHOWN, "firefox (auto)", ""),
        Step(StepKind.DARK, "Dark", "no candidate holds"),
    )
    assert [step.subject for step in why_steps(("shows -", "shows out", "shows media:radio"))] == [
        "nothing",
        "out",
        "radio (media)",
    ]


def test_a_member_as_the_card_names_it():
    assert member_text("app:firefox", {}) == "firefox"
    assert member_text("device:bluez_output.x", {"bluez_output.x": "Buds"}) == "Buds"
    assert member_text("device:usb", {}) == "usb"
    assert member_text("browser", {}) == "browser"
