// A thin scroll bar that shows while it is used or hovered.
import QtQuick
import QtQuick.Templates as T
import XTouch

T.ScrollBar {
    id: control
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding)
    padding: 2
    visible: control.policy !== T.ScrollBar.AlwaysOff
    minimumSize: orientation === Qt.Horizontal ? height / width : width / height
    hoverEnabled: true

    contentItem: Rectangle {
        implicitWidth: control.interactive ? (control.hovered || control.pressed ? 8 : 6) : 2
        implicitHeight: control.interactive ? (control.hovered || control.pressed ? 8 : 6) : 2
        radius: width / 2
        color: control.pressed ? Theme.colors.text_muted : Theme.colors.control_border
        opacity: 0.0
        Behavior on implicitWidth { NumberAnimation { duration: Theme.fade } }

        states: State {
            name: "active"
            when: control.policy === T.ScrollBar.AlwaysOn || (control.active && control.size < 1.0)
            PropertyChanges { control.contentItem.opacity: 0.85 }
        }
        transitions: Transition {
            from: "active"
            SequentialAnimation {
                PauseAnimation { duration: 450 }
                NumberAnimation { target: control.contentItem; duration: 200; property: "opacity"; to: 0.0 }
            }
        }
    }
}
