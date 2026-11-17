"""
The desk: events of the device go to the presenter bound to their strip, releases to whoever got the press, the hands
on the device, the chord of Solo buttons.
"""

from tests.support.hardware import RecordingSurface
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button
from xtouch_daemon.runtime.desk import Desk


class Recorder:
    """A presenter that records what it got."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

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
