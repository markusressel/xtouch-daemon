import QtQuick
import QtQuick.Templates as T
import XTouch

T.TabBar {
    id: control
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset, contentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset, contentHeight + topPadding + bottomPadding)
    spacing: Theme.space.xs

    contentItem: ListView {
        model: control.contentModel
        currentIndex: control.currentIndex
        spacing: control.spacing
        orientation: ListView.Horizontal
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.AutoFlickIfNeeded
        snapMode: ListView.SnapToItem
        highlightMoveDuration: Theme.resize
        highlightResizeDuration: Theme.resize
        highlightFollowsCurrentItem: true
        highlight: Item {
            z: 2
            Rectangle {
                height: 2
                width: parent.width
                y: parent.height - height
                color: Theme.colors.accent
            }
        }
    }

    background: Rectangle {
        color: "transparent"
        Rectangle { width: parent.width; height: 1; y: parent.height - 1; color: Theme.colors.border }
    }
}
