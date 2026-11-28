// Buttons of which one is on, in one rounded frame: a thumb behind the one that is on slides to the next one picked.
// Its children are `SegmentButton`s; each says whether it is on (`checked`), so the page decides, not the click.
import QtQuick
import XTouch

Rectangle {
    id: group
    default property alias buttons: row.data
    readonly property int inset: 3
    // the button that is on, under the thumb
    readonly property Item current: {
        for (const child of row.children)
            if (child.checked && child.visible) return child
        return null
    }

    implicitWidth: row.implicitWidth + 2 * inset
    implicitHeight: Theme.controlHeight
    radius: Theme.radius.medium
    color: Theme.colors.raised
    border.width: 1
    border.color: Theme.colors.control_border

    Rectangle {
        id: thumb
        objectName: "thumb"
        visible: group.current !== null
        x: group.current ? row.x + group.current.x : group.inset
        y: group.inset
        width: group.current ? group.current.width : 0
        height: group.height - 2 * group.inset
        radius: Theme.radius.medium - 1
        color: Theme.tint(Theme.colors.accent, 0.22)
        Behavior on x { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
    }

    Row {
        id: row
        x: group.inset
        y: group.inset
        height: group.height - 2 * group.inset
        spacing: 2
    }
}
