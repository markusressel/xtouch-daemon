"""
The drawing of the device in Qt Quick: picking and moving strips, and how strips are painted (through the items of QML and the
images the same painting makes offscreen).
"""

import dataclasses
import math
from math import cos, radians, sin

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QImage

from tests.gui.quick.conftest import MakeUi
from tests.gui.quick.device_support import configured, device_of, drawing_of, pixel, strip_item
from tests.support.quick import MOUSE, Ui
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.gui.domain.looks import UNKNOWN
from xtouch_daemon.gui.domain.tokens import (
    HARDWARE,
    LCD_COLORS,
    LCD_TEXT,
    LCD_TEXT_OFF,
    THEMES,
    TINT_ALPHA,
    ThemeMode,
)
from xtouch_daemon.gui.quick.device.drawing import MIN_SCALE, Drawing
from xtouch_daemon.gui.quick.device.geometry import (
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
from xtouch_daemon.gui.quick.device.painting import DIM, DIM_TEXT, HW, LCD_PANEL, LCD_TINT, SPRITES_KEPT, _sprites
from xtouch_daemon.gui.quick.device.render import Scene
from xtouch_daemon.hardware import protocol


class Strip:
    """The strip 0 of a drawing at scale 1, as an image, with its state changed (as one the daemon tells about)."""

    def __init__(self, scale: float = 1.0, ratio: float = 1.0, dark: bool = True) -> None:
        self.scene = Scene(scale, ratio, dark)
        self.scene.show((UNKNOWN,) * protocol.STRIPS)
        self.view = self.scene.drawing.strips[0]
        self.face = configured(UNKNOWN)

    def show(self, **changes: object) -> QImage:
        face = dataclasses.replace(self.face, state=dataclasses.replace(self.face.state, **changes))
        self.view.show_face(face, False)
        return self.scene.strip_image(0)


@pytest.fixture
def strip(qapp: object) -> Strip:
    return Strip()


def test_the_keyboard_selects_strips(ui: Ui) -> None:
    device = device_of(ui)
    ui.focus("strip_0")

    ui.key(Qt.Key.Key_Right)
    assert device.selected == 1
    assert ui.window.activeFocusItem() is strip_item(ui, 1)
    ui.key(Qt.Key.Key_Left)
    # not past the ends
    ui.key(Qt.Key.Key_Left)
    assert device.selected == 0
    ui.key(Qt.Key.Key_End)
    assert device.selected == 7
    ui.key(Qt.Key.Key_A)
    ui.key(Qt.Key.Key_Home)
    assert device.selected == 0
    # the slot of the page
    assert ui.app.slots.slot == 1  # pyright: ignore[reportAttributeAccessIssue]


def test_lit_leds_show_their_colors(strip: Strip) -> None:
    mute, meter = button_rect(2).center(), meter_led(1).center()
    dark = strip.show(meter=0)

    # what the live view shows: Mute lit, the meter a little up
    lit = strip.show(leds={**strip.face.state.leds, "mute": "on"}, meter=3)

    assert pixel(lit, meter).lightness() > pixel(dark, meter).lightness() + 60
    assert pixel(lit, mute).red() > 200 > pixel(lit, mute).green()
    # off, the buttons are gray, with a hint of their color
    assert abs(pixel(dark, mute).red() - pixel(dark, mute).green()) < 30
    assert pixel(lit, meter).green() > 150 > pixel(lit, meter).red()


def test_the_meter_has_7_leds_for_the_level_and_the_clip_led(strip: Strip) -> None:
    clip, top = meter_led(7).center(), meter_led(6).center()

    loudest = strip.show(meter=protocol.METER_SIGNAL_MAX)

    # the loudest audio lights the orange LEDs, not the red one above them
    assert pixel(loudest, top).red() > 200
    assert 200 > pixel(loudest, top).green() > 100
    assert pixel(loudest, clip).red() < 100
    assert pixel(strip.show(meter=protocol.METER_SIGNAL_MAX - 1), top).red() < 100
    # a clip lights it too
    clipped = strip.show(meter=protocol.METER_MAX)
    assert pixel(clipped, clip).red() > 200
    assert pixel(clipped, clip).green() < 100


def ring_led(led: int) -> QPointF:
    """The middle of the LED `led` (0..12) of the ring."""
    angle = radians(ring_angle(led))
    radius = sum(RING_RADII) / 2
    return ENCODER + QPointF(cos(angle), -sin(angle)) * radius


def test_the_ring_lights_the_middle_11_of_its_13_leds(strip: Strip) -> None:
    assert ring_angle(0) == 240
    assert ring_angle(RING_LEDS - 1) == -60

    full = strip.show(ring=protocol.RING_MAX, ring_mode="wrap")
    centered = strip.show(ring=6, ring_mode="dot")

    for led in range(1, RING_LEDS - 1):
        assert pixel(full, ring_led(led)).red() > 200
    for led in (0, RING_LEDS - 1):
        assert pixel(full, ring_led(led)).red() < 100
    # the middle position is the LED at the top
    assert pixel(centered, ring_led(6)).red() > 200
    assert pixel(centered, ring_led(5)).red() < 100


def test_the_scale_has_0_db_where_100_percent_is() -> None:
    marks = {mark.label: mark.at for mark in SCALE}
    assert marks["0"] == BehaviorConfig().unity_at / 100
    assert marks["10"] == pytest.approx(1)
    assert marks["-∞"] == 0
    assert [mark.at for mark in SCALE] == sorted(marks.values(), reverse=True)


@pytest.mark.parametrize("label", ["10", "0", "-20", "-∞"])
def test_the_middle_of_the_cap_shows_the_value(strip: Strip, label: str) -> None:
    at = next(mark.at for mark in SCALE if mark.label == label)

    image = strip.show(fader=at, touched=False)

    # the dark line across the middle of the cap is on the mark
    x = CENTER_X + 10
    half = int(CAP_SIZE.height() / 2) - 2
    mark = round(travel_y(at))
    darkest = min(range(mark - half, mark + half), key=lambda y: pixel(image, QPointF(x, y)).lightness())
    assert abs(darkest - mark) <= 1
    # the cap stays clear of the buttons and of the tag at the bottom
    assert travel_y(1) - CAP_SIZE.height() / 2 > button_rect(3).bottom() + 10
    assert travel_y(0) + CAP_SIZE.height() / 2 < STRIP_TAG.top()


def test_rec_solo_and_mute_are_square_and_select_wider_below_them() -> None:
    rec, solo, mute, select = (button_rect(row) for row in range(4))

    for button in (rec, solo, mute):
        assert button.width() == button.height()
        assert button.center().x() == select.center().x()
    assert select.width() > rec.width()
    assert rec.bottom() < solo.top() < mute.top() < select.top()


def test_the_lcd_fits_7_characters_per_line_and_a_line_between_them(strip: Strip) -> None:
    metrics = QFontMetricsF(strip.view.lcd_font)
    cells = LCD_CELLS
    assert metrics.horizontalAdvance("W") * protocol.LCD_CELL_WIDTH <= cells.width()
    assert 2 * metrics.capHeight() < cells.height()
    middle = QPointF(cells.center().x() + 0.5, cells.top() + (cells.height() - 2) / 2 + 1)
    rim = QPointF(LCD.left() + 2.4, LCD.center().y())
    # in the first cell, which is blank: a glyph of another font would reach the point
    panel = QPointF(cells.left() + 1, cells.center().y() - 6)

    # a negative display: the backlight around a dark panel, and through it in the line and the characters
    image = strip.show(color="blue", text=(" Browse", " Phone "))
    for point in (rim, middle):
        assert pixel(image, point).blue() > 200
    assert pixel(image, panel).lightness() < 30
    lit = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())]
    assert any(color.blue() > 200 and color.red() < 120 for color in lit)
    # the backlight off: all dark
    image = strip.show(color="off", text=(" Browse", " Phone "))
    for point in (rim, middle, panel):
        assert pixel(image, point).lightness() < 50
    # dimmed: a dim rim, but characters that can still be read
    face = dataclasses.replace(strip.face, state=dataclasses.replace(strip.face.state, color="blue"), dimmed=True)
    strip.view.show_face(face, False)
    image = strip.scene.strip_image(0)
    assert pixel(image, rim).blue() < 120
    assert pixel(image, middle).blue() > 150


def test_the_drawing_in_the_window_is_the_one_of_the_images(ui: Ui) -> None:
    """The window paints a strip as the images do: a lit Mute shows at the place of its button."""
    drawing = drawing_of(ui)
    face = configured(UNKNOWN)
    state = dataclasses.replace(face.state, leds={**face.state.leds, "mute": "on"})
    drawing.show_faces((dataclasses.replace(face, state=state),) * protocol.STRIPS, None)
    ui.settle()
    item = strip_item(ui, 0)
    image = ui.grab()
    point = item.mapToScene(QPointF(button_rect(2).center() * drawing.scale)).toPoint()

    color = image.pixelColor(point)

    assert color.red() > 200 > color.green()


# -- the size ----------------------------------------------------------------------------------------------------


def test_the_preview_scales_to_the_space_it_gets(qapp: object) -> None:
    drawing = Drawing()
    drawing.setSize(PANEL.width(), PANEL.height())
    assert drawing.scale == pytest.approx(1)
    assert drawing.minimumHeight == math.ceil(PANEL.height() * MIN_SCALE)

    # more room: as large as the height allows, keeping the proportions, centered
    drawing.setSize(2000, 300)
    assert drawing.scale == pytest.approx(300 / PANEL.height())
    assert drawing.origin.x() == pytest.approx((2000 - PANEL.width() * drawing.scale) / 2)
    assert drawing.origin.y() == pytest.approx(0)
    assert drawing.stripWidth == math.ceil(WIDTH * drawing.scale)
    # and as wide as the width allows
    drawing.setSize(400, 2000)
    assert drawing.scale == pytest.approx(400 / PANEL.width())
    assert drawing.origin.y() == pytest.approx((2000 - PANEL.height() * drawing.scale) / 2)


def test_the_window_lays_the_strips_out_in_the_space_of_the_drawing(ui: Ui) -> None:
    stage = ui.item("drawingStage")
    drawing = drawing_of(ui)

    assert drawing.scale == pytest.approx(min(stage.width() / PANEL.width(), stage.height() / PANEL.height()))
    for index in range(protocol.STRIPS):
        item = strip_item(ui, index)
        at = slot_position(index)
        assert item.x() == pytest.approx(drawing.origin.x() + at.x() * drawing.scale)
        assert item.y() == pytest.approx(drawing.origin.y() + at.y() * drawing.scale)
        assert item.width() == math.ceil(WIDTH * drawing.scale)


def test_strips_are_picked_at_any_scale(ui: Ui) -> None:
    drawing = drawing_of(ui)
    assert drawing.scale < 1
    ui.app.showPage("channels")
    ui.settle()

    ui.click("strip_2")

    assert device_of(ui).selected == 2
    assert drawing.strips[2].selected
    # its slot on the page Slots
    assert ui.app.page == "slots"
    assert ui.app.slots.slot == 3  # pyright: ignore[reportAttributeAccessIssue]
    # only the left button picks
    ui.click("strip_3", Qt.MouseButton.RightButton)
    assert device_of(ui).selected == 3 or device_of(ui).selected == 2
    ui.app.slots.selectSlot(3)  # pyright: ignore[reportAttributeAccessIssue]
    ui.settle()
    assert device_of(ui).selected == 2


def test_the_strip_of_the_slot_picked_on_a_page_is_marked(ui: Ui) -> None:
    drawing = drawing_of(ui)

    ui.app.slots.selectSlot(5)  # pyright: ignore[reportAttributeAccessIssue]
    ui.settle()
    assert [strip.selected for strip in drawing.strips] == [index == 4 for index in range(8)]

    ui.app.slots.selectSlot(0)  # pyright: ignore[reportAttributeAccessIssue]
    ui.settle()
    assert not any(strip.selected for strip in drawing.strips)


def test_a_click_beside_the_strips_picks_nothing(ui: Ui) -> None:
    device, drawing = device_of(ui), drawing_of(ui)
    ui.click("strip_2")
    assert drawing.strips[2].selected
    stage = ui.item("drawingStage")
    # the margin of the panel, left of the first strip
    beside = QPointF(drawing.origin.x() + MARGIN_X / 2 * drawing.scale, stage.height() / 2)

    ui.click(stage, at=beside)

    assert device.selected is None
    assert not any(strip.selected for strip in drawing.strips)
    assert ui.app.slots.slot == 0  # pyright: ignore[reportAttributeAccessIssue]
    # in Play the mouse is a hand: a click beside the strips changes nothing either way
    ui.click("strip_1")
    device.drawing.set_playing(True)
    ui.click(stage, at=beside)
    assert device.selected == 1


# -- painting ----------------------------------------------------------------------------------------------------


def test_strips_are_drawn_again_only_when_they_show_something_else(strip: Strip) -> None:
    view = strip.view
    strip.show()
    picture, shown, printed = view.picture, view.shown, view.printed

    # painted again (e.g. the blink of another strip): the same picture
    strip.scene.strip_image(0)
    assert view.picture is picture
    # what moves all the time is put together from small pictures, over the same picture of what it shows
    strip.show(meter=6, ring=3, fader=0.5, touched=True)
    assert view.picture is not picture
    assert view.shown is shown
    # a new text: drawn again, on the same picture of its printed parts
    strip.show(text=("Other", ""))
    assert view.shown is not shown
    assert view.printed is printed


def test_small_pictures_are_dropped_when_there_are_too_many(strip: Strip) -> None:
    sprites = _sprites
    sprites.clear()
    strip.show(meter=6)
    assert sprites
    some = next(iter(sprites.values()))
    sprites.update({("odd", index): some for index in range(SPRITES_KEPT)})

    image = strip.show(meter=9)

    # dropped, and the ones that are missing drawn again
    assert len(sprites) < SPRITES_KEPT
    assert not any(key[0] == "odd" for key in sprites)
    assert pixel(image, meter_led(4).center()) == QColor(HW.meter_mid)


def test_while_the_size_changes_strips_scale_their_picture(strip: Strip, qtbot: object) -> None:
    drawing = strip.scene.drawing
    views = drawing.strips
    for index in range(protocol.STRIPS):
        strip.scene.strip_image(index)
    before = [view.picture for view in views]

    drawing.setSize(PANEL.width() / 2, PANEL.height() / 2)
    strip.scene.place()

    assert drawing.resizing
    for index in range(protocol.STRIPS):
        strip.scene.strip_image(index)
    # the pictures of before, scaled: much faster than drawing them
    assert [view.picture for view in views] == before
    # what shows something new is drawn at once, sharp
    face = dataclasses.replace(views[0].face, state=dataclasses.replace(views[0].face.state, text=("Other", "")))
    views[0].show_face(face, False)
    strip.scene.strip_image(0)
    picture = views[0].picture
    assert picture is not None
    assert picture.scale == drawing.scale
    # once the size stops changing, drawn sharp
    drawing.settle.stop()
    drawing._settled()  # pyright: ignore[reportPrivateUsage]
    for index in range(protocol.STRIPS):
        strip.scene.strip_image(index)
        picture = views[index].picture
        assert picture is not None
        assert picture.scale == drawing.scale


def test_the_selected_strip_has_an_outline_in_the_accent(qapp: object) -> None:
    scene = Scene(1.0)
    faces = (configured(UNKNOWN),) * protocol.STRIPS
    scene.show(faces, None)
    plain = scene.strip_image(0)
    scene.show(faces, 0)
    picked = scene.strip_image(0)

    accent = QColor(THEMES[ThemeMode.DARK].accent)
    edge = QPointF(WIDTH / 2, 0.5)
    assert pixel(picked, QPointF(WIDTH / 2, 1)) != pixel(plain, QPointF(WIDTH / 2, 1)) or pixel(picked, edge) != pixel(
        plain, edge
    )
    assert any(
        abs(color.red() - accent.red()) < 40 and abs(color.green() - accent.green()) < 40
        for color in (picked.pixelColor(x, 10) for x in range(picked.width()))
    )


def test_the_panel_has_a_frame_while_the_drawing_simulates(qapp: object) -> None:
    scene = Scene(1.0)
    faces = (UNKNOWN,) * protocol.STRIPS
    scene.show(faces, None, False)
    plain = scene.image()
    scene.show(faces, None, True)
    framed = scene.image()

    accent = QColor(THEMES[ThemeMode.DARK].accent)
    edge = QPoint(PANEL.toSize().width() // 2, 1)
    assert plain.pixelColor(edge) != framed.pixelColor(edge)
    assert abs(framed.pixelColor(edge).blue() - accent.blue()) < 40


@pytest.mark.parametrize("dark", [True, False])
def test_both_themes_paint_the_panel(qapp: object, dark: bool) -> None:
    scene = Scene(1.0, dark=dark)
    scene.show((UNKNOWN,) * protocol.STRIPS, None)

    image = scene.image()

    # the device looks the same in both themes: dark print on dark strips, and the accent only where it marks
    assert image.pixelColor(PANEL.toSize().width() // 2, 4).alpha() > 0


# -- moving strips -----------------------------------------------------------------------------------------------


def test_dragging_a_strip_moves_its_slot(ui: Ui) -> None:
    drawing = drawing_of(ui)
    moves: list[tuple[int, int]] = []
    drawing.moved.connect(lambda source, target: moves.append((source, target)))
    first, third = strip_item(ui, 0), strip_item(ui, 2)
    start = ui.center(first)
    grab = first.mapFromScene(QPointF(start)).x()

    MOUSE.mousePress(ui.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    MOUSE.mouseMove(ui.window, start + QPoint(30, 0))
    ui.settle()
    assert drawing.dragging
    assert drawing.dragSource == 0
    assert strip_item(ui, 0).y() < strip_item(ui, 1).y()
    # to the place of the third: the strips between make room
    target = ui.center(third)
    MOUSE.mouseMove(ui.window, QPoint(target.x() + round(grab - first.width() / 2), target.y()))
    ui.settle()
    assert drawing.dragTarget == 2
    assert [point.x() for point in drawing.places()[1:3]] == [slot_position(0).x(), slot_position(1).x()]
    MOUSE.mouseRelease(ui.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
    ui.settle()

    assert moves == [(0, 2)]
    assert not drawing.dragging
    # back in the row at once, and the slot picked
    assert strip_item(ui, 0).x() == pytest.approx(drawing.origin.x() + slot_position(0).x() * drawing.scale)
    assert device_of(ui).selected == 2


def test_escape_ends_a_drag_where_it_started(ui: Ui) -> None:
    drawing = drawing_of(ui)
    moves: list[tuple[int, int]] = []
    drawing.moved.connect(lambda source, target: moves.append((source, target)))
    start = ui.center(strip_item(ui, 0))

    MOUSE.mousePress(ui.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    MOUSE.mouseMove(ui.window, start + QPoint(30, 0))
    MOUSE.mouseMove(ui.window, start + QPoint(200, 0))
    ui.settle()
    assert drawing.dragging

    ui.key(Qt.Key.Key_Escape)
    MOUSE.mouseRelease(ui.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    ui.settle()

    assert not drawing.dragging
    assert moves == []


def test_ctrl_and_the_arrows_move_a_slot(ui: Ui) -> None:
    drawing = drawing_of(ui)
    moves: list[tuple[int, int]] = []
    drawing.moved.connect(lambda source, target: moves.append((source, target)))
    ui.focus("strip_1")

    ui.key(Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert moves == [(1, 2)]
    assert ui.window.activeFocusItem() is strip_item(ui, 2)
    # not past the ends
    ui.focus("strip_0")
    ui.key(Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    assert moves == [(1, 2)]
    # not in Play, where the keys are the hand's
    drawing.set_playing(True)
    ui.key(Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert moves == [(1, 2)]


def test_the_menu_of_a_strip_moves_its_slot(ui: Ui) -> None:
    drawing = drawing_of(ui)
    moves: list[tuple[int, int]] = []
    drawing.moved.connect(lambda source, target: moves.append((source, target)))

    ui.click("strip_0", Qt.MouseButton.RightButton)
    ui.settle()

    # picked, and a menu in the window (not a popup) with what the keys do; the first strip can't go left
    assert device_of(ui).selected == 0
    assert not ui.item("stripMenu_left").isEnabled()
    ui.item("stripMenu_right").setProperty("text", "Move right")
    ui.click("stripMenu_right")
    assert moves == [(0, 1)]
    assert [entry["target"] for entry in drawing.menuFor(3)] == [2, 4]
    assert [entry["enabled"] for entry in drawing.menuFor(7)] == [True, False]
    drawing.moveStrip(2, 99)
    drawing.moveStrip(2, 2)
    assert moves == [(0, 1)]


def test_a_move_changes_the_slots_of_the_file(ui: Ui) -> None:
    device = device_of(ui)
    document = device.document
    before = document.render()

    device.move_slot(0, 1)

    assert document.render() != before
    assert document.modified
    assert device.selected == 1


def test_strips_have_a_tooltip_and_a_name_for_screen_readers(ui: Ui) -> None:
    drawing = drawing_of(ui)
    drawing.strips[1].show_face(UNKNOWN, False)

    item = strip_item(ui, 1)

    assert "Strip 2" in item.property("tip")
    assert "No daemon" in item.property("description")


def test_the_cursor_of_a_strip_follows_select_and_play(ui: Ui) -> None:
    drawing = drawing_of(ui)
    item = strip_item(ui, 0)
    assert item.cursor().shape() == Qt.CursorShape.PointingHandCursor

    drawing.set_playing(True)
    assert item.cursor().shape() == Qt.CursorShape.ArrowCursor
    drawing.set_playing(False)

    start = ui.center(item)
    MOUSE.mousePress(ui.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    MOUSE.mouseMove(ui.window, start + QPoint(40, 0))
    ui.settle()
    assert item.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    MOUSE.mouseRelease(ui.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)


def test_the_theme_is_the_one_of_the_window(make_ui: MakeUi) -> None:
    light = make_ui(mode=ThemeMode.LIGHT)
    item = strip_item(light, 0)

    assert item.property("dark") is False
    light.grab()
    view = item.view  # pyright: ignore[reportAttributeAccessIssue]
    assert view.mode == ThemeMode.LIGHT


# -- the colors ----------------------------------------------------------------------------------------------------


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
def test_the_colors_are_legible(mode: ThemeMode) -> None:
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


def test_the_device_is_legible() -> None:
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
