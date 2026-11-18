"""
The distinct outcomes of a configuration, and the table in the design that shows them.
"""

import re

from tests.support.paths import DOCS
from tests.support.slots import example, older, scene
from xtouch_daemon.slots.model import DEFAULT
from xtouch_daemon.slots.outcomes import Outcome, dimensions, outcomes, states_for, table


def test_the_table_in_the_design_is_the_one_of_its_example():
    text = (DOCS / "development" / "design" / "channels-states-slots.md").read_text()
    match = re.search(r"```\n(when .*?)```", text, re.DOTALL)
    assert match is not None
    assert match.group(1) == table(outcomes(example())) + "\n"


def test_what_the_stacks_ask_about():
    assert dimensions(older()) == (("call",), ())
    assert dimensions(example()) == (("call",), ())


def test_states_presence_and_composed_states():
    read = scene(
        """
[channel.out]
type = "output"

[channel.buds]
type = "output"
device = "bluez_output.*"
tags = ["wireless"]

[pool.wireless]
channels = ["#wireless"]

[state.night]
homeassistant = true

[state.quiet]
when = "night"

[state.video]
mode = true
apps = ["mpv"]

[slots]
1 = ["buds if present", "out"]
2 = ["- if quiet", "wireless if present", "auto"]
3 = ["out if video", "auto"]
"""
    )
    # quiet follows from night: no row has one without the other
    assert table(outcomes(read)) == (
        # wireless has none left for slot 2 (buds is on slot 1): auto gets it
        "when                          1     2     3     4-8\n"
        "default                       buds  auto  auto  auto\n"
        "night                         buds  -     auto  auto\n"
        "video                         buds  auto  out   auto\n"
        "buds absent                   out   auto  auto  auto\n"
        "video and night               buds  -     out   auto\n"
        "night, buds absent            out   -     auto  auto\n"
        # out ranks higher on slot 3: slot 1 goes on to auto
        "video, buds absent            auto  auto  out   auto\n"
        "video and night, buds absent  auto  -     out   auto"
    )
    # a composed state named on is on, whatever it names (simulate --state quiet)
    assert states_for(read, DEFAULT, ["quiet"])["quiet"]


def test_neighbors_that_always_show_the_same_are_merged():
    rows = [
        Outcome("default", ("a", "b", "b", "c", "c", "c", "d", "d")),
        Outcome("x", ("a", "b", "b", "c", "e", "e", "d", "d")),
    ]
    assert table(rows) == "when     1  2-3  4  5-6  7-8\ndefault  a  b    c  c    d\nx        a  b    c  e    d"
