"""
Simulate: the what-if, the inputs a configuration offers it and the words of its buttons.
"""

from xtouch_daemon.config.files import parse_config
from xtouch_daemon.gui.domain.simulate import Inputs, WhatIf, is_present, presence_tip, state_tip
from xtouch_daemon.live.messages import SlotsState, StateView

CONFIG = """
[channel.out]
type = "output"
label = "Spk"

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
"""


def test_the_inputs_of_a_configuration():
    assert Inputs.of(parse_config(CONFIG, "test").slots) == Inputs(("default", "gaming"), ("call",), ("voip",))


def test_a_what_if_changes_one_thing_at_a_time():
    what_if = WhatIf().toggled("call", flip=False).toggled("voip", flip=True).counted(people=2)
    assert what_if == WhatIf(on=frozenset({"call"}), flipped=frozenset({"voip"}), people=2)
    assert what_if.toggled("call", flip=False).on == frozenset()


def test_simulate_starts_with_what_the_daemon_tells():
    slots = SlotsState(
        mode="gaming",
        mode_pick=None,
        slots=(),
        states=(
            StateView("call", True, False, None, "voice chat", "auto"),
            StateView("gaming", True, True, None, "steam", "auto"),
        ),
        waiting={},
    )
    assert WhatIf.of_live(slots) == WhatIf("gaming", frozenset({"call"}))
    # a channel is present until flipped, the built-in pools empty until flipped
    assert (is_present("voip", False), is_present("voip", True)) == (True, False)
    assert (is_present("apps", False), is_present("auto", True)) == (False, True)
    assert presence_tip("voip", False) == "voip is present. Click: absent."
    assert presence_tip("voip", True) == "voip is absent. Click: present."
    assert presence_tip("people", False) == "The pool people is empty. Click: it has members."
    assert presence_tip("people", True) == "The pool people has members. Click: it is empty."
    assert presence_tip("auto", False) == "No application plays for auto. Click: one does."
    assert presence_tip("auto", True) == "An application plays for auto. Click: none."
    assert state_tip("call", True) == "call is on. Click: off."
