"""
Simulate: a what-if resolved, its slots and states, and the faces of the drawing.
"""

from xtouch_daemon.config.files import parse_config
from xtouch_daemon.gui.domain.simulate import Inputs, WhatIf, presence_text, simulated, simulated_faces

CONFIG = """
[channel.out]
type = "output"
label = "Spk"
color = "cyan"

[channel.voip]
type = "apps"
match = ["mumble"]
label = "VoIP"

[state.call]
voice_chat = true

[state.gaming]
mode = true

[slots]
1 = "out"
2 = ["voip if call and present", "auto"]
3 = ["out if gaming", "-"]
"""


def test_a_what_if_is_resolved():
    setup = parse_config(CONFIG, "test").slots
    inputs = Inputs.of(setup)
    assert inputs == Inputs(("default", "gaming"), ("call",), ("voip",))
    slots = simulated(setup, WhatIf().toggled("call", flip=False))
    assert [view.channel or view.pool for view in slots.slots[:3]] == ["out", "voip", None]
    assert {state.name: (state.value, state.source) for state in slots.states} == {
        "call": (True, "what if"),
        "gaming": (False, None),
    }
    gone = simulated(setup, WhatIf("gaming", frozenset({"call"})).toggled("voip", flip=True))
    assert [view.channel or view.pool for view in gone.slots[:3]] == ["out", "auto", None]
    assert gone.mode == "gaming"
    # Simulate starts with what the daemon tells: the mode and the states that are on
    assert WhatIf.of_live(gone) == WhatIf("gaming", frozenset({"call"}))
    assert (presence_text("auto"), presence_text("voip")) == ("auto plays", "voip absent")


def test_faces_show_what_would_be_shown():
    setup = parse_config(CONFIG, "test").slots
    faces = simulated_faces(setup, simulated(setup, WhatIf()))
    assert (faces[0].state.text, faces[0].state.color, faces[0].look.printed) == (("Spk", "what if"), "cyan", "out")
    assert faces[2].dimmed
    assert not faces[0].live
