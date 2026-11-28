"""
The preview of a part of a strip in Qt Quick (`PartPreview.qml` and `PartPreviewModel`): the strip cut to the
encoder, the display, the buttons or the fader, with the steps of what its options do.
"""

from collections.abc import Iterator

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtQml import QQmlComponent
from PyQt6.QtQuick import QQuickItem

from tests.gui.quick.conftest import MakeUi
from tests.support.gui import strip_state
from tests.support.quick import Ui
from xtouch_daemon.gui.domain.demos import Frame, Part
from xtouch_daemon.gui.qt.preview.part_view import CROPS
from xtouch_daemon.gui.quick.device.items import use_theme
from xtouch_daemon.gui.quick.device.part import PartPreviewModel

PARTS: tuple[Part, ...] = ("encoder", "display", "buttons", "fader")

SOURCE = b"""
import QtQuick
import XTouch.Device

PartPreview {
    cardColor: "#101010"
    edgeColor: "#808080"
}
"""


def frames() -> tuple[Frame, ...]:
    return (
        Frame("Audio plays: all dark", strip_state(("Speaker", "60%"), color="cyan", fader=0.6)),
        Frame("Fader moved: the new volume", strip_state(("Speaker", "70%"), color="cyan", fader=0.7)),
        Frame(
            "Muted: Mute",
            strip_state(
                ("Speaker", "70%"), color="cyan", leds={"rec": "off", "solo": "off", "mute": "on", "select": "off"}
            ),
        ),
    )


@pytest.fixture
def shown(make_ui: MakeUi) -> Iterator[tuple[Ui, PartPreviewModel, QQuickItem]]:
    """A preview of the display in the window, with three frames."""
    ui = make_ui()
    model = PartPreviewModel("display")
    model.play(frames())
    component = QQmlComponent(ui.engine)
    component.setData(SOURCE, QUrl.fromLocalFile("/tmp/preview.qml"))
    preview = component.createWithInitialProperties({"model": model})
    assert isinstance(preview, QQuickItem), (component.status(), [e.toString() for e in component.errors()])
    root = ui.window.contentItem()
    assert root is not None
    preview.setParentItem(root)
    ui.settle()
    ui.grab()
    yield ui, model, preview
    preview.deleteLater()


def test_the_size_follows_the_crop_of_the_part() -> None:
    for part in PARTS:
        model = PartPreviewModel(part)
        crop = CROPS[part]
        assert model.drawingWidth == round(crop.width() * model.scale + 0.5)
        assert model.drawingHeight >= 1
        assert model.captionWidth >= model.drawingWidth
        assert model.partName == part


def test_the_model_goes_through_the_steps() -> None:
    model = PartPreviewModel("display")
    assert model.stepCount == 0
    # nothing to step through
    model.step(1)
    model.play(frames())
    assert (model.stepText, model.captionText) == ("1 / 3", "Audio plays: all dark")
    assert model.view.face.state.text == ("Speaker", "60%")

    model.step(1)
    assert (model.stepIndex, model.stepText, model.captionText) == (1, "2 / 3", "Fader moved: the new volume")
    model.step(-2)
    # before the first frame, the last
    assert model.stepIndex == 2
    model.step(1)
    assert model.stepIndex == 0


def test_the_same_frames_go_on_where_they_are() -> None:
    model = PartPreviewModel("display")
    model.play(frames())
    model.step(1)
    model.play(frames())
    assert model.stepIndex == 1
    # fewer frames than the step: the last one
    model.play(frames()[:1])
    assert model.stepIndex == 0
    # nobody plays or moves a part
    assert model.hand is None
    assert model.mover is None
    assert not model.resizing
    model.pick(0)
    assert not model.key(0, None)  # pyright: ignore[reportArgumentType]


def test_the_buttons_of_the_window_go_through_the_steps(shown: tuple[Ui, PartPreviewModel, QQuickItem]) -> None:
    ui, model, preview = shown
    assert ui.text("partCounter") == "1 / 3"
    assert ui.find("partCaption") is not None

    ui.click("partNext")
    assert model.stepIndex == 1
    assert ui.text("partCounter") == "2 / 3"
    ui.click("partBack")
    ui.click("partBack")
    assert model.stepIndex == 2
    assert preview.property("model") is model


def test_one_frame_has_nothing_to_go_through(make_ui: MakeUi) -> None:
    ui = make_ui()
    model = PartPreviewModel("fader")
    model.play(frames()[:1])
    component = QQmlComponent(ui.engine)
    component.setData(SOURCE, QUrl.fromLocalFile("/tmp/preview.qml"))
    preview = component.createWithInitialProperties({"model": model})
    assert isinstance(preview, QQuickItem)
    root = ui.window.contentItem()
    assert root is not None
    preview.setParentItem(root)
    ui.settle()
    assert not ui.item("partNext").isEnabled()
    assert not ui.item("partBack").isEnabled()
    preview.deleteLater()


def test_the_drawing_shows_the_frame(shown: tuple[Ui, PartPreviewModel, QQuickItem]) -> None:
    ui, model, _ = shown
    use_theme(True)
    drawing = ui.item("partDrawing")
    first = ui.grab()
    assert not first.isNull()
    assert drawing.width() == model.drawingWidth
    assert drawing.height() == model.drawingHeight
    # the next frame is another picture
    ui.click("partNext")
    ui.settle()
    assert ui.grab() != first
