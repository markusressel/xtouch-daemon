// A button of a `SegmentGroup`: an icon and a text, in the accent while it is on (the thumb of the group is behind
// it), in the color of the text while it is off, muted while it can't be pressed.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import XTouch

AbstractButton {
    id: button
    property string iconName: ""
    readonly property color ink: !enabled ? Theme.colors.text_muted : checked ? Theme.colors.accent : Theme.colors.text

    height: parent ? parent.height : implicitHeight
    implicitHeight: Theme.controlHeight - 6
    implicitWidth: content.implicitWidth + leftPadding + rightPadding
    leftPadding: Theme.space.m
    rightPadding: Theme.space.m
    hoverEnabled: true
    Accessible.role: Accessible.RadioButton
    Accessible.checked: checked

    contentItem: Item {
        Row {
            id: content
            anchors.centerIn: parent
            spacing: Theme.space.xs
            ColorImage {
                visible: button.iconName !== ""
                anchors.verticalCenter: parent.verticalCenter
                width: 16; height: 16
                sourceSize: Qt.size(16, 16)
                source: button.iconName !== "" ? "image://icon/" + button.iconName : ""
                color: button.ink
                Behavior on color { ColorAnimation { duration: Theme.fade } }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: button.text
                color: button.ink
                font.pointSize: Theme.fontSize.body
                font.bold: button.checked
                Behavior on color { ColorAnimation { duration: Theme.fade } }
            }
        }
    }

    // under the mouse a light tint; the thumb of the group is the fill of the one that is on
    background: Rectangle {
        radius: Theme.radius.medium - 1
        color: !button.checked && button.enabled && (button.down || button.hovered)
            ? Theme.tint(Theme.colors.text, button.down ? 0.12 : 0.06) : "transparent"
    }
}
