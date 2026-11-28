// "Used by": the eight strips of the device, filled where a slot shows the channel, dashed where only the controls of a
// slot use it, faint otherwise (a click on a used one shows the slot), and the rest (a pool, a state) in words; `none`
// says it while nothing uses it. `where` is what `uses` and `state_uses` tell: `slot 2`, `controls 5`, `pool games`.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Row {
    id: usedBy
    required property QtObject tools
    property var where: []
    property string none: "Not used by a slot, pool or state yet."
    readonly property var usage: tools.usedBy(where, none)
    signal slotPicked(int slot)

    spacing: Theme.space.s
    height: Math.max(strips.height, rest.implicitHeight)

    Label {
        visible: usedBy.usage.title
        anchors.verticalCenter: parent.verticalCenter
        text: "Used by"
        color: Theme.colors.text_muted
    }
    Row {
        id: strips
        objectName: "used_by_strips"
        visible: usedBy.usage.anyStrip
        spacing: 3
        anchors.verticalCenter: parent.verticalCenter
        Repeater {
            model: usedBy.usage.strips
            Rectangle {
                id: strip
                required property var modelData
                readonly property bool used: modelData.use !== "none"
                objectName: "used_by_" + modelData.slot
                width: 16
                height: 26
                radius: 3
                color: modelData.use === "shows" ? Theme.tint(Theme.colors.slot, 0.31) : "transparent"
                border.width: 1
                border.color: used ? Theme.colors.slot : Theme.tint(Theme.colors.control_border, 0.43)
                opacity: used ? 1 : 0.8
                Behavior on color { ColorAnimation { duration: Theme.fade } }
                Behavior on border.color { ColorAnimation { duration: Theme.fade } }
                Label {
                    anchors { top: parent.top; topMargin: 1; horizontalCenter: parent.horizontalCenter }
                    text: strip.modelData.slot
                    font.pointSize: Theme.fontSize.caption * 0.8
                    font.bold: true
                    color: strip.used ? Theme.colors.text : Theme.colors.text_muted
                }
                Rectangle {
                    anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 15; bottom: parent.bottom; bottomMargin: 4 }
                    width: 2
                    radius: 1
                    color: strip.used ? Theme.colors.slot : Theme.tint(Theme.colors.control_border, 0.43)
                }
                HoverHandler { id: hover; cursorShape: strip.used ? Qt.PointingHandCursor : Qt.ArrowCursor }
                TapHandler { enabled: strip.used; onTapped: usedBy.slotPicked(strip.modelData.slot) }
                ToolTip.visible: hover.hovered && modelData.tip !== ""
                ToolTip.text: modelData.tip
            }
        }
    }
    Label {
        id: rest
        objectName: "used_by_rest"
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(0, usedBy.width - x)
        text: usedBy.usage.rest
        wrapMode: Text.Wrap
        color: Theme.colors.text_muted
    }
}
