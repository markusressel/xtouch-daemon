// The drawing of the device (the window Device): the bar over it, what the test of the device does while it runs, the
// offer to switch to a device plugged in, and the 8 strips. The strips show what the daemon shows right now; a click
// picks one and its slot, a drag moves its slot, and in Play the mouse is a hand on the device.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Rectangle {
    id: panel
    required property QtObject app
    readonly property QtObject device: app.device
    property alias stage: stage
    property alias bar: bar

    objectName: "devicePanel"
    color: Theme.colors.surface
    implicitHeight: 380

    // the window closes: the preview ends, the test, the virtual device
    readonly property Window window: Window.window
    Connections {
        target: panel.window
        function onVisibleChanged() {
            if (panel.window && !panel.window.visible)
                panel.device.shutdown()
        }
    }
    // the slot picked on a page marks its strip
    Connections {
        target: panel.app.slots
        function onSlotChanged() { panel.device.showSelected(panel.app.slots.slot - 1) }
    }
    Component.onCompleted: device.showSelected(app.slots.slot - 1)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space.s
        spacing: Theme.space.xs

        DeviceBar {
            id: bar
            device: panel.device
            Layout.fillWidth: true
        }

        Reveal {
            shown: panel.device.testRunning
            Layout.fillWidth: true
            HelpText {
                objectName: "testHelp"
                width: parent.width
                text: panel.device.testHelp
            }
        }

        Reveal {
            shown: panel.device.deviceOffer.text !== undefined
            Layout.fillWidth: true
            Banner {
                objectName: "deviceBanner"
                width: parent.width
                tone: "neutral"
                text: panel.device.deviceOffer.text !== undefined ? panel.device.deviceOffer.text : ""
                Button {
                    objectName: "deviceOfferButton"
                    visible: panel.device.deviceOffer.action !== undefined && panel.device.deviceOffer.action !== ""
                    text: visible ? panel.device.deviceOffer.action : ""
                    icon.source: "image://icon/swap-horizontal"
                    onClicked: panel.device.switchToDevice()
                }
            }
        }

        DrawingStage {
            id: stage
            drawing: panel.device.drawingModel
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: panel.device.drawingModel.minimumHeight
        }
    }
}
