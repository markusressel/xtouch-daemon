"""
The preview of the device: moving strips, and how strips are painted.
"""

import dataclasses
import itertools
import math
from math import cos, radians, sin
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PyQt6.QtGui import QColor, QContextMenuEvent, QFontMetricsF, QImage, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QMenu,
    QWidget,
)
from pytestqt.qtbot import QtBot

from tests.support.gui import CONFIG, Dialogs, MakeWindow, click
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.gui.qt.preview.geometry import (
    CAP_SIZE,
    CENTER_X,
    ENCODER,
    HEIGHT,
    LCD,
    LCD_CELLS,
    MARGIN_X,
    PANEL,
    RING_LEDS,
    RING_RADII,
    SCALE,
    STRIP_TAG,
    WIDTH,
    button_rect,
    meter_led,
    ring_angle,
    slot_position,
    travel_y,
)
from xtouch_daemon.gui.qt.preview.painting import DIM, DIM_TEXT, HW, LCD_PANEL, LCD_TINT, SPRITES_KEPT, _sprites
from xtouch_daemon.gui.qt.preview.panel import MIN_SCALE, SETTLE_MS
from xtouch_daemon.gui.qt.preview.strip_view import StripView
from xtouch_daemon.gui.qt.theme.settings import (
    load_preview_share,
    save_preview_share,
)
from xtouch_daemon.gui.qt.theme.tokens import (
    HARDWARE,
    LCD_COLORS,
    LCD_TEXT,
    LCD_TEXT_OFF,
    THEMES,
    TINT_ALPHA,
    ThemeMode,
)
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.gui.qt.window.splitter import EDITOR_MIN_HEIGHT
from xtouch_daemon.hardware import protocol


def x_of(window: MainWindow, index: int) -> int:
    return window.preview.strips[index].x()


def test_a_dragged_strip_leaves_a_place_and_the_others_make_room(qtbot: QtBot, make_window: MakeWindow, path: Path):
    path.write_text(CONFIG + '\n[[strip]]\ntype = "auto"\n')
    window = make_window()
    preview = window.preview
    first, second, third = (x_of(window, index) for index in range(3))
    view = preview.strips[0]

    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    # a small move is still a click
    qtbot.mouseMove(view, QPoint(52, 51))
    assert not preview.dragging
    qtbot.mouseMove(view, QPoint(50 + third - first, 50))

    assert preview.dragging
    assert view.lifted
    # its place is free and the strips it passed moved over, gliding
    assert preview.drop_target == 2
    # back and forth: the strips change their way (the mouse is where the strip is now)
    qtbot.mouseMove(view, QPoint(50 + second - view.x(), 50))
    assert preview.drop_target == 1
    qtbot.mouseMove(view, QPoint(50 + third - view.x(), 50))
    assert preview.drop_target == 2
    qtbot.waitUntil(lambda: x_of(window, 1) == first and x_of(window, 2) == second)
    assert not window.grab().isNull()

    # dropped beyond the configured strips, it goes to that place: auto strips in between
    qtbot.mouseMove(view, QPoint(50 + 7 * (third - second), 50))
    assert preview.drop_target == 7
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(50 + 7 * (third - second), 50))

    assert not preview.dragging
    assert [strip.type for strip in window.document.strips] == ["apps", "auto", *["auto"] * 5, "output"]
    assert window.selected == 7
    # every view at its own place again (eight strips show the strip list, so the preview may have a new scale)
    places = [x_of(window, index) for index in range(8)]
    assert places == sorted(places)
    assert len({right - left for left, right in itertools.pairwise(places)}) <= 2
    assert window.status.text() == "Moved strip 1 to place 8."


def test_escape_cancels_a_drag(qtbot: QtBot, window: MainWindow):
    preview = window.preview
    view = preview.strips[0]
    home = view.pos()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(view, QPoint(160, 50))
    assert preview.drop_target == 1

    qtbot.keyClick(preview, Qt.Key.Key_Escape)

    assert not preview.dragging
    assert view.pos() == home
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(160, 50))
    assert [strip.type for strip in window.document.strips] == ["output", "apps"]
    # a drag that ends where it started moves nothing either
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(view, QPoint(60, 50))
    qtbot.keyClick(view, Qt.Key.Key_Escape)
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(view, QPoint(60, 50))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(60, 50))
    assert [strip.type for strip in window.document.strips] == ["output", "apps"]
    assert window.history.can_undo is False


def test_strips_that_are_not_configured_do_not_move(qtbot: QtBot, window: MainWindow):
    view = window.preview.strips[6]
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    qtbot.mouseMove(view, QPoint(80, 60))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton)

    assert not window.preview.dragging
    assert window.selected == 6


def test_the_keyboard_selects_and_moves_strips(qtbot: QtBot, window: MainWindow):
    strips = window.preview.strips
    strips[0].setFocus()

    qtbot.keyClick(strips[0], Qt.Key.Key_Right)
    assert window.selected == 1
    qtbot.keyClick(strips[1], Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    assert [strip.type for strip in window.document.strips] == ["apps", "output"]
    assert window.selected == 0
    # not past the ends
    qtbot.keyClick(strips[0], Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(strips[0], Qt.Key.Key_Left)
    assert [strip.type for strip in window.document.strips] == ["apps", "output"]
    # but to a free place: an auto strip comes in between, and goes again with it
    qtbot.keyClick(strips[1], Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert [strip.type for strip in window.document.strips] == ["apps", "auto", "output"]
    qtbot.keyClick(strips[2], Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    assert [strip.type for strip in window.document.strips] == ["apps", "output"]

    qtbot.keyClick(strips[0], Qt.Key.Key_End)
    assert window.selected == 7
    qtbot.keyClick(strips[7], Qt.Key.Key_Delete)
    qtbot.keyClick(strips[7], Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(strips[7], Qt.Key.Key_A)
    # an unconfigured strip doesn't move
    assert len(window.document.strips) == 2
    assert window.selected == 7
    qtbot.keyClick(strips[7], Qt.Key.Key_Home)
    assert window.selected == 0

    # the other strips stay where they are
    qtbot.keyClick(strips[0], Qt.Key.Key_Delete)
    assert [strip.type for strip in window.document.strips] == ["auto", "output"]
    assert window.status.text() == "Removed strip 1, its place is an auto strip now. Ctrl+Z brings it back."
    qtbot.keyClick(strips[1], Qt.Key.Key_Delete)
    assert window.document.strips == []
    assert window.status.text() == "Removed strip 2. Ctrl+Z brings it back."


def test_the_menu_of_a_strip(qtbot: QtBot, window: MainWindow):
    menu = window.preview.menu_for(1)
    left, right, _, remove = menu.actions()
    assert left.text() == "Move left\tCtrl+Left"
    # also to a free place
    assert right.isEnabled()
    assert not window.preview.menu_for(0).actions()[0].isEnabled()

    left.trigger()
    assert [strip.type for strip in window.document.strips] == ["apps", "output"]
    window.preview.menu_for(0).actions()[1].trigger()
    assert [strip.type for strip in window.document.strips] == ["output", "apps"]
    remove.trigger()
    assert [strip.type for strip in window.document.strips] == ["output"]

    (configure,) = window.preview.menu_for(4).actions()
    configure.trigger()
    assert len(window.document.strips) == 5
    assert window.selected == 4


def test_a_strip_that_is_not_configured_is_configured_by_a_double_click(qtbot: QtBot, window: MainWindow):
    qtbot.mouseDClick(window.preview.strips[3], Qt.MouseButton.LeftButton)
    assert len(window.document.strips) == 4
    # a configured one stays as it is
    qtbot.mouseDClick(window.preview.strips[0], Qt.MouseButton.LeftButton)
    assert len(window.document.strips) == 4


def test_the_context_menu_opens_on_the_strip(qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch):
    shown: list[list[str]] = []
    monkeypatch.setattr(QMenu, "exec", lambda menu, *args: shown.append([a.text() for a in menu.actions()]))
    view = window.preview.strips[5]
    qtbot.mousePress(view, Qt.MouseButton.RightButton)

    view.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), view.mapToGlobal(QPoint())))

    assert shown == [["Configure strip 6"]]
    assert window.selected == 5


def show_state(view: StripView, **changes: object) -> QImage:
    """The strip with its state changed, as painted."""
    face = view.face
    view.show_face(dataclasses.replace(face, state=dataclasses.replace(face.state, **changes)), False)
    image = view.grab().toImage()
    # its pixels per logical unit of the strip: the zoom times the scale of the preview
    image.setDevicePixelRatio(image.devicePixelRatio() * view.preview.scale)
    return image


def pixel(image: QImage, point: QPointF) -> QColor:
    """The color at a point of the strip, in logical units, at any zoom and scale."""
    return image.pixelColor((point * image.devicePixelRatio()).toPoint())


def test_lit_leds_show_their_colors(window: MainWindow):
    view = window.preview.strips[0]
    mute, meter = button_rect(2).center(), meter_led(1).center()
    dark = show_state(view, meter=0)

    # what the live view shows: Mute lit, the meter a little up
    lit = show_state(view, leds={**view.face.state.leds, "mute": "on"}, meter=3)

    assert pixel(lit, meter).lightness() > pixel(dark, meter).lightness() + 60
    assert pixel(lit, mute).red() > 200 > pixel(lit, mute).green()
    # off, the buttons are gray, with a hint of their color
    assert abs(pixel(dark, mute).red() - pixel(dark, mute).green()) < 30
    assert pixel(lit, meter).green() > 150 > pixel(lit, meter).red()


def test_the_meter_has_7_leds_for_the_level_and_the_clip_led(window: MainWindow):
    view = window.preview.strips[0]
    clip, top = meter_led(7).center(), meter_led(6).center()

    loudest = show_state(view, meter=protocol.METER_SIGNAL_MAX)

    # the loudest audio lights the orange LEDs, not the red one above them
    assert pixel(loudest, top).red() > 200
    assert 200 > pixel(loudest, top).green() > 100
    assert pixel(loudest, clip).red() < 100
    assert pixel(show_state(view, meter=protocol.METER_SIGNAL_MAX - 1), top).red() < 100
    # a clip lights it too
    clipped = show_state(view, meter=protocol.METER_MAX)
    assert pixel(clipped, clip).red() > 200
    assert pixel(clipped, clip).green() < 100


def ring_led(led: int) -> QPointF:
    """The middle of the LED `led` (0..12) of the ring."""
    angle = radians(ring_angle(led))
    radius = sum(RING_RADII) / 2
    return ENCODER + QPointF(cos(angle), -sin(angle)) * radius


def test_the_ring_lights_the_middle_11_of_its_13_leds(window: MainWindow):
    view = window.preview.strips[0]
    assert ring_angle(0) == 240
    assert ring_angle(RING_LEDS - 1) == -60

    full = show_state(view, ring=protocol.RING_MAX, ring_mode="wrap")
    centered = show_state(view, ring=6, ring_mode="dot")

    for led in range(1, RING_LEDS - 1):
        assert pixel(full, ring_led(led)).red() > 200
    for led in (0, RING_LEDS - 1):
        assert pixel(full, ring_led(led)).red() < 100
    # the middle position is the LED at the top
    assert pixel(centered, ring_led(6)).red() > 200
    assert pixel(centered, ring_led(5)).red() < 100


def test_the_scale_has_0_db_where_100_percent_is():
    marks = {mark.label: mark.at for mark in SCALE}
    assert marks["0"] == BehaviorConfig().unity_at / 100
    assert marks["10"] == pytest.approx(1)
    assert marks["-∞"] == 0
    assert [mark.at for mark in SCALE] == sorted(marks.values(), reverse=True)


@pytest.mark.parametrize("label", ["10", "0", "-20", "-∞"])
def test_the_middle_of_the_cap_shows_the_value(window: MainWindow, label: str):
    at = next(mark.at for mark in SCALE if mark.label == label)
    view = window.preview.strips[0]

    image = show_state(view, fader=at, touched=False)

    # the dark line across the middle of the cap is on the mark
    x = CENTER_X + 10
    half = int(CAP_SIZE.height() / 2) - 2
    mark = round(travel_y(at))
    darkest = min(range(mark - half, mark + half), key=lambda y: pixel(image, QPointF(x, y)).lightness())
    assert abs(darkest - mark) <= 1
    # the cap stays clear of the buttons and of the tag at the bottom
    assert travel_y(1) - CAP_SIZE.height() / 2 > button_rect(3).bottom() + 10
    assert travel_y(0) + CAP_SIZE.height() / 2 < STRIP_TAG.top()


def test_rec_solo_and_mute_are_square_and_select_wider_below_them():
    rec, solo, mute, select = (button_rect(row) for row in range(4))

    for button in (rec, solo, mute):
        assert button.width() == button.height()
        assert button.center().x() == select.center().x()
    assert select.width() > rec.width()
    assert rec.bottom() < solo.top() < mute.top() < select.top()


def test_the_lcd_fits_7_characters_per_line_and_a_line_between_them(window: MainWindow):
    view = window.preview.strips[0]
    metrics = QFontMetricsF(view.lcd_font)
    cells = LCD_CELLS
    assert metrics.horizontalAdvance("W") * protocol.LCD_CELL_WIDTH <= cells.width()
    assert 2 * metrics.capHeight() < cells.height()
    face = view.face
    middle = QPointF(cells.center().x() + 0.5, cells.top() + (cells.height() - 2) / 2 + 1)

    rim = QPointF(LCD.left() + 2.4, LCD.center().y())
    panel = QPointF(cells.left() + 1, cells.center().y() - 6)

    # a negative display: the backlight around a dark panel, and through it in the line and the characters
    image = show_state(view, color="blue", text=("Browser", "Phones "))
    for point in (rim, middle):
        assert pixel(image, point).blue() > 200
    assert pixel(image, panel).lightness() < 30
    lit = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())]
    assert any(color.blue() > 200 and color.red() < 120 for color in lit)
    # the backlight off: all dark
    image = show_state(view, color="off", text=("Browser", "Phones "))
    for point in (rim, middle, panel):
        assert pixel(image, point).lightness() < 50
    # dimmed: a dim rim, but characters that can still be read
    view.show_face(dataclasses.replace(face, state=dataclasses.replace(face.state, color="blue"), dimmed=True), False)
    image = view.grab().toImage()
    image.setDevicePixelRatio(image.devicePixelRatio() * view.preview.scale)
    assert pixel(image, rim).blue() < 120
    assert pixel(image, middle).blue() > 150
    view.show_face(face, False)


def test_a_dragged_strip_is_outlined_and_its_place_shown(qtbot: QtBot, window: MainWindow):
    preview = window.preview
    edge = preview.to_widget(QPointF(3, 150)) - preview.to_widget(QPointF())
    # below the lifted strip, where the place it goes to shows on the panel
    place = preview.to_widget(QPointF(slot_position(0)) + QPointF(WIDTH / 2, HEIGHT - 6))
    strip_before = preview.strips[1].grab().toImage().pixelColor(edge)
    place_before = preview.grab().toImage().pixelColor(place)

    preview.start_drag(1, 10)
    preview.drag_to(preview.to_widget(QPointF(MARGIN_X + 10, 0)).x())

    assert preview.drop_target == 0
    # the strip that was there made room
    qtbot.waitUntil(lambda: preview.strips[0].pos() == preview.slot_point(1))
    assert preview.strips[1].grab().toImage().pixelColor(edge).blue() > strip_before.blue()
    assert preview.grab().toImage().pixelColor(place).blue() > place_before.blue() + 10
    preview.cancel_drag()


def drag_handle(window: MainWindow, share: float, release: bool = True) -> None:
    """Drags the handle between the preview and the editor to `share` of the height, as a hand does."""
    handle = window.splitter.handle(1)
    assert handle is not None
    grip = QPointF(handle.rect().center())
    send_mouse(handle, QEvent.Type.MouseButtonPress, grip, Qt.MouseButton.LeftButton)
    top, bottom = window.splitter.sizes()
    window.splitter.moveSplitter(round((top + bottom) * share), 1)
    QApplication.processEvents()
    if release:
        send_mouse(handle, QEvent.Type.MouseButtonRelease, grip, Qt.MouseButton.NoButton)


def send_mouse(widget: QWidget, kind: QEvent.Type, at: QPointF, buttons: Qt.MouseButton) -> None:
    """A press, move or release of the left button at `at` in `widget`."""
    where = QPointF(widget.mapToGlobal(at))
    event = QMouseEvent(kind, at, where, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def test_the_preview_scales_to_the_space_it_gets(window: MainWindow):
    preview = window.preview
    large = preview.scale
    assert preview.minimumSizeHint().height() == round(PANEL.height() * MIN_SCALE)

    drag_handle(window, 0.1)

    # down to its minimum, keeping its proportions, centered
    assert preview.scale < large
    assert preview.height() >= preview.minimumSizeHint().height()
    assert preview.scale == pytest.approx(min(preview.width() / PANEL.width(), preview.height() / PANEL.height()))
    panel = PANEL * preview.scale
    assert preview.origin.x() == pytest.approx((preview.width() - panel.width()) / 2)
    assert preview.origin.y() == pytest.approx((preview.height() - panel.height()) / 2)
    for index, view in enumerate(preview.strips):
        assert view.pos() == preview.slot_point(index)
        assert view.width() == math.ceil(WIDTH * preview.scale)
    # the editor keeps its room
    assert window.tabs.height() >= EDITOR_MIN_HEIGHT
    handle = window.splitter.handle(1)
    assert handle is not None
    assert handle.cursor().shape() == Qt.CursorShape.SplitVCursor
    assert "Drag" in handle.toolTip()
    assert not handle.grab().isNull()


def test_strips_are_picked_and_dragged_at_any_scale(qtbot: QtBot, window: MainWindow):
    preview = window.preview
    drag_handle(window, 0.1)
    assert preview.scale < 0.8
    # the strip under a point in the middle of its place
    third = preview.to_widget(QPointF(slot_position(2)) + QPointF(WIDTH / 2, 250))
    view = preview.childAt(third)
    assert view is preview.strips[2]

    click(qtbot, view)
    assert window.selected == 2

    first = preview.strips[0]
    grab = QPoint(first.width() // 2, first.height() // 2)
    qtbot.mousePress(first, Qt.MouseButton.LeftButton, pos=grab)
    qtbot.mouseMove(first, grab + QPoint(preview.slot_point(1).x() - first.x(), 0))
    assert preview.drop_target == 1
    # the place under the strip follows the scale too: just short of the middle between two places
    middle = (preview.slot_point(0).x() + preview.slot_point(1).x()) / 2
    qtbot.mouseMove(first, grab + QPoint(round(middle - first.x()) + 2, 0))
    assert preview.drop_target == 1
    qtbot.mouseMove(first, grab + QPoint(round(middle - first.x()) - 2, 0))
    assert preview.drop_target == 0
    qtbot.mouseRelease(first, Qt.MouseButton.LeftButton, pos=grab)
    assert not preview.dragging


def test_strips_are_drawn_again_only_when_they_show_something_else(qtbot: QtBot, window: MainWindow):
    preview = window.preview
    qtbot.waitUntil(lambda: not preview.resizing)
    view = preview.strips[0]
    show_state(view)
    picture, shown, printed = view.picture, view.shown, view.printed

    # painted again (e.g. the blink of another strip): the same picture
    view.grab()
    assert view.picture is picture
    # what moves all the time is put together from small pictures, over the same picture of what it shows
    show_state(view, meter=6, ring=3, fader=0.5, touched=True)
    assert view.picture is not picture
    assert view.shown is shown
    # a new text: drawn again, on the same picture of its printed parts
    show_state(view, text=("Other", ""))
    assert view.shown is not shown
    assert view.printed is printed


def test_small_pictures_are_dropped_when_there_are_too_many(window: MainWindow):
    view = window.preview.strips[0]
    sprites = _sprites
    sprites.clear()
    show_state(view, meter=6)
    assert sprites
    some = next(iter(sprites.values()))
    sprites.update({("odd", index): some for index in range(SPRITES_KEPT)})

    image = show_state(view, meter=9)

    # dropped, and the ones that are missing drawn again
    assert len(sprites) < SPRITES_KEPT
    assert not any(key[0] == "odd" for key in sprites)
    assert pixel(image, meter_led(4).center()) == QColor(HW.meter_mid)


def test_while_the_size_changes_strips_scale_their_picture(qtbot: QtBot, window: MainWindow):
    preview = window.preview
    qtbot.waitUntil(lambda: not preview.resizing)
    views = preview.strips
    for view in views:
        view.grab()
    before = [view.picture for view in views]

    drag_handle(window, 0.1, release=False)

    assert preview.resizing
    for view in views:
        view.grab()
    # the pictures of before, scaled: much faster than drawing them
    assert [view.picture for view in views] == before
    # what shows something new is drawn at once, sharp
    show_state(views[0], text=("Other", ""))
    picture = views[0].picture
    assert picture is not None
    assert picture.scale == preview.scale
    # also while the hand rests, until it lets go of the handle
    qtbot.wait(SETTLE_MS * 2)
    assert preview.resizing
    # nothing is saved before
    assert load_preview_share() is None
    handle = window.splitter.handle(1)
    assert handle is not None
    send_mouse(handle, QEvent.Type.MouseButtonRelease, QPointF(), Qt.MouseButton.NoButton)
    assert not preview.resizing
    assert load_preview_share() == pytest.approx(window.splitter.share)
    for view in views:
        view.grab()
        assert view.picture is not None
        assert view.picture.scale == preview.scale


def test_the_handle_follows_many_moves_of_the_mouse_at_once(window: MainWindow):
    handle = window.splitter.handle(1)
    assert handle is not None
    grip = QPointF(handle.rect().center())
    send_mouse(handle, QEvent.Type.MouseButtonPress, grip, Qt.MouseButton.LeftButton)
    top = window.splitter.sizes()[0]
    moves: list[int] = []
    window.splitter.splitterMoved.connect(lambda position, _: moves.append(position))

    for step in range(1, 6):
        send_mouse(handle, QEvent.Type.MouseMove, grip - QPointF(0, 10 * step), Qt.MouseButton.LeftButton)
    assert window.splitter.sizes()[0] == top
    QApplication.processEvents()

    # once, to where the mouse is now
    assert len(moves) == 1
    assert window.splitter.sizes()[0] == top - 50
    # the last move before it is let go counts too (10 above the grip, which has moved along)
    send_mouse(handle, QEvent.Type.MouseMove, grip - QPointF(0, 10), Qt.MouseButton.LeftButton)
    send_mouse(handle, QEvent.Type.MouseButtonRelease, grip, Qt.MouseButton.NoButton)
    assert window.splitter.sizes()[0] == top - 60
    assert not window.preview.resizing
    QApplication.processEvents()
    assert len(moves) == 2


def test_a_new_size_ends_a_drag(window: MainWindow):
    preview = window.preview
    preview.start_drag(0, 10)
    preview.drag_to(preview.slot_point(2).x())

    drag_handle(window, 0.1)

    assert not preview.dragging
    assert [view.pos() for view in preview.strips] == [preview.slot_point(index) for index in range(8)]


def test_the_size_of_the_preview_is_kept(make_window: MakeWindow, isolated: Dialogs):
    window = make_window()
    assert window.preview_share is None
    assert load_preview_share() is None
    natural = window.preview.scale

    drag_handle(window, 0.4)

    share = window.splitter.share
    assert load_preview_share() == pytest.approx(share)
    assert window.session().preview_share == pytest.approx(share)
    # the next start, and the window after a new zoom
    for after in (make_window(), make_window(session=window.session())):
        assert after.splitter.share == pytest.approx(share, abs=0.01)
        assert after.preview.scale < natural


def test_a_kept_size_of_the_preview_that_is_none_is_ignored(isolated: Dialogs):
    save_preview_share(0.4)
    assert load_preview_share() == 0.4
    for odd in ("huge", 0, 1.5):
        QSettings().setValue("preview_share", odd)
        assert load_preview_share() is None


def luminance(color: str) -> float:
    def channel(value: int) -> float:
        value_ = value / 255
        return value_ / 12.92 if value_ <= 0.04045 else ((value_ + 0.055) / 1.055) ** 2.4

    rgb = QColor(color)
    return 0.2126 * channel(rgb.red()) + 0.7152 * channel(rgb.green()) + 0.0722 * channel(rgb.blue())


def contrast(foreground: str, background: str) -> float:
    """The contrast ratio of WCAG 2.2."""
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def over(color: str, background: str, alpha: int) -> str:
    """A translucent color on a background."""
    top, bottom = QColor(color).getRgb()[:3], QColor(background).getRgb()[:3]
    mix = [round(a * alpha / 255 + b * (1 - alpha / 255)) for a, b in zip(top, bottom, strict=True)]
    return QColor(*mix).name()


@pytest.mark.parametrize("mode", list(ThemeMode))
def test_the_colors_are_legible(mode: ThemeMode):
    """WCAG 2.2 AA: 4.5:1 for text, 3:1 for the outlines of controls."""
    colors = THEMES[mode]
    surfaces = (colors.surface, colors.raised, colors.sunken, colors.chrome)
    for surface in surfaces:
        assert contrast(colors.text, surface) >= 4.5
        assert contrast(colors.text_muted, surface) >= 4.5
        assert contrast(colors.error, surface) >= 4.5
        assert contrast(colors.control_border, surface) >= 3
    assert contrast(colors.placeholder, colors.sunken) >= 4.5
    assert contrast(colors.on_accent, colors.accent) >= 4.5
    assert contrast(colors.on_accent, colors.accent_hover) >= 4.5
    assert contrast(colors.text, colors.accent_tint) >= 4.5
    for tone, background in (
        (colors.tone_good, colors.success),
        (colors.tone_warn, colors.warning),
        (colors.tone_bad, colors.error),
        (colors.tone_neutral, colors.tone_neutral),
    ):
        assert contrast(tone, over(background, colors.chrome, TINT_ALPHA)) >= 4.5


def test_the_device_is_legible():
    hardware = HARDWARE
    off = LCD_COLORS["off"]
    for name, color in LCD_COLORS.items():
        # the marks on the swatches of the color picker
        assert contrast(LCD_TEXT_OFF if name == "off" else LCD_TEXT, color) >= 4.5
        if name == "off":
            continue
        # the characters, the backlight through the dark panel
        assert contrast(color, over(color, LCD_PANEL, round(LCD_TINT * 255))) >= 4.5
        dimmed = over(color, off, round(DIM * 255))
        text = over(color, off, round(DIM_TEXT * 255))
        assert contrast(text, over(dimmed, LCD_PANEL, round(LCD_TINT * 255))) >= 4
    for strip in (hardware.strip_top, hardware.strip_bottom):
        assert contrast(hardware.print, strip) >= 4.5
        assert contrast(hardware.print_dim, strip) >= 4.5
    assert contrast(hardware.badge_text, hardware.badge) >= 4.5
    assert contrast(hardware.tag_text, hardware.tag) >= 4.5
