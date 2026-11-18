"""
Why a slot shows what it shows and where a channel is, from the trace in the live view.
"""

from xtouch_daemon.live.messages import SlotsState, SlotView
from xtouch_daemon.slots.why import why

SLOTS = SlotsState(
    "default",
    None,
    (
        SlotView(1, 0, "browser", None, None, ("shows browser",)),
        SlotView(
            2,
            1,
            None,
            "auto",
            "app:firefox",
            ("browser if call: doesn't hold (call is off)", "browser: on slot 1 (tie, to the left)", "shows auto"),
        ),
        SlotView(3, 0, None, "auto", "app:firefox", ("shows auto:app:firefox",)),
    ),
    (),
    {},
)


def test_why_a_slot_shows_what_it_shows():
    assert why(SLOTS, "2") == (
        "Slot 2: browser if call: doesn't hold (call is off); browser: on slot 1 (tie, to the left); shows auto"
    )
    assert why(SLOTS, "8") == "Slot 8: the daemon tells nothing about it"


def test_why_a_channel_is_where_it_is():
    assert why(SLOTS, "browser") == (
        "browser: on slot 1; not slot 2 (doesn't hold (call is off)); not slot 2 (on slot 1 (tie, to the left))"
    )
    assert why(SLOTS, "app:firefox") == "app:firefox: on slot 2; on slot 3"
    assert why(SLOTS, "mic") == "mic: on no slot, and no slot asks for it"
