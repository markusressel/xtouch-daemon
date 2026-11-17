"""
The desk: events of the device go to the presenter bound to their strip, releases to whoever got the press, the hands
on the device, the chord of Solo buttons, the meters.
"""

import asyncio

import pytest

from tests.support.audio import output
from tests.support.daemon import QUIET
from tests.support.hardware import RecordingSurface
from tests.support.tasks import settle
from xtouch_daemon.audio.meter import CaptureTarget, Lit, Reading
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.values import MeterPoint
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import METER_MAX, Button
from xtouch_daemon.runtime import desk as desk_module
from xtouch_daemon.runtime.desk import Desk

SPEAKER = CaptureTarget("speaker", monitor=True)
STATE = AudioState(outputs=(output("speaker", 50),), default_output="speaker")


class Recorder:
    """A presenter that records what it got; its meter shows `targets`, or without audio `held`."""

    def __init__(self, targets: set[CaptureTarget] | None = None, held: Reading | None = None) -> None:
        self.events: list[tuple[str, object]] = []
        self.targets = targets or set()
        self.held = held
        self.points: list[MeterPoint] = []

    def on_fader(self, fraction: float) -> None:
        self.events.append(("fader", round(fraction, 2)))

    def on_touch(self, touched: bool) -> None:
        self.events.append(("touch", touched))

    def on_button(self, button: Button, pressed: bool) -> None:
        self.events.append((button.name, pressed))

    def on_encoder(self, steps: int) -> None:
        self.events.append(("encoder", steps))

    def on_encoder_press(self, pressed: bool) -> None:
        self.events.append(("push", pressed))

    def meter_targets(self, state: AudioState) -> set[CaptureTarget]:
        return self.targets if state.connected else set()

    def is_playing(self, target: CaptureTarget, state: AudioState) -> bool:
        return state.connected

    def target_gain(self, target: CaptureTarget, state: AudioState) -> float | None:
        return 0.5 if state.connected else None

    def held_meter(self, point: MeterPoint) -> Reading | None:
        self.points.append(point)
        return self.held


def test_the_events_of_a_strip_go_to_its_presenter(surface: RecordingSurface) -> None:
    desk = Desk(surface)
    first, second = Recorder(), Recorder()
    desk.bind(0, first)
    desk.bind(1, second)
    surface.on_event(protocol.FaderMoved(0, protocol.fader_value(0.5)))
    surface.on_event(protocol.ButtonPressed(1, Button.MUTE, True))
    surface.on_event(protocol.ButtonPressed(1, Button.MUTE, False))
    surface.on_event(protocol.EncoderTurned(1, -2))
    surface.on_event(protocol.EncoderPressed(1, True))
    surface.on_event(protocol.EncoderPressed(1, False))
    # nobody on strip 3
    surface.on_event(protocol.FaderMoved(2, 0))
    surface.on_event(protocol.EncoderTurned(2, 1))
    surface.on_event(protocol.ButtonPressed(2, Button.SELECT, True))
    assert first.events == [("fader", 0.5)]
    assert second.events == [("MUTE", True), ("MUTE", False), ("encoder", -2), ("push", True), ("push", False)]


def test_a_release_goes_to_whoever_got_the_press(surface: RecordingSurface) -> None:
    desk = Desk(surface)
    old, new = Recorder(), Recorder()
    desk.bind(0, old)
    surface.on_event(protocol.ButtonPressed(0, Button.SELECT, True))
    surface.on_event(protocol.EncoderPressed(0, True))
    desk.bind(0, new)
    surface.on_event(protocol.ButtonPressed(0, Button.SELECT, False))
    surface.on_event(protocol.EncoderPressed(0, False))
    assert old.events == [("SELECT", True), ("push", True), ("SELECT", False), ("push", False)]
    assert new.events == []
    # the next press is the new one's
    surface.on_event(protocol.ButtonPressed(0, Button.SELECT, True))
    assert new.events == [("SELECT", True)]


def test_a_finger_on_fader_2_during_a_change_of_slot_7_keeps_slot_2_and_its_new_presenter_knows(
    surface: RecordingSurface,
) -> None:
    desk = Desk(surface)
    second, seventh, other, new = Recorder(), Recorder(), Recorder(), Recorder()
    desk.bind(1, second)
    desk.bind(6, seventh)
    surface.on_event(protocol.FaderTouched(1, True))
    assert desk.held_slots() == {2}

    desk.bind(6, other)
    desk.bind(1, second)  # the same presenter again: nothing happens
    assert second.events == [("touch", True)]
    assert seventh.events == other.events == []

    # slot 2 changes after all (a layout switch of the old format): the fader goes over to the new presenter
    desk.bind(1, new)
    surface.on_event(protocol.FaderMoved(1, protocol.fader_value(0.25)))
    surface.on_event(protocol.FaderTouched(1, False))
    assert second.events == [("touch", True), ("touch", False)]
    assert new.events == [("touch", True), ("fader", 0.25), ("touch", False)]


def test_unbound_presenters_let_go_of_the_fader(surface: RecordingSurface) -> None:
    desk = Desk(surface)
    gone, stays = Recorder(), Recorder()
    desk.bind(0, gone)
    desk.bind(1, stays)
    surface.on_event(protocol.FaderTouched(0, True))
    desk.unbind([gone])
    assert desk.presenters[:2] == [None, stays]
    assert gone.events == [("touch", True), ("touch", False)]
    # bound again under the finger, to a strip nobody had
    desk.bind(0, stays)
    surface.on_event(protocol.FaderTouched(0, False))
    assert gone.events == [("touch", True), ("touch", False)]
    assert stays.events == [("touch", True), ("touch", False)]


def test_the_hands_on_the_device(surface: RecordingSurface) -> None:
    desk = Desk(surface)
    free: list[int] = []
    desk.on_hands_free = lambda: free.append(1)
    assert not desk.busy
    surface.on_event(protocol.FaderTouched(3, True))
    surface.on_event(protocol.ButtonPressed(0, Button.REC, True))
    surface.on_event(protocol.EncoderPressed(5, True))
    assert desk.busy
    assert desk.held_slots() == {1, 4, 6}
    surface.on_event(protocol.FaderTouched(3, False))
    surface.on_event(protocol.ButtonPressed(0, Button.REC, False))
    assert free == []
    surface.on_event(protocol.EncoderPressed(5, False))
    assert free == [1]
    assert not desk.busy
    assert desk.held_slots() == frozenset()
    # a turn is no hand on the device
    surface.on_event(protocol.EncoderTurned(5, 1))
    assert free == [1]


def test_the_chord_of_solo_buttons(surface: RecordingSurface) -> None:
    chords: list[int] = []
    desk = Desk(surface, frozenset({0, 7}), lambda: chords.append(1))

    def solo(strip: int, pressed: bool) -> None:
        surface.on_event(protocol.ButtonPressed(strip, Button.SOLO, pressed))

    solo(0, True)
    solo(3, True)  # not part of the chord
    assert chords == []
    solo(7, True)
    assert chords == [1]
    # once per chord: both have to be let go first
    solo(7, False)
    solo(7, True)
    assert chords == [1]
    solo(0, False)
    solo(7, False)
    solo(0, True)
    solo(7, True)
    assert chords == [1, 1]
    desk.chord = frozenset()
    solo(0, False)
    solo(0, True)
    assert chords == [1, 1]


async def test_a_capture_goes_on_when_another_presenter_shows_the_same(surface: RecordingSurface) -> None:
    desk = Desk(surface, capture_command=QUIET)
    meter = desk.meters[0]
    desk.bind(0, Recorder({SPEAKER}), "post_fader")
    assert meter.point == "post_fader"
    assert meter.targets == set()  # from the next watch() on
    desk.watch(STATE)
    capture = meter._captures[SPEAKER]
    assert meter._playing(SPEAKER)
    assert meter._gain(SPEAKER) == 0.5
    # a new mixer: its presenter shows the speaker too
    desk.bind(0, Recorder({SPEAKER}))
    desk.watch(STATE)
    assert meter._captures[SPEAKER] is capture
    assert meter.point == "pre_fader"
    # nobody on the strip: nothing plays there
    desk.bind(0, None)
    assert not meter._playing(SPEAKER)
    assert meter._gain(SPEAKER) is None
    desk.watch(STATE)
    assert meter.targets == set()
    desk.close()
    await desk.wait_closed()


async def test_the_meters_show_the_level_or_what_the_presenter_holds(
    surface: RecordingSurface, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(desk_module, "METER_INTERVAL", 0.001)
    desk = Desk(surface, capture_command=QUIET)
    desk.bind(0, Recorder())
    desk.bind(1, held := Recorder(held=Lit(5)), "post_fader")
    desk.meters[2].feed(1.0)  # a clip, on a strip nobody is on
    task = asyncio.create_task(desk.run())
    await asyncio.sleep(0.01)
    task.cancel()
    await settle()
    assert surface.meters(0) == []
    assert surface.meters(1)[-1] == 5
    assert held.points[-1] == "post_fader"
    assert surface.meters(2)[0] == METER_MAX
