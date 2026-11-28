// A thing of the configuration in its color (`entity`: `state`, `channel`, `presence`, `slot`): outlined for a part of a
// condition, filled (a tint, text in `text`) for what is shown. `swatches`: colors of LCDs before the text.
import QtQuick
import XTouch

Rectangle {
    id: chip
    property string text
    property string entity: "channel"
    property color hue: Theme.colors[entity] !== undefined ? Theme.colors[entity] : Theme.colors.channel
    property bool filled: false
    property var swatches: []
    property alias elide: label.elide
    property real maximumWidth: Infinity

    radius: Theme.radius.pill
    color: filled ? Theme.tint(hue, 2 * Theme.tintAlpha) : "transparent"
    border.color: hue
    border.width: 1
    implicitHeight: label.implicitHeight + 4
    implicitWidth: Math.min(maximumWidth, content.implicitWidth + 2 * Theme.space.s)
    Behavior on color { ColorAnimation { duration: Theme.fade } }
    Behavior on border.color { ColorAnimation { duration: Theme.fade } }

    Row {
        id: content
        anchors.verticalCenter: parent.verticalCenter
        x: Theme.space.s
        width: Math.min(implicitWidth, chip.width - 2 * Theme.space.s)
        spacing: Theme.space.xs
        Repeater {
            model: chip.swatches
            Swatch {
                required property var modelData
                anchors.verticalCenter: parent.verticalCenter
                color: modelData
            }
        }
        FadeText {
            id: label
            anchors.verticalCenter: parent.verticalCenter
            text: chip.text
            color: chip.filled ? Theme.colors.text : chip.hue
        }
    }
}
