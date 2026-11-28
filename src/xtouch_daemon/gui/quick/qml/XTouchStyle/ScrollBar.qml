// A thin scroll bar that shows while there is more to scroll to, wider and stronger while it is used or hovered.
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
        objectName: "handle"
        implicitWidth: control.interactive ? (control.hovered || control.pressed ? 8 : 6) : 2
        implicitHeight: control.interactive ? (control.hovered || control.pressed ? 8 : 6) : 2
        radius: width / 2
        color: control.pressed ? Theme.colors.text_muted : Theme.colors.control_border
        // there while there is more to scroll to (a view moved by the wheel alone is never `active`), stronger while
        // it is used
        opacity: control.policy === T.ScrollBar.AlwaysOff ? 0
            : control.policy !== T.ScrollBar.AlwaysOn && control.size >= 1.0 ? 0
            : control.hovered || control.pressed || control.active ? 0.9 : 0.55
        Behavior on implicitWidth { NumberAnimation { duration: Theme.fade } }
        Behavior on implicitHeight { NumberAnimation { duration: Theme.fade } }
        Behavior on opacity { NumberAnimation { duration: Theme.fade } }
    }
}
