// The preview of a part of a strip of the device: the strip cut to the encoder, the display, the buttons or the
// fader, with ‹ and › to go through the steps of what its options do, and a caption under the drawing. It knows
// nothing of forms: give it a `model` (a `PartPreviewModel`, see `gui/quick/device/part.py`) and call
// `model.play(frames)` from Python with the scene of the options (`gui.domain.demos.scene`) when they change.
//
// Colors: `cardColor` is the color of what it sits on (the corners are rounded in it), `edgeColor` the thin line around
// the cut.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls
import XTouch.Device

ColumnLayout {
    id: preview
    required property QtObject model
    property color cardColor: Theme.colors.raised
    property color edgeColor: Theme.colors.border

    objectName: "partPreview"
    spacing: Theme.space.xs

    PartItem {
        id: drawing
        objectName: "partDrawing"
        model: preview.model
        dark: Theme.dark
        cardColor: preview.cardColor
        edgeColor: preview.edgeColor
        cornerRadius: Theme.radius.medium
        Layout.preferredWidth: preview.model.drawingWidth
        Layout.preferredHeight: preview.model.drawingHeight
        Accessible.role: Accessible.Graphic
        Accessible.name: "Preview of the " + preview.model.partName
        Accessible.description: preview.model.captionText
    }

    RowLayout {
        spacing: Theme.space.xs
        IconButton {
            objectName: "partBack"
            name: "chevron-left"
            tip: "The step before"
            enabled: preview.model.stepCount > 1
            onClicked: preview.model.step(-1)
        }
        Label {
            objectName: "partCounter"
            text: preview.model.stepText
            color: Theme.colors.text_muted
            font.pointSize: Theme.fontSize.caption
        }
        IconButton {
            objectName: "partNext"
            name: "chevron-right"
            tip: "The next step"
            enabled: preview.model.stepCount > 1
            onClicked: preview.model.step(1)
        }
    }

    HelpText {
        objectName: "partCaption"
        text: preview.model.captionText
        Layout.preferredWidth: preview.model.captionWidth
    }
}
