// Panes side by side or one above the other, with a handle between them that shows under the mouse.
import QtQuick
import QtQuick.Templates as T
import XTouch

T.SplitView {
    id: control
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset, implicitContentHeight + topPadding + bottomPadding)

    handle: Rectangle {
        implicitWidth: control.orientation === Qt.Horizontal ? 6 : control.width
        implicitHeight: control.orientation === Qt.Horizontal ? control.height : 6
        color: T.SplitHandle.pressed ? Theme.colors.accent
            : T.SplitHandle.hovered ? Theme.tint(Theme.colors.accent, 0.5) : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.fade } }
        Rectangle {
            anchors.centerIn: parent
            width: control.orientation === Qt.Horizontal ? 1 : parent.width
            height: control.orientation === Qt.Horizontal ? parent.height : 1
            color: Theme.colors.border
        }
    }
}
