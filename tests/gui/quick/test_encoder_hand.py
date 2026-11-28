"""
The mouse on the encoder in Play: a drag turns it, a click on the knob pushes it, holding the knob holds it down, a
click on an LED turns it until the ring lights the LED (the LEDs at the ends: all the way), holding an LED turns on.
"""

import pytest
from PyQt6.QtCore import QPointF
from pytestqt.qtbot import QtBot

from tests.support.gui import led_point
from xtouch_daemon.gui.quick.device import encoder_hand
from xtouch_daemon.gui.quick.device.encoder_hand import EXTRA_TURNS, HOLD_MS, EncoderHand
from xtouch_daemon.gui.quick.device.geometry import ENCODER
from xtouch_daemon.strips.knobs import balance_ring

DRAG = 5.0


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    # turned towards an LED a step every 5 ms, not 60
    monkeypatch.setattr(encoder_hand, "TURN_MS", 5)


class Balance:
    """An encoder on the balance, in steps of 5 % (as the daemon turns it): the ring as the daemon shows it."""

    def __init__(self, steps_per_side: int = 20, ends: bool = True) -> None:
        self.value = 0
        self.side = steps_per_side
        self.lights_ends = ends
        self.pushes: list[bool] = []
        self.turns: list[int] = []

    def turn(self, steps: int) -> None:
        self.turns.append(steps)
        self.value = max(-self.side, min(self.side, self.value + steps))

    def position(self) -> int:
        return balance_ring(self.value / self.side)[0]

    def ends(self) -> bool:
        return self.lights_ends and balance_ring(self.value / self.side)[1]


def hand_on(balance: Balance) -> EncoderHand:
    return EncoderHand(balance.turn, balance.pushes.append, balance.position, balance.ends)


def test_a_click_on_an_led_turns_until_the_ring_lights_it(qtbot: QtBot) -> None:
    balance = Balance()
    hand = hand_on(balance)
    hand.press(led_point(9))
    # nothing yet: it may still become a drag
    assert balance.turns == []
    hand.release()
    qtbot.waitUntil(lambda: balance.position() == 9 and not hand._repeat.isActive())
    assert set(balance.turns) == {1}
    # the LED at the end: all the way, until the LEDs at the ends light
    hand.press(led_point(12))
    hand.release()
    qtbot.waitUntil(lambda: balance.value == 20)
    assert balance.ends()
    hand.press(led_point(0))
    hand.release()
    qtbot.waitUntil(lambda: balance.value == -20)


def test_an_end_led_of_a_ring_without_ends_turns_as_far_as_it_goes(qtbot: QtBot) -> None:
    balance = Balance(ends=False)
    hand = hand_on(balance)
    hand.press(led_point(12))
    hand.release()
    qtbot.waitUntil(lambda: not hand._repeat.isActive(), timeout=10_000)
    assert balance.value == 20
    # it gave up after a few steps more at the last position
    assert len(balance.turns) == 20 + EXTRA_TURNS


def test_a_drag_from_an_led_turns_and_aims_at_nothing(qtbot: QtBot) -> None:
    balance = Balance()
    hand = hand_on(balance)
    start = led_point(3)
    hand.press(start)
    hand.move(start + QPointF(DRAG, 0), DRAG)
    assert hand.dragging
    hand.move(start + QPointF(DRAG + 4 * encoder_hand.DRAG_STEP, 0), DRAG)
    # the guide: how far it turned, in steps
    assert hand.turned == (DRAG + 4 * encoder_hand.DRAG_STEP) / encoder_hand.DRAG_STEP
    hand.release()
    assert not hand.dragging
    assert sum(balance.turns) == 5
    qtbot.wait(3 * encoder_hand.TURN_MS)
    assert sum(balance.turns) == 5


def test_holding_an_led_turns_on_after_a_moment(qtbot: QtBot) -> None:
    balance = Balance()
    hand = hand_on(balance)
    hand.press(led_point(11))
    qtbot.wait(HOLD_MS // 2)
    assert balance.turns == []
    qtbot.waitUntil(lambda: balance.position() == 11)
    hand.release()
    turned = len(balance.turns)
    qtbot.wait(3 * encoder_hand.TURN_MS)
    assert len(balance.turns) == turned


def test_holding_the_knob_holds_it_down(qtbot: QtBot) -> None:
    balance = Balance()
    hand = hand_on(balance)
    hand.press(ENCODER)
    qtbot.waitUntil(lambda: balance.pushes == [True])
    hand.release()
    assert balance.pushes == [True, False]
    assert balance.turns == []
