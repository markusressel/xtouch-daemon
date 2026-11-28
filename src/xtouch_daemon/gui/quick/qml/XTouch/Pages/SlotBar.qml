// The top of the page: the button Simulate (it stays put), the states with their dots (click for their override, or
// to simulate them the other way) and, while Simulate runs, where it shows. What-ifs take the place of nothing: they
// open as a panel below (see `SlotWhatIf.qml`).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Item {
    id: bar
    required property QtObject slots
    objectName: "slot_bar"
    implicitHeight: Theme.controlHeight

    Button {
        id: simulate
        objectName: "simulate"
        x: 0
        text: "Simulate"
        icon.source: "image://icon/flask-outline"
        checkable: true
        checked: bar.slots.simulating
        enabled: bar.slots.simulateEnabled
        onClicked: bar.slots.toggleSimulate(!bar.slots.simulating)
        ToolTip.visible: hovered
        ToolTip.delay: 400
        ToolTip.text: bar.slots.simulateTip
        // the button follows what is, not what was clicked
        onToggled: checked = Qt.binding(() => bar.slots.simulating)
    }

    // the states: gone while what-ifs show
    Item {
        id: states
        objectName: "state_buttons"
        x: simulate.width + Theme.space.s
        height: parent.height
        width: bar.slots.simulating ? 0 : row.implicitWidth
        opacity: bar.slots.simulating ? 0 : 1
        clip: true
        visible: opacity > 0
        Behavior on width { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: Theme.resize } }

        Row {
            id: row
            spacing: Theme.space.s
            Repeater {
                model: bar.slots.stateButtons
                SlotStateButton {
                    id: stateButton
                    required property var row
                    required property string key
                    objectName: "state_" + key
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.text
                    on: row.on
                    ToolTip.text: row.tip
                    onClicked: {
                        popover.info = bar.slots.stateInfo(key)
                        popover.anchor = stateButton
                        popover.open()
                    }
                }
            }
        }
    }

    // where Simulate shows
    Item {
        x: simulate.width + Theme.space.s
        height: parent.height
        width: note.implicitWidth
        opacity: bar.slots.simulating ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Theme.resize } }
        FadeText {
            id: note
            objectName: "device_note"
            anchors.verticalCenter: parent.verticalCenter
            text: bar.slots.deviceNote
            color: Theme.colors.text_muted
        }
    }

    SlotStatePopover {
        id: popover
        objectName: "state_popover"
        slots: bar.slots
    }
}
