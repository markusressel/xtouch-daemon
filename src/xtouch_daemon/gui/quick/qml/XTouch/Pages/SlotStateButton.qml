// A state in the bar: a dot (on or off, none until the daemon tells it), its label and what overrides it. A click
// opens its popover.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

AbstractButton {
    id: button
    property int on: -1
    readonly property color hue: Theme.colors.state

    leftPadding: Theme.space.s
    rightPadding: Theme.space.s
    topPadding: 2
    bottomPadding: 2
    spacing: Theme.space.xs
    hoverEnabled: true
    implicitWidth: contentItem.implicitWidth + leftPadding + rightPadding
    implicitHeight: Math.max(Theme.controlHeight, contentItem.implicitHeight + topPadding + bottomPadding)
    ToolTip.visible: hovered && ToolTip.text !== ""
    ToolTip.delay: 400

    contentItem: Row {
        spacing: button.spacing
        SlotDot {
            anchors.verticalCenter: parent.verticalCenter
            visible: button.on >= 0
            on: button.on === 1
            hue: button.hue
            size: 10
        }
        FadeText {
            anchors.verticalCenter: parent.verticalCenter
            text: button.text
            color: button.hue
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "▾"
            color: button.hue
            font.pointSize: Theme.fontSize.caption
        }
    }

    background: Rectangle {
        radius: Theme.radius.medium
        color: Theme.tint(button.hue, button.down ? 0.28 : button.hovered ? 0.2 : 0.12)
        border.width: button.visualFocus ? 2 : 1
        border.color: button.visualFocus ? Theme.colors.accent : Theme.tint(button.hue, 0.5)
        Behavior on color { ColorAnimation { duration: Theme.fade } }
    }
}
