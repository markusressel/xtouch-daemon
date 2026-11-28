// The window: the menus on top, the footer at the bottom, and between them the drawing of the device over the
// configuration (the rail and its pages); the log under them while it shows.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls
import XTouch.Device
import XTouch.Pages

ApplicationWindow {
    id: window
    required property QtObject app

    objectName: "window"
    title: "X-Touch Extender"
    width: 1280
    height: 900
    visible: true

    menuBar: AppMenuBar { app: window.app }
    footer: Footer { app: window.app }

    SplitView {
        id: panes
        objectName: "panes"
        anchors.fill: parent
        orientation: Qt.Vertical

        DevicePanel {
            objectName: "devicePanel"
            app: window.app
            SplitView.preferredHeight: window.height * 0.38
            SplitView.minimumHeight: 120
        }

        Item {
            objectName: "configuration"
            SplitView.fillHeight: true
            SplitView.minimumHeight: 200

            Rail {
                id: rail
                app: window.app
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            }

            Item {
                id: pages
                anchors { left: rail.right; right: parent.right; top: parent.top; bottom: parent.bottom }

                component PageHolder: Loader {
                    required property string name
                    readonly property bool current: window.app !== null && window.app.page === name
                    objectName: "page_" + name
                    anchors.fill: parent
                    // built when first shown, kept after
                    active: current || item !== null
                    asynchronous: false
                    opacity: current ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: Theme.fade; easing.type: Easing.InOutQuad } }
                }

                PageHolder { name: "slots"; sourceComponent: SlotsPage { app: window.app } }
                PageHolder { name: "channels"; sourceComponent: ChannelsPage { app: window.app } }
                PageHolder { name: "states"; sourceComponent: StatesPage { app: window.app } }
                PageHolder { name: "settings"; sourceComponent: SettingsPage { app: window.app } }
            }
        }

        LogPanel {
            objectName: "logPanel"
            app: window.app
            visible: false
            SplitView.preferredHeight: 200
        }
    }
}
