// A candidate in the path of the inspector (`1  games`): the one picked is highlighted, the one the slot shows has a
// dot (a ring where the slot came to it and has nothing left).
import QtQuick
import QtQuick.Controls
import XTouch

ToolButton {
    id: crumb
    property string mark: ""
    property color hue: Theme.colors.channel

    checkable: true
    focusPolicy: Qt.NoFocus
    ToolTip.delay: 400

    contentItem: Row {
        spacing: Theme.space.xs
        Item {
            id: markBox
            anchors.verticalCenter: parent.verticalCenter
            width: crumb.mark !== "" ? 10 : 0
            height: 10
            clip: true
            Behavior on width { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
            SlotDot {
                anchors.centerIn: parent
                size: 10
                on: crumb.mark !== "ring"
                hue: crumb.hue
                opacity: crumb.mark !== "" ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.fade } }
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: crumb.text
            color: crumb.hue
            font.pointSize: Theme.fontSize.body
            font.bold: crumb.checked
        }
    }
}
