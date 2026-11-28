// With no slot picked: a line for each slot, what it shows and its problems, with a bar in the color of how it is
// doing; a click picks the slot.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Rectangle {
    id: overview
    required property QtObject slots
    objectName: "overview"
    height: column.implicitHeight + 2 * Theme.space.m
    radius: Theme.radius.large
    color: Theme.colors.raised
    border.color: Theme.colors.border

    Column {
        id: column
        x: Theme.space.m
        y: Theme.space.m
        width: parent.width - 2 * Theme.space.m
        spacing: Theme.space.s
        SectionHeader { text: "Slots"; topPadding: 0 }
        Label {
            width: parent.width
            text: "Pick a slot or a candidate to edit it."
            color: Theme.colors.text_muted
            wrapMode: Text.Wrap
        }
        SlotList {
            width: parent.width
            spacing: Theme.space.xs
            model: overview.slots.overview
            delegate: Rectangle {
                id: line
                required property var row
                required property string key
                objectName: "overview_" + row.slot
                readonly property color hue: row.tone === "good" ? Theme.colors.tone_good
                    : row.tone === "bad" ? Theme.colors.tone_bad : Theme.colors.tone_neutral
                width: ListView.view.width
                height: text.implicitHeight + 2 * Theme.space.xs
                radius: Theme.radius.small
                color: Theme.tint(hue, mouse.containsMouse ? 0.2 : 0.1)
                Behavior on color { ColorAnimation { duration: Theme.fade } }
                Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
                Rectangle {
                    width: 3
                    height: parent.height
                    radius: 1
                    color: line.hue
                    Behavior on color { ColorAnimation { duration: Theme.fade } }
                }
                RowLayout {
                    id: text
                    x: Theme.space.m
                    y: Theme.space.xs
                    width: parent.width - Theme.space.m - Theme.space.s
                    spacing: Theme.space.s
                    Text {
                        Layout.alignment: Qt.AlignTop
                        text: "Slot " + line.row.slot
                        color: Theme.colors.slot
                        font.pointSize: Theme.fontSize.body
                    }
                    SlotFadeText {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        markup: line.row.text
                    }
                }
                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: overview.slots.pickSlot(line.row.slot)
                }
                SlotTip { text: line.row.tip }
            }
        }
    }
}
