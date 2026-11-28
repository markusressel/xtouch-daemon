from datetime import datetime

from xtouch_daemon.gui.domain.states import describe_live, live_state, ordered, spans_on, state_uses
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


def test_the_history_of_a_state_by_quarters_of_an_hour():
    zone = datetime.now().astimezone().tzinfo
    noon = datetime(2026, 11, 28, 12, 0, tzinfo=zone).timestamp()
    # watched from 11:10, on from 11:20 to 11:25 and since 11:50; now is 12:05
    minute = 60
    history = ((noon - 50 * minute, False), (noon - 40 * minute, True), (noon - 35 * minute, False), (noon - 600, True))
    spans = spans_on(history, noon + 5 * minute, spans=5)
    assert [f"{span.start:%H:%M}" for span in spans] == ["11:00", "11:15", "11:30", "11:45", "12:00"]
    assert [(span.on / minute, span.known / minute) for span in spans] == [(0, 5), (5, 15), (0, 15), (10, 15), (5, 5)]
    assert all(span.length == 15 * minute for span in spans)
    assert [span.describe() for span in spans] == [
        "11:00-11:15: off, watched for 5 min",
        "11:15-11:30: on for 5 min",
        "11:30-11:45: off",
        "11:45-12:00: on for 10 min",
        "12:00-12:05: on",
    ]
    assert spans_on(history, noon - 3 * 3600, spans=1)[0].describe() == "09:00-09:00: no daemon watched it"
    moment = spans_on(((noon, True), (noon + 20, False)), noon + 600, spans=1)[0]
    assert moment.describe() == "12:00-12:10: on for a moment"
    assert len(spans_on(history, noon)) == 96
