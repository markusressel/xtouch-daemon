"""
The rows of a slot card (`StackList`): a change of a row moves only that row.
"""

from typing import Any

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from xtouch_daemon.gui.domain.slot_stacks import rows
from xtouch_daemon.gui.qt.motion import Fade, picture_of
from xtouch_daemon.gui.qt.pages.slot_cards import StackList
from xtouch_daemon.gui.qt.theme.tokens import Motion

VALUES: dict[str, Any] = {
    "channel": {"out": {"type": "output"}, "voip": {"type": "voip"}},
    "slots": {"1": ["out if present", "voip", "-"]},
}


@pytest.fixture
def stack(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> StackList:
    stack = StackList()
    qtbot.addWidget(stack)
    stack.resize(400, 300)
    stack.show()
    qtbot.waitExposed(stack)
    stack.fill(rows(VALUES, 1), 0, {}, VALUES)
    monkeypatch.setattr(Motion, "enabled", True)
    return stack


def widgets(stack: StackList) -> list[QWidget | None]:
    return [stack.itemWidget(stack.item(index)) for index in range(stack.count())]  # pyright: ignore[reportArgumentType]


def fades(stack: StackList) -> list[Fade]:
    return stack.findChildren(Fade)


def test_only_the_rows_that_change_fade_through(stack: StackList):
    before = widgets(stack)
    # the second candidate is shown now: the first is passed, the second shown, the third stays unreached
    stack.fill(rows(VALUES, 1), 1, {0: "out is not connected"}, VALUES)
    after = widgets(stack)
    assert after[2] is before[2]
    assert after[0] is not before[0]
    assert after[1] is not before[1]
    changed = sorted(fade.geometry().y() for fade in fades(stack))
    assert changed == [stack.visualItemRect(stack.item(row)).y() for row in (0, 1)]  # pyright: ignore[reportArgumentType]
    # through the color of the card: the old and the new text never show at once
    assert all(isinstance(fade.behind, QColor) for fade in fades(stack))


def test_rows_that_come_fade_in_and_rows_that_go_fade_out(stack: StackList):
    more = {**VALUES, "slots": {"1": ["out if present", "voip", "apps", "-"]}}
    stack.fill(rows(more, 1), 0, {}, more)
    # `apps` takes the place of `-`, which moves down into a new row
    (new,) = [fade for fade in fades(stack) if fade.picture.width() == 1]
    assert new.geometry() == stack.visualItemRect(stack.item(3))  # pyright: ignore[reportArgumentType]
    for fade in fades(stack):
        fade.animation.stop()
        fade.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    last = stack.visualItemRect(stack.item(stack.count() - 1))  # pyright: ignore[reportArgumentType]
    stack.fill(rows(VALUES, 1), 0, {}, VALUES)
    # the last row goes, and fades out where it was
    assert last in [fade.geometry() for fade in fades(stack) if fade.behind is None]


def test_a_change_of_the_configuration_makes_every_row_anew(stack: StackList):
    before = widgets(stack)
    VALUES_CHANGED = {**VALUES, "channel": {"out": {"type": "output", "color": "red"}, "voip": {"type": "voip"}}}
    stack.fill(rows(VALUES_CHANGED, 1), 0, {}, VALUES_CHANGED)
    assert all(new is not old for new, old in zip(widgets(stack), before, strict=True))


def test_the_same_rows_change_nothing(stack: StackList):
    before = widgets(stack)
    stack.fill(rows(VALUES, 1), 0, {}, VALUES)
    assert widgets(stack) == before
    assert fades(stack) == []


def test_nothing_fades_while_the_window_draws_nothing(stack: StackList):
    stack.setUpdatesEnabled(False)
    stack.fill(rows(VALUES, 1), 1, {}, VALUES)
    stack.setUpdatesEnabled(True)
    assert fades(stack) == []


def test_a_picture_has_nothing_behind_the_widget(stack: StackList):
    row = widgets(stack)[0]
    assert row is not None
    picture = picture_of(row).toImage()
    # the corner of a row is the card under it, which the picture leaves out
    assert picture.pixelColor(0, 0).alpha() == 0
