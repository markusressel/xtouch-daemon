// Two panes side by side (a list, what is picked) with a handle between them that has a grip. The first pane keeps its
// share of the width when the window gets wider or narrower; `moved` tells a new share while the handle is dragged,
// `released` when it is let go (the page keeps the share then). The panes are its two children.
import QtQuick
import XTouch

Item {
    id: split
    property real share: 0.3
    property real minimumFirst: 160
    property real minimumSecond: 320
    default property list<Item> panes
    readonly property real handleWidth: Theme.space.m
    readonly property real total: Math.max(0, width - handleWidth)
    // the room of the first pane, within what both panes need (the first one gives way where they don't both fit)
    readonly property real firstWidth: Math.max(0, Math.min(Math.max(total * share, minimumFirst), total - minimumSecond))
    readonly property bool dragging: grab.pressed
    signal moved(real share)
    signal released()

    function place(pane, holder) {
        pane.parent = holder
        pane.width = Qt.binding(() => holder.width)
        pane.height = Qt.binding(() => holder.height)
    }
    Component.onCompleted: {
        if (panes.length > 0) place(panes[0], first)
        if (panes.length > 1) place(panes[1], second)
    }

    Item {
        id: first
        width: split.firstWidth
        height: parent.height
        clip: true
    }
    Item {
        id: second
        x: split.firstWidth + split.handleWidth
        width: parent.width - x
        height: parent.height
        clip: true
    }
    Item {
        id: handle
        objectName: "pane_handle"
        x: split.firstWidth
        width: split.handleWidth
        height: parent.height

        Rectangle {
            anchors.centerIn: parent
            width: 4
            height: 36
            radius: 2
            color: grab.pressed ? Theme.colors.accent : grab.containsMouse ? Theme.colors.text_muted : Theme.colors.control_border
            Behavior on color { ColorAnimation { duration: Theme.fade } }
        }
        MouseArea {
            id: grab
            objectName: "pane_grab"
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.SplitHCursor
            onPositionChanged: mouse => {
                if (!pressed || split.total <= 0) return
                const x = mapToItem(split, mouse.x, 0).x - split.handleWidth / 2
                const wanted = Math.max(split.minimumFirst, Math.min(split.total - split.minimumSecond, x))
                split.moved(wanted / split.total)
            }
            onReleased: split.released()
        }
    }
}
