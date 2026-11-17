from xtouch_daemon.gui.domain.states import describe_live, live_state, ordered, state_uses
from xtouch_daemon.live.messages import SlotsState, Snapshot, StateView


def test_modes_come_first():
    assert ordered({"call": {}, "gaming": {"mode": True}, "odd": 3}) == ["gaming", "call", "odd"]


def test_where_a_state_is_asked_about():
    values = {
        "slots": {"1": ["voip if call", {"show": "out", "when": "call or gaming"}, "auto"], "2": "x if (", "3": 4},
        "controls": {"5": {"select": "toggle:call", "when": "not call"}, "6": [{"when": "gaming"}], "7": 1},
        "state": {"both": {"when": "call and gaming"}, "odd": 1, "plain": {"apps": ["x"]}},
    }
    assert state_uses(values, "call") == ("slot 1", "controls 5", "state both")
    assert state_uses(values, "gaming") == ("slot 1", "controls 6", "state both")
    assert state_uses({}, "call") == ()


def test_what_the_daemon_says_about_a_state():
    call = StateView("call", True, False, "2026-11-17T21:04:00", "mumble runs", "on")
    slots = SlotsState("default", None, (), (call,), {})
    snapshot = Snapshot("x", True, sound_server=True, mqtt=None, strips=(), slots=slots)
    assert live_state(snapshot, "call") == call
    assert live_state(snapshot, "nope") is None
    assert live_state(None, "call") is None
    assert describe_live(call) == "on since 21:04 (mumble runs), override on"
    assert describe_live(StateView("x", False, False, None, None, "auto")) == "off"
    assert describe_live(None) == "No daemon runs these states right now."
