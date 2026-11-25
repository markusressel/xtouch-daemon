"""
The previews of the controls in the forms of the page Channels: a card per part of the strip, with a drawing of the
part that plays what its options do, following the values in the form.
"""

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
    window.channels_page.select(("pool", "people"))
    assert list(previews(window)) == ["display", "buttons", "fader"]
    assert [frame.caption for frame in previews(window)["buttons"].frames] == [
        "There: all dark",
        "Muted by you: Mute",
    ]


def test_mute_can_flash_while_muted(window: MainWindow):
    window.document.set(("pool", "people", "mute_led"), "flash")
    window.document.set(("channel", "out", "mute_led"), "flash")
    window.editor.edited()
    show_channel(window, "out")
    window.channels_page.select(("pool", "people"))
    (_, muted) = previews(window)["buttons"].frames
    assert muted.caption == "Muted by you: Mute flashing"
    assert muted.state.leds["mute"] == "flash"
    show_channel(window, "out")
    frames = previews(window)["buttons"].frames
    assert "Muted: Mute flashing" in [frame.caption for frame in frames]
    assert previews(window)["fader"].frames[-1].state.leds["mute"] == "flash"


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


def test_the_buttons_go_through_the_steps(window: MainWindow):
    show_channel(window, "out")
    display = previews(window)["display"]
    display.next.click()
    assert display.index == 1
    assert display.caption.text() == "Fader moved: the new volume"
    assert display.counter.text() == f"2 / {len(display.frames)}"
    display.back.click()
    display.back.click()
    # before the first frame, the last
    assert display.index == len(display.frames) - 1


def test_the_same_frames_go_on_where_they_are(window: MainWindow):
    preview = PartPreview("display")
    frames = (Frame("one", previews_state(window)), Frame("two", previews_state(window)))
    preview.play(frames)
    preview.step(1)
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
