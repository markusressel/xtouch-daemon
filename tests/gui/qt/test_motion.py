"""
Motion in the GUI (`gui/qt/motion.py`): fades and reveals, driven to a time of the test's choosing.
"""

import pytest
from PyQt6.QtCore import QEvent, QVariantAnimation
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from xtouch_daemon.gui.qt.motion import REVEAL, UNBOUNDED, Fade, fading, reveal
from xtouch_daemon.gui.qt.pages.base import Stack
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Motion


@pytest.fixture(autouse=True)
def motion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Motion, "enabled", True)


@pytest.fixture
def column(qtbot: QtBot) -> tuple[QWidget, QLabel, QLabel]:
    """A window with two rows."""
    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    first, second = QLabel("first"), QLabel("second")
    layout.addWidget(first)
    layout.addWidget(second)
    layout.addStretch()
    window.resize(300, 200)
    window.show()
    qtbot.waitExposed(window)
    return window, first, second


def fades(widget: QWidget) -> list[Fade]:
    return widget.findChildren(Fade)


def gone() -> None:
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def test_a_change_fades_from_the_old_picture_to_the_new_look(column: tuple[QWidget, QLabel, QLabel]):
    _, first, _ = column
    with fading(first):
        first.setText("changed")
    (fade,) = fades(first)
    # the old picture over the new look, as big as the widget was
    assert fade.opacity == 1.0
    assert fade.size() == first.size()
    assert not fade.picture.isNull()
    fade.animation.setCurrentTime(Motion.FADE // 2)
    assert 0.0 < fade.opacity < 1.0
    fade.animation.setCurrentTime(Motion.FADE)
    assert fade.opacity == 0.0
    gone()
    assert fades(first) == []


def test_a_change_inside_a_fade_is_part_of_it(column: tuple[QWidget, QLabel, QLabel]):
    window, first, _ = column
    with fading(window):
        with fading(first):
            first.setText("changed")
        set_role(first, "hint")
    assert len(fades(window)) == 1
    assert fades(first) == []


def test_set_role_fades_and_the_same_value_does_nothing(column: tuple[QWidget, QLabel, QLabel]):
    _, first, _ = column
    set_role(first, "hint")
    assert len(fades(first)) == 1
    set_role(first, "hint")
    assert len(fades(first)) == 1


def test_nothing_fades_while_it_doesnt_show_or_motion_is_off(
    column: tuple[QWidget, QLabel, QLabel], monkeypatch: pytest.MonkeyPatch
):
    _, first, second = column
    second.hide()
    with fading(second):
        second.setText("changed")
    assert fades(second) == []
    monkeypatch.setattr(Motion, "enabled", False)
    with fading(first):
        first.setText("changed")
    assert fades(first) == []


def test_a_stack_fades_from_one_part_to_the_other(qtbot: QtBot):
    stack = Stack()
    qtbot.addWidget(stack)
    one, two = QLabel("one"), QLabel("two")
    stack.add(one)
    stack.add(two)
    stack.show_part(one)
    stack.resize(200, 100)
    stack.show()
    qtbot.waitExposed(stack)
    stack.show_part(two)
    assert len(fades(stack)) == 1
    assert one.isHidden()
    assert not two.isHidden()


def animation_of(widget: QWidget) -> QVariantAnimation:
    found = widget.findChild(QVariantAnimation, REVEAL)
    assert found is not None
    return found


def test_a_row_grows_and_fades_in_then_shrinks_and_hides(column: tuple[QWidget, QLabel, QLabel]):
    _, first, second = column
    second.hide()
    QApplication.processEvents()
    full = second.sizeHint().height()

    animation = reveal(second, True)
    assert animation is not None
    # from no height, shown, fading in
    assert not second.isHidden()
    assert second.maximumHeight() == 0
    assert isinstance(second.graphicsEffect(), QGraphicsOpacityEffect)
    animation.setCurrentTime(Motion.RESIZE // 2)
    assert 0 < second.maximumHeight() < full
    effect = second.graphicsEffect()
    assert isinstance(effect, QGraphicsOpacityEffect)
    assert 0.0 < effect.opacity() < 1.0
    # the same way again: the one running goes on
    assert reveal(second, True) is animation
    animation.setCurrentTime(Motion.RESIZE)
    # at its own height, without a bound or a fade
    assert second.maximumHeight() == UNBOUNDED
    assert second.graphicsEffect() is None
    assert not second.isHidden()
    # shown already: nothing to do
    assert reveal(second, True) is None

    QApplication.processEvents()
    animation = reveal(second, False)
    assert animation is not None
    assert not second.isHidden()
    animation.setCurrentTime(Motion.RESIZE // 2)
    assert 0 < second.maximumHeight() < full
    # turned around half way: it grows again from where it is
    back = reveal(second, True)
    assert back is animation
    assert animation.startValue() == second.maximumHeight()
    animation.setCurrentTime(Motion.RESIZE)
    assert not second.isHidden()
    reveal(second, False)
    animation.setCurrentTime(Motion.RESIZE)
    assert second.isHidden()
    assert second.maximumHeight() == UNBOUNDED
    assert first.isVisible()


def test_a_row_of_a_parent_that_doesnt_show_comes_and_goes_at_once(qtbot: QtBot):
    parent = QWidget()
    qtbot.addWidget(parent)
    row = QLabel("row", parent)
    row.hide()
    assert reveal(row, True) is None
    assert not row.isHidden()
    assert reveal(row, False) is None
    assert row.isHidden()
    # without a parent too
    alone = QLabel("alone")
    qtbot.addWidget(alone)
    assert reveal(alone, False) is None
    assert alone.isHidden()


def test_a_reveal_keeps_an_effect_of_the_widget(column: tuple[QWidget, QLabel, QLabel]):
    _, _, second = column
    own = QGraphicsOpacityEffect(second)
    second.setGraphicsEffect(own)
    animation = reveal(second, False)
    assert animation is not None
    animation.setCurrentTime(Motion.RESIZE)
    assert second.isHidden()
    assert second.graphicsEffect() is own
