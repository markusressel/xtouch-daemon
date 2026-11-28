// The 8 strips on their panel, as large as the space allows (the proportions stay). The strips are items painted with
// the painting of the widgets; where they sit comes from the `drawing` (a click picks a strip, a drag moves it, the
// others glide aside), what they show from the daemon. A click beside the strips picks nothing.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Device

Item {
    id: stage
    required property QtObject drawing
    property alias strips: strips

    objectName: "drawingStage"
    onWidthChanged: drawing.setSize(width, height)
    onHeightChanged: drawing.setSize(width, height)
    Component.onCompleted: drawing.setSize(width, height)

    PanelItem {
        anchors.fill: parent
        drawing: stage.drawing
        dark: Theme.dark
    }

    MouseArea {
        objectName: "drawingBackground"
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onPressed: stage.drawing.clickBeside()
    }

    Repeater {
        id: strips
        model: 8

        StripItem {
            id: strip
            required property int index
            objectName: "strip_" + index
            stripIndex: index
            drawing: stage.drawing
            dark: Theme.dark
            readonly property point place: stage.drawing.positions[index]
            x: stage.drawing.originX + place.x * stage.drawing.panelScale
            y: stage.drawing.originY + place.y * stage.drawing.panelScale
            width: stage.drawing.stripWidth
            height: stage.drawing.stripHeight
            z: stage.drawing.dragSource === index ? 1 : 0
            // the others make room for a dragged strip; everything else (a new size, the drop) happens at once
            Behavior on x {
                enabled: stage.drawing.isDragging && stage.drawing.dragSource !== strip.index
                NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic }
            }
            Behavior on y {
                enabled: stage.drawing.isDragging && stage.drawing.dragSource !== strip.index
                NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic }
            }
            ToolTip.visible: hovered && tip !== "" && !stage.drawing.isDragging
            ToolTip.text: tip
            ToolTip.delay: 300
            Accessible.role: Accessible.Button
            Accessible.name: "Strip " + (index + 1)
            Accessible.description: description
            onContextRequested: (px, py) => {
                strip.ToolTip.hide()
                menu.entries = stage.drawing.menuFor(index)
                menu.strip = index
                menu.popup(strip, px, py)
            }
        }
    }

    Menu {
        id: menu
        objectName: "stripMenu"
        property int strip: 0
        property var entries: []
        MenuItem {
            objectName: "stripMenu_left"
            text: "Move left"
            description: "Ctrl+Left"
            icon.source: "image://icon/chevron-left"
            enabled: menu.entries.length > 0 && menu.entries[0].enabled
            onTriggered: stage.drawing.moveStrip(menu.strip, menu.entries[0].target)
        }
        MenuItem {
            objectName: "stripMenu_right"
            text: "Move right"
            description: "Ctrl+Right"
            icon.source: "image://icon/chevron-right"
            enabled: menu.entries.length > 1 && menu.entries[1].enabled
            onTriggered: stage.drawing.moveStrip(menu.strip, menu.entries[1].target)
        }
    }
}
