// A stand-in for the preview of a part of the strip (`PartPreview` of `XTouch.Device`) beside the options about it: it
// takes the inputs the preview needs and shows only its name. A page gives the real one with `FormView.preview`.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Rectangle {
    id: placeholder
    objectName: "part_preview_placeholder"
    // `encoder`, `display`, `buttons` or `fader`
    property string part
    // the strip type of the channel, e.g. `output`
    property string strip
    // every option of the channel with its value as it counts (unset ones at their defaults)
    property var values: ({})

    implicitWidth: 160
    implicitHeight: 28
    radius: Theme.radius.small
    color: Theme.tint(Theme.colors.text, 0.06)
    Label {
        anchors.centerIn: parent
        text: "preview: " + placeholder.part
        font.pointSize: Theme.fontSize.caption
        color: Theme.colors.text_muted
    }
}
