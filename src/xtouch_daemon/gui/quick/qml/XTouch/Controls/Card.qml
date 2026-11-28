// A card on the window: raised, with a line around it; in the accent while it is the one picked, in the error color
// while it has a problem. Its children go into `content` (a column).
import QtQuick
import XTouch

Rectangle {
    id: card
    property bool picked: false
    property bool problem: false
    property bool hovered: false
    default property alias content: column.data
    property alias spacing: column.spacing
    property int padding: Theme.space.m

    implicitWidth: column.implicitWidth + 2 * padding
    implicitHeight: column.implicitHeight + 2 * padding
    radius: Theme.radius.large
    color: Theme.colors.raised
    border.width: picked || problem ? 2 : 1
    border.color: problem ? Theme.colors.error : picked ? Theme.colors.accent : Theme.colors.border
    Behavior on color { ColorAnimation { duration: Theme.fade } }
    Behavior on border.color { ColorAnimation { duration: Theme.fade } }

    // the line of a card under the mouse: at once, as the mouse moves (a pick or a problem fades in)
    Rectangle {
        anchors.fill: parent
        z: 1
        radius: card.radius
        color: "transparent"
        border.width: 1
        border.color: Theme.colors.control_border
        visible: card.hovered && !card.picked && !card.problem
    }

    Column {
        id: column
        x: card.padding
        y: card.padding
        width: card.width - 2 * card.padding
        spacing: Theme.space.s
    }
}
