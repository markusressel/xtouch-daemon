import dataclasses

import pytest

from tests.support.gui import strip_state
from xtouch_daemon.gui.domain.looks import AWAY, UNKNOWN, device_faces, meter_leds, ring_leds
from xtouch_daemon.live.messages import SlotsState, SlotView, Snapshot


def test_without_the_daemon_the_device_is_dark():
    assert device_faces(None) == (UNKNOWN,) * 8


def test_without_the_device_the_strips_are_dark():
    # what the daemon would show on it once it is there does not show
    snapshot = Snapshot("x", False, sound_server=True, mqtt=None, strips=(strip_state(("Speaker", "100%")),) * 8)

    assert device_faces(snapshot) == (AWAY,) * 8
    assert AWAY.state.color == "off"


def test_the_device_shows_what_each_slot_shows():
    strips = (strip_state(("Speaker", "100%"), color="cyan"), *(strip_state() for _ in range(7)))
    views = (
        SlotView(1, 0, "out", None, None, ()),
        SlotView(2, 1, None, "auto", "app:Brave", ()),
    )
    slots = SlotsState("default", None, views, (), {})
    snapshot = Snapshot("x", True, sound_server=True, mqtt=None, strips=strips, slots=slots)

    first, second, third, *_ = device_faces(snapshot)

    assert (first.look.label, first.look.printed, first.look.detail) == ("Speaker", "out", "Shows out")
    assert first.live
    assert not first.dimmed
    assert (second.look.printed, second.look.detail, second.dimmed) == ("auto", "Shows app:Brave via auto", True)
    assert (third.look.printed, third.look.detail) == ("", "")
    # a daemon without slots: what the strips show, nothing printed
    plain = device_faces(dataclasses.replace(snapshot, slots=None))
    assert plain[0].look.printed == ""


@pytest.mark.parametrize(
    ("position", "mode", "lit"),
    [
        (0, "wrap", set()),
        (3, "dot", {3}),
        (15, "dot", {11}),
        (4, "wrap", {1, 2, 3, 4}),
        (8, "boost_cut", {6, 7, 8}),
        (4, "boost_cut", {4, 5, 6}),
        (1, "spread", {6}),
        (3, "spread", {4, 5, 6, 7, 8}),
        (11, "spread", set(range(1, 12))),
    ],
)
def test_a_ring_lights_like_the_device(position: int, mode: str, lit: set[int]):
    assert ring_leds(position, mode) == lit


def test_a_meter_lights_its_segments():
    assert [meter_leds(level) for level in range(15)] == [0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 7, 8]
    assert (meter_leds(-1), meter_leds(15)) == (0, 8)
