import pytest

from tests.conftest import RecordingSurface
from xtouch_daemon.placement import Flow, place
from xtouch_daemon.protocol import Button, Color, Led
from xtouch_daemon.surface import VirtualStrip


def test_the_first_strips_that_take_a_place_are_on_the_device() -> None:
    collapse = [False, True, False, False]
    assert place(collapse, [False] * 4, count=3) == (0, 1, 2)
    # the second one collapses: the others move up, the last one gets a place
    assert place(collapse, [False, True, False, False], count=3) == (0, 2, 3)
    # only strips with collapse do
    assert place(collapse, [True, False, True, True], count=3) == (0, 1, 2)
    # fewer than the device has: the rest shows none
    assert place([True, True], [True, False], count=3) == (1, None, None)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make_flow(
    surface: RecordingSurface, collapse: list[bool], hold: float = 3.0
) -> tuple[Flow, list[VirtualStrip], Clock]:
    strips = [VirtualStrip(surface, index) for index in range(len(collapse))]
    for index, strip in enumerate(strips):
        strip.set_text(0, f"S{index + 1}")
    clock = Clock()
    flow = Flow(strips, surface.strips[:3], collapse, lambda index: f"S{index + 1}", hold, clock)
    return flow, strips, clock


def texts(surface: RecordingSurface) -> list[str]:
    return [strip.text[0] for strip in surface.strips[:3]]


async def test_the_first_update_places_from_scratch(surface: RecordingSurface) -> None:
    flow, strips, _ = make_flow(surface, [False, True, False, False])
    # nothing is shown again before: what the strips draw goes to the device where they are configured
    assert texts(surface) == ["", "", ""]
    strips[0].set_text(1, "on")
    assert surface.strips[0].text[1] == "on"
    assert flow.update([False, True, False, False])
    # without waiting for the hold time
    assert texts(surface) == ["S1", "S3", "S4"]
    assert flow.placement == (0, 2, 3)
    assert (flow.position(1), flow.position(2), flow.strip_at(1)) == (None, 1, 2)


async def test_without_a_state_the_strips_take_their_places_and_stay(surface: RecordingSurface) -> None:
    flow, _, clock = make_flow(surface, [False, True, False, False])
    assert flow.update(None)
    assert texts(surface) == ["S1", "S2", "S3"]
    clock.now = 10
    assert not flow.update(None)
    # the first state places from scratch
    assert flow.update([False, True, False, False])
    assert texts(surface) == ["S1", "S3", "S4"]


async def test_a_strip_collapses_after_the_hold_time_and_comes_back_at_once(
    surface: RecordingSurface, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    flow, _, clock = make_flow(surface, [False, True, False, True])
    flow.update([False, False, False, True])
    assert texts(surface) == ["S1", "S2", "S3"]

    assert not flow.update([False, True, False, True])
    clock.now = 2.9
    assert not flow.update([False, True, False, True])
    assert texts(surface) == ["S1", "S2", "S3"]
    clock.now = 3.0
    assert flow.update([False, True, False, True])
    assert texts(surface) == ["S1", "S3", ""]
    assert "Strips: S2 collapses, S3 moves to 2" in caplog.text

    assert flow.update([False, False, False, False])
    assert texts(surface) == ["S1", "S2", "S3"]
    assert "Strips: S2 appears at 2, S3 moves to 3" in caplog.text


async def test_a_strip_that_is_present_but_has_no_room_waits(
    surface: RecordingSurface, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    flow, _, _ = make_flow(surface, [True, False, False, False], hold=0)
    flow.update([True, False, False, False])
    assert texts(surface) == ["S2", "S3", "S4"]
    flow.update([False, False, False, False])
    assert texts(surface) == ["S1", "S2", "S3"]
    assert "Strips: S1 appears at 1, S2 moves to 2, S3 moves to 3, S4 waits" in caplog.text


async def test_nothing_moves_while_the_device_is_busy(surface: RecordingSurface) -> None:
    flow, _, _ = make_flow(surface, [False, True, False], hold=0)
    flow.update([False, False, False])
    assert not flow.update([False, True, False], busy=True)
    assert texts(surface) == ["S1", "S2", "S3"]
    assert flow.update([False, True, False])
    assert texts(surface) == ["S1", "S3", ""]


async def test_a_strip_that_moves_shows_everything_on_its_new_place(surface: RecordingSurface) -> None:
    flow, strips, _ = make_flow(surface, [True, False, False], hold=0)
    strips[1].set_color(Color.CYAN)
    strips[1].set_led(Button.MUTE, Led.ON)
    strips[1].set_fader(0.5)
    flow.update([False, False, False])
    assert surface.strips[1].color == Color.CYAN

    flow.update([True, False, False])
    target = surface.strips[0]
    assert (target.color, target.leds[Button.MUTE], target.text[0]) == (Color.CYAN, Led.ON, "S2")
    await surface.settled()
    # the motor glides to the value of the strip
    assert target.position == target.fader == strips[1].fader
    # the strip of the device that is left over is dark and its fader down
    assert surface.strips[2].text == ["", ""]
    assert surface.strips[2].fader == 0
    # what the strip shows from now on goes to its new place only
    strips[1].set_text(1, "50%")
    assert (target.text[1], surface.strips[1].text[1]) == ("50%", "")
