"""
The drawing of the device: picking strips, and how strips are painted.
"""

import dataclasses
import math
from math import cos, radians, sin

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QImage, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
)
from pytestqt.qtbot import QtBot

from tests.support.gui import MakeWindow, click
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.gui.domain.looks import StripFace
from xtouch_daemon.gui.qt.preview.geometry import (
    CAP_SIZE,
    CENTER_X,
    ENCODER,
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
from xtouch_daemon.gui.qt.preview.panel import MIN_SCALE
from xtouch_daemon.gui.qt.preview.strip_view import StripView
from xtouch_daemon.gui.qt.theme.settings import (
    load_split,
    save_split,
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
from xtouch_daemon.gui.qt.window.splitter import LEFT_SHARE
from xtouch_daemon.hardware import protocol


@pytest.fixture
def window(make_window: MakeWindow, qtbot: QtBot) -> MainWindow:
    """The window, with the drawing of the device at about its own size: the pixels the tests look at are there."""
    window = make_window()
    preview = window.device_view.preview
    window.resize(1280, 1400)
    window.resizeDocks([window.device_dock], [round(PANEL.height()) + 120], Qt.Orientation.Vertical)
    QApplication.processEvents()
    # as high as the panel: at scale 1, a line of 1 unit is a line of pixels (the bars above it settle a step later)
    dock = window.device_dock
    for _ in range(10):
        if preview.height() == math.ceil(PANEL.height()):
            break
        height = dock.height() - preview.height() + math.ceil(PANEL.height())
        window.resizeDocks([dock], [height], Qt.Orientation.Vertical)
        qtbot.wait(10)
    assert preview.scale == pytest.approx(1, abs=0.002)
    qtbot.waitUntil(lambda: not window.device_view.preview.resizing)
    return window


def x_of(window: MainWindow, index: int) -> int:
    return window.device_view.preview.strips[index].x()


def test_the_keyboard_selects_strips(qtbot: QtBot, window: MainWindow):
    strips = window.device_view.preview.strips
    strips[0].setFocus()

    qtbot.keyClick(strips[0], Qt.Key.Key_Right)
    assert window.device_view.selected == 1
    qtbot.keyClick(strips[1], Qt.Key.Key_Left)
    # not past the ends
    qtbot.keyClick(strips[0], Qt.Key.Key_Left)
    assert window.device_view.selected == 0
    qtbot.keyClick(strips[0], Qt.Key.Key_End)
    assert window.device_view.selected == 7
    qtbot.keyClick(strips[7], Qt.Key.Key_A)
    qtbot.keyClick(strips[7], Qt.Key.Key_Home)
    assert window.device_view.selected == 0


def show_state(view: StripView, **changes: object) -> QImage:
    """The strip with its state changed, as painted (as one the daemon tells about)."""
    face = configured(view)
    view.show_face(dataclasses.replace(face, state=dataclasses.replace(face.state, **changes)), False)
    image = view.grab().toImage()
    # its pixels per logical unit of the strip: the zoom times the scale of the preview
    image.setDevicePixelRatio(image.devicePixelRatio() * view.preview.scale)
    return image


def configured(view: StripView) -> StripFace:
    """The face of the strip, as one the daemon tells about (not drawn fainter)."""
    return dataclasses.replace(view.face, look=dataclasses.replace(view.face.look, configured=True), live=True)


def pixel(image: QImage, point: QPointF) -> QColor:
    """The color at a point of the strip, in logical units, at any zoom and scale."""
    return image.pixelColor((point * image.devicePixelRatio()).toPoint())


def test_lit_leds_show_their_colors(window: MainWindow):
    view = window.device_view.preview.strips[0]
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
    view = window.device_view.preview.strips[0]
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
    view = window.device_view.preview.strips[0]
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
    view = window.device_view.preview.strips[0]

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
    view = window.device_view.preview.strips[0]
    metrics = QFontMetricsF(view.lcd_font)
    cells = LCD_CELLS
    assert metrics.horizontalAdvance("W") * protocol.LCD_CELL_WIDTH <= cells.width()
    assert 2 * metrics.capHeight() < cells.height()
    face = configured(view)
    middle = QPointF(cells.center().x() + 0.5, cells.top() + (cells.height() - 2) / 2 + 1)

    rim = QPointF(LCD.left() + 2.4, LCD.center().y())
    # in the first cell, which is blank: a glyph of another font would reach the point
    panel = QPointF(cells.left() + 1, cells.center().y() - 6)

    # a negative display: the backlight around a dark panel, and through it in the line and the characters
    image = show_state(view, color="blue", text=(" Browse", " Phone "))
    for point in (rim, middle):
        assert pixel(image, point).blue() > 200
    assert pixel(image, panel).lightness() < 30
    lit = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())]
    assert any(color.blue() > 200 and color.red() < 120 for color in lit)
    # the backlight off: all dark
    image = show_state(view, color="off", text=(" Browse", " Phone "))
    for point in (rim, middle, panel):
        assert pixel(image, point).lightness() < 50
    # dimmed: a dim rim, but characters that can still be read
    view.show_face(dataclasses.replace(face, state=dataclasses.replace(face.state, color="blue"), dimmed=True), False)
    image = view.grab().toImage()
    image.setDevicePixelRatio(image.devicePixelRatio() * view.preview.scale)
    assert pixel(image, rim).blue() < 120
    assert pixel(image, middle).blue() > 150
    view.show_face(face, False)


def drag_handle(window: MainWindow, share: float, release: bool = True) -> None:
    """Drags the handle between the slots and the inspector to `share` of the width, as a hand does."""
    splitter = window.slots_page.splitter
    handle = splitter.handle(1)
    assert handle is not None
    grip = QPointF(handle.rect().center())
    send_mouse(handle, QEvent.Type.MouseButtonPress, grip, Qt.MouseButton.LeftButton)
    left, right = splitter.sizes()
    splitter.moveSplitter(round((left + right) * share), 1)
    QApplication.processEvents()
    if release:
        send_mouse(handle, QEvent.Type.MouseButtonRelease, grip, Qt.MouseButton.NoButton)


def shrink_device(window: MainWindow) -> None:
    """Makes the window Device low, as a hand does with the edge of the dock."""
    window.resizeDocks([window.device_dock], [80], Qt.Orientation.Vertical)
    QApplication.processEvents()


def send_mouse(widget: QWidget, kind: QEvent.Type, at: QPointF, buttons: Qt.MouseButton) -> None:
    """A press, move or release of the left button at `at` in `widget`."""
    where = QPointF(widget.mapToGlobal(at))
    event = QMouseEvent(kind, at, where, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def test_the_preview_scales_to_the_space_it_gets(window: MainWindow):
    preview = window.device_view.preview
    large = preview.scale
    assert preview.minimumSizeHint().height() == math.ceil(PANEL.height() * MIN_SCALE)

    shrink_device(window)

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


def test_the_panes_of_a_page_have_a_handle(window: MainWindow):
    splitter = window.slots_page.splitter
    # most of the width is for the inspector, until the handle is dragged
    assert splitter.share == pytest.approx(LEFT_SHARE, abs=0.02)
    handle = splitter.handle(1)
    assert handle is not None
    assert handle.cursor().shape() == Qt.CursorShape.SplitHCursor
    assert "Drag" in handle.toolTip()
    assert not handle.grab().isNull()
    assert load_split("slots") is None

    drag_handle(window, 0.5)

    assert load_split("slots") == pytest.approx(splitter.share)
    # each page has its own
    for name, page in (("channels", window.channels_page), ("states", window.states_page)):
        window.show_page(name)
        QApplication.processEvents()
        assert page.splitter.share == pytest.approx(LEFT_SHARE, abs=0.02)


def test_strips_are_picked_at_any_scale(qtbot: QtBot, window: MainWindow):
    preview = window.device_view.preview
    shrink_device(window)
    assert preview.scale < 0.8
    # the strip under a point in the middle of its place
    third = preview.to_widget(QPointF(slot_position(2)) + QPointF(WIDTH / 2, 250))
    view = preview.childAt(third)
    assert view is preview.strips[2]

    window.show_page("channels")
    click(qtbot, view)
    assert window.device_view.selected == 2
    assert preview.strips[2].selected
    # its slot on the page Slots
    assert window.current_page == "slots"
    assert window.slots_page.slot == 3
    # only the left button picks
    qtbot.mouseClick(preview.strips[3], Qt.MouseButton.RightButton)
    assert window.device_view.selected == 2


def test_a_click_beside_the_strips_picks_nothing(qtbot: QtBot, window: MainWindow):
    preview = window.device_view.preview
    click(qtbot, preview.strips[2])
    assert preview.strips[2].selected
    # the margin of the panel, left of the first strip
    beside = preview.to_widget(QPointF(MARGIN_X / 2, PANEL.height() / 2))
    assert preview.childAt(beside) is None

    qtbot.mouseClick(preview, Qt.MouseButton.LeftButton, pos=beside)
    assert window.device_view.selected is None
    assert not any(view.selected for view in preview.strips)
    assert (window.slots_page.slot, window.slots_page.candidate) == (None, None)
    assert all(stack.currentRow() == -1 for stack in window.slots_page.lists)
    # in Play the mouse is a hand: a click beside the strips changes nothing either way
    click(qtbot, preview.strips[1])
    preview.set_playing(True)
    qtbot.mouseClick(preview, Qt.MouseButton.LeftButton, pos=beside)
    assert window.device_view.selected == 1


def test_strips_are_drawn_again_only_when_they_show_something_else(qtbot: QtBot, window: MainWindow):
    preview = window.device_view.preview
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
    view = window.device_view.preview.strips[0]
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
    preview = window.device_view.preview
    qtbot.waitUntil(lambda: not preview.resizing)
    views = preview.strips
    for view in views:
        view.grab()
    before = [view.picture for view in views]

    shrink_device(window)

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
    # once the size stops changing, drawn sharp
    qtbot.waitUntil(lambda: not preview.resizing)
    for view in views:
        view.grab()
        assert view.picture is not None
        assert view.picture.scale == preview.scale


def test_the_handle_follows_many_moves_of_the_mouse_at_once(window: MainWindow):
    splitter = window.slots_page.splitter
    handle = splitter.handle(1)
    assert handle is not None
    grip = QPointF(handle.rect().center())
    send_mouse(handle, QEvent.Type.MouseButtonPress, grip, Qt.MouseButton.LeftButton)
    left = splitter.sizes()[0]
    moves: list[int] = []
    splitter.splitterMoved.connect(lambda position, _: moves.append(position))

    for step in range(1, 6):
        send_mouse(handle, QEvent.Type.MouseMove, grip + QPointF(10 * step, 0), Qt.MouseButton.LeftButton)
    assert splitter.sizes()[0] == left
    QApplication.processEvents()

    # once, to where the mouse is now
    assert len(moves) == 1
    assert splitter.sizes()[0] == left + 50
    # the last move before it is let go counts too (10 right of the grip, which has moved along)
    send_mouse(handle, QEvent.Type.MouseMove, grip + QPointF(10, 0), Qt.MouseButton.LeftButton)
    send_mouse(handle, QEvent.Type.MouseButtonRelease, grip, Qt.MouseButton.NoButton)
    assert splitter.sizes()[0] == left + 60
    QApplication.processEvents()
    assert len(moves) == 2


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


def test_the_share_of_a_pane_is_kept(make_window: MakeWindow):
    save_split("slots", 0.6)
    window = make_window()
    assert window.slots_page.splitter.share == pytest.approx(0.6, abs=0.02)
    # shown again: the keys stay where they are
    window.hide()
    window.show()
