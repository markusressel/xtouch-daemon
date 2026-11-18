from xtouch_daemon.gui.domain.slots import slots_status
from xtouch_daemon.gui.domain.status import Tone
from xtouch_daemon.live.messages import SlotsState, SlotView, Snapshot, StateView

SLOTS = SlotsState(
    "gaming",
    None,
    (
        SlotView(1, 0, "game", None, None, ("shows game",)),
        SlotView(2, 0, None, "auto", "app:Spotify", ()),
        SlotView(3, None, None, None, None, ()),
    ),
    (
        StateView("gaming", True, True, "2026-11-17T10:00:00+00:00", "mygame runs", "auto"),
        StateView("call", False, False, None, None, "off"),
    ),
    {"auto": ("app:mpv",), "people": ()},
)


def snapshot(slots: SlotsState | None) -> Snapshot:
    return Snapshot("abc", True, False, None, (), slots=slots)


def test_the_mode_and_its_tip() -> None:
    assert slots_status(None) is None
    assert slots_status(snapshot(None)) is None
    status = slots_status(snapshot(SLOTS))
    assert status is not None
    assert (status.text, status.tone) == ("Mode: gaming", Tone.NEUTRAL)
    lines = status.tip.splitlines()
    assert lines[0].endswith("The rules pick it now.")
    assert lines[1:] == [
        "",
        "mode gaming: on (mygame runs)",
        "state call: off, override off",
        "",
        "slot 1: game",
        "slot 2: app:Spotify via auto",
        "slot 3: nothing",
        "waiting for auto: app:mpv",
    ]


def test_a_mode_by_hand() -> None:
    import dataclasses

    status = slots_status(snapshot(dataclasses.replace(SLOTS, mode_pick="gaming")))
    assert status is not None
    assert (status.text, status.tone) == ("Mode: gaming · by hand", Tone.WARN)
    assert status.tip.splitlines()[0].endswith("It was picked by hand.")
