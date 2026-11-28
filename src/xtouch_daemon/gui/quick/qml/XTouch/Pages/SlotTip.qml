// A tooltip for the item it is in. A `group` (the row it is on) counts the tips that show, so the tip of the row
// waits while one of its parts shows its own.
import QtQuick
import QtQuick.Controls
import XTouch

Item {
    id: tip
    property string text
    property Item group: null
    property alias hovered: hover.hovered
    anchors.fill: parent

    HoverHandler {
        id: hover
        enabled: tip.text !== ""
        onHoveredChanged: if (tip.group) tip.group.tipsOver += hovered ? 1 : -1
    }
    ToolTip.visible: hover.hovered && text !== ""
    ToolTip.text: text
    ToolTip.delay: 400
}
