from datetime import datetime

from xtouch_daemon.gui.domain.states import describe_live, hours_on, live_state, ordered, state_uses
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


def test_the_history_of_a_state_by_the_hours_of_the_clock():
    zone = datetime.now().astimezone().tzinfo
    noon = datetime(2026, 11, 28, 12, 0, tzinfo=zone).timestamp()
    # watched from 9:30, on from 10:15 to 10:45 and since 11:50; now is 12:20
    history = ((noon - 2.5 * 3600, False), (noon - 1.75 * 3600, True), (noon - 1.25 * 3600, False), (noon - 600, True))
    hours = hours_on(history, noon + 1200, hours=5)
    assert [hour.start.hour for hour in hours] == [8, 9, 10, 11, 12]
    assert [hour.share for hour in hours] == [None, 0, 0.5, 600 / 3600, 1]
    assert [hour.describe() for hour in hours] == [
        "08:00-09:00: no daemon watched it",
        "09:00-10:00: off, watched for 30 min",
        "10:00-11:00: on for 30 min",
        "11:00-12:00: on for 10 min",
        "12:00-12:20: on",
    ]
    assert (
        hours_on(((noon, True), (noon + 20, False)), noon + 3540, hours=1)[0].describe()
        == "12:00-12:59: on for a moment"
    )
