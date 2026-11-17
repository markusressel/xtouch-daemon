"""
The previews of the controls in the forms of the page Channels: a card per part of the strip, with a drawing of the
part that plays what its options do, following the values in the form.
"""

from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.support.gui import show_channel
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.domain.demos import Frame, Part
from xtouch_daemon.gui.qt.preview.part_view import CROPS, PartPreview
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.messages import StripState


def previews(window: MainWindow) -> dict[Part, PartPreview]:
    page = window.channels_page
    return dict(page.form_previews[page._form_key()])


def test_the_options_of_a_part_have_a_preview(window: MainWindow):
    show_channel(window, "out")
    shown = previews(window)
    assert list(shown) == ["encoder", "display", "buttons", "fader"]
    display = shown["display"]
    assert display.caption.text() == "Plays: label and volume"
    face = display.drawing.view.face
    assert face.state.text == ("Speaker", "60%")
    assert face.state.color == "cyan"
    # the drawing is the strip of the window Device, cut to the part
    crop = CROPS["display"]
    assert display.drawing.width() == round(crop.width() * display.drawing.scale + 0.5)
    assert display.drawing.view.toolTip() == ""
    # people have no encoder; the groups without a part have no preview
    window.channels_page.select(("people",))
    assert list(previews(window)) == ["display", "fader"]


def test_a_preview_follows_the_values_in_the_form(window: MainWindow):
    show_channel(window, "out")
    buttons = previews(window)["buttons"]
    before = buttons.frames
    assert buttons.frames[0].caption == "Audio plays: all dark"

    path = ("channel", "out", "solo")
    window.document.set(path, "playing")
    window.editor.edited(Change(Scope.VALUE, path))

    assert buttons.frames != before
    assert buttons.frames[0].caption == "Audio plays: Solo"
    assert buttons.index == 0


def test_a_preview_plays_while_it_is_visible(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    display = previews(window)["display"]
    qtbot.waitUntil(display.isVisible)
    assert display.timer.isActive()
    display.step()
    assert display.index == 1
    assert display.caption.text() == "Fader moved: the new volume"
    for _ in range(len(display.frames) - 1):
        display.step()
    # after the last frame, the first again
    assert display.index == 0

    window.show_page("states")
    QApplication.processEvents()
    assert not display.timer.isActive()
    window.show_page("channels")
    assert display.timer.isActive()


def test_the_same_frames_go_on_where_they_are(window: MainWindow):
    preview = PartPreview("display")
    frames = (Frame("one", previews_state(window)), Frame("two", previews_state(window)))
    preview.play(frames)
    preview.step()
    preview.play(frames)
    assert preview.index == 1
    # a click on the drawing does nothing
    preview.drawing.pick(0)
    assert not preview.drawing.resizing
    assert not preview.drawing.key(0, None)  # type: ignore[arg-type]
    preview.deleteLater()


def previews_state(window: MainWindow) -> StripState:
    show_channel(window, "out")
    return previews(window)["display"].frames[0].state
