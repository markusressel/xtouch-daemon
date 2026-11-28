"""
The previews of the controls in the forms in Qt Quick: the
group of the options about a part of the strip has a drawing of the part that plays what the options do, following
the values of the form.
"""

from typing import Any

import pytest

from tests.gui.quick.forms_host import host
from tests.support.quick import Ui
from xtouch_daemon.gui.domain.changes import Change, Scope
from xtouch_daemon.gui.quick.device.part import PartPreviewModel
from xtouch_daemon.gui.quick.forms.context import forms_of
from xtouch_daemon.gui.quick.forms.form import Form
from xtouch_daemon.gui.quick.forms.strips import channel_form, pool_form


@pytest.fixture
def out(ui: Ui) -> Form:
    form = channel_form(forms_of(ui.app), "output")
    form.retarget(("channel", "out"))
    form.active = True
    return form


def model_of(form: Form, part: str) -> PartPreviewModel:
    model = form.previewModel(part)
    assert isinstance(model, PartPreviewModel)
    return model


def previewed(form: Form) -> list[str]:
    """The parts the groups of a form have a preview of, in the order of the device."""
    rows: Any = form.rows
    found: list[str] = []
    for _key, spec, _info in rows.rows:
        if spec["preview"] and spec["preview"] not in found:
            found.append(spec["preview"])
    return found


def test_the_options_of_a_part_have_a_preview(ui: Ui, out: Form):
    assert previewed(out) == ["encoder", "display", "buttons", "fader"]
    display = model_of(out, "display")
    assert display.captionText == "Plays: label and volume"
    state = display.frames[0].state
    assert state.text == ("Speaker", "60%")
    assert state.color == "cyan"
    # the preview of a part stays the same one
    assert out.previewModel("display") is display
    # people have no encoder; the groups without a part have no preview
    people = pool_form(forms_of(ui.app), "people")
    people.retarget(("pool", "people"))
    assert previewed(people) == ["display", "buttons", "fader"]
    assert [frame.caption for frame in model_of(people, "buttons").frames] == [
        "There: all dark",
        "Muted by you: Mute",
    ]


def test_mute_can_flash_while_muted(ui: Ui, out: Form):
    document = ui.app.editor.document
    document.set(("pool", "people", "mute_led"), "flash")
    document.set(("channel", "out", "mute_led"), "flash")
    ui.app.editor.edited()
    people = pool_form(forms_of(ui.app), "people")
    people.retarget(("pool", "people"))
    (_, muted) = model_of(people, "buttons").frames
    assert muted.caption == "Muted by you: Mute flashing"
    assert muted.state.leds["mute"] == "flash"
    frames = model_of(out, "buttons").frames
    assert "Muted: Mute flashing" in [frame.caption for frame in frames]
    assert model_of(out, "fader").frames[-1].state.leds["mute"] == "flash"


def test_a_preview_follows_the_values_in_the_form(ui: Ui, out: Form):
    buttons = model_of(out, "buttons")
    before = buttons.frames
    assert buttons.frames[0].caption == "Audio plays: all dark"

    out.setValue("solo", "playing")

    assert buttons.frames != before
    assert buttons.frames[0].caption == "Audio plays: Solo"
    assert buttons.index == 0
    # a value changed from elsewhere in the file, too
    path = ("channel", "out", "solo")
    ui.app.editor.document.set(path, "muted")
    ui.app.editor.edited(Change(Scope.VALUE, path))
    assert buttons.frames[0].caption != "Audio plays: Solo"


def test_the_preview_shows_the_step_where_it_was(out: Form):
    display = model_of(out, "display")
    display.step(1)
    assert display.index == 1
    assert display.captionText == "Fader moved: the new volume"
    out.setValue("label", "Other")
    assert display.index == 1
    display.step(-2)
    # before the first frame, the last
    assert display.index == len(display.frames) - 1


def test_a_form_in_the_window_has_a_preview_per_group_with_a_part(ui: Ui, out: Form):
    window = host(ui, out)
    window.window.resize(900, 2400)
    window.settle()
    assert len(window.items("partPreview")) == 4
    assert not window.shows("part_preview_placeholder")
    drawings = window.items("partDrawing")
    assert [item.property("model") for item in drawings] == [out.previewModel(part) for part in previewed(out)]
    # their buttons go through the steps of their parts
    for button in window.items("partNext"):
        window.click(button)
    assert [model_of(out, part).index for part in previewed(out)] == [1, 1, 1, 1]
