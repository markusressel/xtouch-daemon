// What Simulate can change, in groups that wrap: the mode, the states, the channels, the pools. The groups and the
// controls in them stay while a what-if changes (only their look moves), so a toggle that is clicked keeps its
// focus and the cards below keep their scroll.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Rectangle {
    id: panel
    required property QtObject slots
    objectName: "what_if_panel"

    implicitHeight: flow.implicitHeight + 2 * Theme.space.s
    implicitWidth: flow.implicitWidth + 2 * Theme.space.m
    radius: Theme.radius.large
    color: Theme.colors.raised
    border.color: Theme.colors.border

    Flow {
        id: flow
        x: Theme.space.m
        y: Theme.space.s
        width: panel.width - 2 * Theme.space.m
        spacing: Theme.space.l

        Repeater {
            model: panel.slots.whatIfGroups
            Column {
                id: group
                required property QtObject modelData
                visible: modelData.shown
                spacing: Theme.space.xs
                Text {
                    text: group.modelData.title.toUpperCase()
                    color: Theme.colors.text_muted
                    font.pointSize: Theme.fontSize.caption
                    font.bold: true
                }
                Flow {
                    width: Math.min(implicitWidth, flow.width)
                    spacing: Theme.space.s
                    Repeater {
                        model: group.modelData.items
                        delegate: Loader {
                            id: loader
                            required property var row
                            required property string key
                            sourceComponent: row.kind === "mode" ? modeBox : row.kind === "count" ? counter : toggle
                            property var rowData: row
                        }
                    }
                }
            }
        }
    }

    Component {
        id: modeBox
        // as wide as its longest mode
        ComboBox {
            objectName: "what_if_mode"
            model: parent.rowData.modes
            currentIndex: Math.max(0, find(parent.rowData.current))
            implicitWidth: 160
            ToolTip.visible: hovered
            ToolTip.text: parent.rowData.tip
            onActivated: index => panel.slots.whatIfMode(model[index])
        }
    }

    Component {
        id: toggle
        // a state, or the presence of a channel or pool: a node says which it is in the what-if, a frame in the accent
        // that it differs from reality
        AbstractButton {
            id: button
            readonly property var row: parent.rowData
            objectName: "what_if_" + row.name
            text: row.name
            hoverEnabled: true
            leftPadding: Theme.space.s
            rightPadding: Theme.space.s
            implicitWidth: content.implicitWidth + leftPadding + rightPadding
            implicitHeight: Theme.controlHeight
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: row.tip
            onClicked: panel.slots.whatIfToggle(row.name, row.flip)
            contentItem: Row {
                id: content
                spacing: Theme.space.xs
                Rectangle {
                    objectName: "node"
                    anchors.verticalCenter: parent.verticalCenter
                    width: 10; height: 10; radius: 5
                    color: button.row.lit ? Theme.colors.tone_good : "transparent"
                    border.width: 2
                    border.color: button.row.lit ? Theme.colors.tone_good : Theme.colors.text_muted
                    Behavior on color { ColorAnimation { duration: Theme.resize } }
                    Behavior on border.color { ColorAnimation { duration: Theme.resize } }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: button.text
                    color: Theme.colors.text
                    font.pointSize: Theme.fontSize.body
                }
            }
            background: Rectangle {
                radius: Theme.radius.medium
                color: button.down ? Theme.tint(Theme.colors.text, 0.16)
                    : button.hovered ? Theme.tint(Theme.colors.text, 0.08) : Theme.colors.raised
                border.width: button.row.checked || button.visualFocus ? 2 : 1
                border.color: button.row.checked || button.visualFocus ? Theme.colors.accent : Theme.colors.control_border
                Behavior on color { ColorAnimation { duration: Theme.fade } }
                Behavior on border.color { ColorAnimation { duration: Theme.fade } }
            }
        }
    }

    Component {
        id: counter
        Row {
            id: count
            readonly property var row: parent.rowData
            spacing: Theme.space.xs
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 10; height: 10; radius: 5
                color: count.row.lit ? Theme.colors.tone_good : "transparent"
                border.width: 2
                border.color: count.row.lit ? Theme.colors.tone_good : Theme.colors.text_muted
                Behavior on color { ColorAnimation { duration: Theme.resize } }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: count.row.name
                color: Theme.colors.text
                font.pointSize: Theme.fontSize.body
            }
            SpinBox {
                objectName: "what_if_count_" + count.row.name
                from: 0
                to: count.row.max
                value: count.row.value
                editable: true
                implicitWidth: 96
                ToolTip.visible: hovered
                ToolTip.delay: 400
                ToolTip.text: count.row.tip
                onValueModified: panel.slots.whatIfCount(count.row.name, value)
            }
        }
    }
}
