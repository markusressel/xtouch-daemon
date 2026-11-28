// The page Slots: the state bar with Simulate on top, the cards of the 8 slots on the left and the inspector (or the
// overview) on the right. Esc ends Simulate.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Item {
    id: page
    required property QtObject app
    readonly property QtObject slots: app.slots
    objectName: "slots_page"

    Shortcut {
        sequence: "Escape"
        enabled: page.slots.simulating && page.visible
        onActivated: page.slots.toggleSimulate(false)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: Theme.space.s
        spacing: Theme.space.s

        SlotBar {
            slots: page.slots
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space.s
            Layout.rightMargin: Theme.space.m
        }

        Reveal {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space.s
            Layout.rightMargin: Theme.space.l
            shown: page.slots.simulating
            SlotWhatIf {
                width: parent.width
                slots: page.slots
            }
        }

        SplitView {
            objectName: "slot_panes"
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            SlotCards {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 320
                slots: page.slots
            }
            SlotInspector {
                SplitView.preferredWidth: page.width * 0.45
                SplitView.minimumWidth: 320
                slots: page.slots
            }
        }
    }
}
