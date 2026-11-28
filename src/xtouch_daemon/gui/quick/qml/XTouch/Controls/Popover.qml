// Details a click away, inside the window: a card under (or over, where there is no room) its `anchor`, that fades and
// grows in. Escape or a press outside closes it; the focus goes back to the anchor then, unless it went elsewhere.
// The anchor is its parent, and a press on the parent doesn't close it: the anchor opens and closes it with `toggle()`
// (closed by the press, its click would open it again at once).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch

Popup {
    id: popover
    property Item anchor: null
    property string title: ""
    default property alias body: column.data
    property real preferredWidth: 360

    // the window's layer of popups, which the place is worked out in
    readonly property Item stage: Overlay.overlay
    parent: anchor ? anchor : stage
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside | Popup.CloseOnPressOutsideParent
    padding: Theme.space.m
    width: Math.min(preferredWidth, stage ? stage.width - 2 * Theme.space.s : preferredWidth)

    function toggle() {
        if (visible)
            close()
        else
            open()
    }

    // where the anchor is when the popover opens: `mapToItem` doesn't tell when the anchor moves, `visible` does
    readonly property point where: {
        const shown = popover.visible
        return anchor && stage ? anchor.mapToItem(stage, 0, 0) : Qt.point(0, 0)
    }
    readonly property bool below: !stage || !anchor || where.y + anchor.height + implicitHeight + Theme.space.s <= stage.height
    // in the stage, then from the anchor (the parent)
    readonly property real stageX: stage ? Math.max(Theme.space.s, Math.min(where.x, stage.width - width - Theme.space.s)) : 0
    readonly property real stageY: !anchor ? 0 : below ? where.y + anchor.height + Theme.space.xs
        : Math.max(Theme.space.s, where.y - implicitHeight - Theme.space.xs)
    x: stageX - where.x
    y: stageY - where.y
    transformOrigin: below ? Item.Top : Item.Bottom

    onClosed: {
        const window = anchor ? anchor.Window.window : null
        if (anchor && window && (!window.activeFocusItem || window.activeFocusItem === window.contentItem
                                  || popover.contentItem.contains(popover.contentItem.mapFromItem(window.activeFocusItem, 0, 0))))
            anchor.forceActiveFocus()
    }

    ColumnLayout {
        id: column
        width: popover.availableWidth
        spacing: Theme.space.s
        Label {
            visible: popover.title !== ""
            text: popover.title
            font.bold: true
            font.pointSize: Theme.fontSize.section
            Layout.fillWidth: true
        }
    }
}
