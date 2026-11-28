// The rail at the left: a button per page, its icon (and its name, while `labels`); the page shown is marked, and the
// mark slides to the next one.
import QtQuick
import QtQuick.Controls
import XTouch

Rectangle {
    id: rail
    required property QtObject app
    property bool labels: app.shell.railLabels

    objectName: "rail"
    implicitWidth: column.implicitWidth + 2 * Theme.space.xs
    width: implicitWidth
    color: Theme.colors.chrome
    Behavior on color { ColorAnimation { duration: Theme.fade } }

    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.colors.border }

    Rectangle {
        id: mark
        readonly property Item target: column.children[rail.app.pages.findIndex(page => page.name === rail.app.page)] ?? null
        x: Theme.space.xs
        y: column.y + (target ? target.y : 0)
        width: target ? target.width : 0
        height: target ? target.height : 0
        radius: Theme.radius.medium
        color: Theme.colors.accent_tint
        Behavior on y { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
    }

    Column {
        id: column
        x: Theme.space.xs
        y: Theme.space.s
        spacing: Theme.space.xs
        Repeater {
            model: rail.app.pages
            ToolButton {
                required property var modelData
                required property int index
                objectName: "rail_" + modelData.name
                width: Math.max(implicitWidth, column.width)
                icon.source: "image://icon/" + modelData.icon
                icon.width: 22
                icon.height: 22
                text: modelData.title
                display: rail.labels ? AbstractButton.TextUnderIcon : AbstractButton.IconOnly
                checked: rail.app.page === modelData.name
                background: Item {}
                ToolTip.visible: hovered
                ToolTip.text: modelData.title + " (Ctrl+" + (index + 1) + ")\n" + modelData.tip
                onClicked: rail.app.showPage(modelData.name)
            }
        }
    }

    // shows or hides the names of the pages under their icons
    ToolButton {
        id: toggle
        objectName: "rail_labels"
        anchors { bottom: parent.bottom; bottomMargin: Theme.space.s; horizontalCenter: parent.horizontalCenter }
        icon.source: "image://icon/" + (rail.labels ? "chevron-double-left" : "chevron-double-right")
        icon.width: 18
        icon.height: 18
        property string tip: rail.labels ? "Hide the names of the pages" : "Show the names of the pages"
        ToolTip.visible: hovered
        ToolTip.text: tip
        onClicked: rail.app.shell.setRailLabels(!rail.labels)
    }
}
