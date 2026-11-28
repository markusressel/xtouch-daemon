// Details a click away, inside the window: a card under (or over, where there is no room) its `anchor`, that fades and
// grows in. Escape or a click outside closes it; the focus goes back to the anchor then, unless it went elsewhere.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch

Popup {
    id: popover
    property Item anchor: parent
    property string title: ""
    default property alias body: column.data
    property real preferredWidth: 360

    parent: Overlay.overlay
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    padding: Theme.space.m
    width: Math.min(preferredWidth, parent ? parent.width - 2 * Theme.space.s : preferredWidth)

    // where the anchor is when the popover opens: `mapToItem` doesn't tell when the anchor moves, `visible` does
    readonly property point where: {
        const shown = popover.visible
        return anchor && parent ? anchor.mapToItem(parent, 0, 0) : Qt.point(0, 0)
    }
    readonly property bool below: !parent || !anchor || where.y + anchor.height + implicitHeight + Theme.space.s <= parent.height
    x: parent ? Math.max(Theme.space.s, Math.min(where.x, parent.width - width - Theme.space.s)) : 0
    y: !anchor ? 0 : below ? where.y + anchor.height + Theme.space.xs : Math.max(Theme.space.s, where.y - implicitHeight - Theme.space.xs)
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
