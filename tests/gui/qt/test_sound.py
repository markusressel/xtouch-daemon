"""
The sound of the channels: a small animation beside a channel that has sound right now, in the list of the channels
and on the cards of the slots; nothing moves while nothing has sound.
"""

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from pytestqt.qtbot import QtBot

from tests.support.gui import strip_state
from xtouch_daemon.gui.qt.fields.rich_items import SOUND_ROLE, ChannelSound
from xtouch_daemon.gui.qt.fields.sound import SIZE, Sound, SoundBadge, paint_sound, sound_of, sounding
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.messages import Snapshot


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


def test_a_badge_is_empty_while_its_channel_has_no_sound(qtbot: QtBot):
    badge = SoundBadge("out", Sound.BARS)
    qtbot.addWidget(badge)
    badge.show()
    # its room stays: nothing beside it moves when the sound comes
    assert badge.size() == SIZE
    quiet = badge.grab().toImage()
    assert badge.toolTip() == ""
    sounding().show(("out",))
    assert badge.grab().toImage() != quiet
    assert badge.toolTip() == "out has sound now"
    # the next frame
    with qtbot.waitSignal(sounding().tick):
        pass
    sounding().show(("browser",))
    assert badge.grab().toImage() == quiet


def test_the_daemon_tells_which_channels_have_sound(window: MainWindow):
    window.show()
    window.show_page("channels")
    listed = window.channels_page.list
    items = [listed.item(row) for row in range(listed.count())]
    sounds = {
        item.data(Qt.ItemDataRole.UserRole)[1]: item.data(SOUND_ROLE)
        for item in items
        if item is not None and item.data(Qt.ItemDataRole.UserRole) is not None
    }
    assert sounds["out"] == ChannelSound("out", Sound.BARS)
    assert sounds["browser"] == ChannelSound("browser", Sound.BARS)
    quiet = listed.grab().toImage()

    strips = tuple(strip_state() for _ in range(8))
    window.live.snapshot = Snapshot("x", True, True, None, strips, sounding=("out",))
    window.refresh_preview()
    assert sounding().sounds("out")
    # beside the name of the channel in the list
    assert listed.grab().toImage() != quiet
    # and after it on the card of its slot
    window.show_page("slots")
    (badge,) = [badge for badge in window.slots_page.lists[0].findChildren(SoundBadge) if badge.channel == "out"]
    assert badge.active
    assert badge.sound is Sound.BARS
    # gone with the daemon
    window.live.snapshot = None
    window.refresh_preview()
    assert not badge.active
    assert listed.grab().toImage() == quiet


def test_the_hue_is_that_of_the_channels():
    image = frame(Sound.PULSE, 0.25)
    middle = image.pixelColor(SIZE.width() // 2, SIZE.height() // 2)
    assert middle.hue() == QColor("#40c0c0").hue()
