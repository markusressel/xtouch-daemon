"""
The sound of the channels: a small animation beside a channel that has sound right now, in the list of the channels
and on the cards of the slots; nothing moves while nothing has sound.
"""

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QImage, QPainter
from pytestqt.qtbot import QtBot

from xtouch_daemon.gui.quick.pages.sound import SIZE, Sound, paint_sound, sound_of, sounding


def frame(sound: Sound, at: float) -> QImage:
    image = QImage(SIZE.width(), SIZE.height(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    paint_sound(painter, QRectF(0, 0, SIZE.width(), SIZE.height()), sound, at, "#40c0c0")
    painter.end()
    return image


def painted(image: QImage) -> bool:
    return any(image.pixelColor(x, y).alpha() > 0 for x in range(image.width()) for y in range(image.height()))


def test_each_type_of_channel_with_sound_moves_its_own_way():
    assert sound_of("output") is sound_of("apps") is Sound.BARS
    assert sound_of("input") is Sound.RIPPLE
    assert sound_of("person") is Sound.PULSE
    # their values have no sound
    assert sound_of("homeassistant") is None
    assert sound_of("custom") is None
    for sound in Sound:
        assert painted(frame(sound, 0.0))
        # a moment later it looks different
        assert frame(sound, 0.0) != frame(sound, 0.3)


def test_the_clock_runs_only_while_a_channel_has_sound(qtbot: QtBot):
    clock = sounding()
    assert not clock.timer.isActive()
    with qtbot.waitSignal(clock.changed):
        clock.show(("out",))
    assert clock.sounds("out")
    assert not clock.sounds("browser")
    assert clock.timer.isActive()
    with qtbot.waitSignal(clock.tick):
        pass
    # the same channels: nothing to tell
    with qtbot.assertNotEmitted(clock.changed):
        clock.show(("out",))
    clock.show(())
    assert not clock.timer.isActive()
