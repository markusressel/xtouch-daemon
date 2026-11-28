// The window: the menus on top, the footer at the bottom, and between them the configuration (the rail and its pages)
// with the panels Device and Log at the side the user put them (default: the Device above, the Log under, hidden), or
// in a window of their own. The shell (`app.shell`) says what the menus and the footer show and do.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQml
import XTouch
import XTouch.Controls
import XTouch.Device
import XTouch.Pages

ApplicationWindow {
    id: window
    required property QtObject app
    readonly property QtObject shell: app.shell

    objectName: "window"
    title: shell.title
    width: Math.min(1280, Screen.desktopAvailableWidth)
    height: Math.min(1000, Screen.desktopAvailableHeight)
    visible: true

    menuBar: AppMenuBar { id: menuBar; app: window.app }
    footer: Footer { app: window.app }

    onClosing: close => { if (!shell.closeAllowed()) close.accepted = false }
    Component.onCompleted: {
        shell.attach(window, Theme.backend)
        arrange()
    }

    Connections {
        target: window.shell
        function onCloseRequested() { window.close() }
        function onKeysRequested() { keysPopover.open() }
    }

    // the keys of the menus, wherever the focus is in the application
    Instantiator {
        model: window.shell.shortcuts
        delegate: Shortcut {
            required property var modelData
            sequence: modelData.sequence
            context: Qt.ApplicationShortcut
            enabled: window.shell.disabled.indexOf(modelData.id) < 0
            onActivated: window.shell.trigger(modelData.id)
        }
    }

    DetailsPopover { id: keysPopover; anchor: menuBar; details: window.shell.keysPopover; objectName: "keys_details" }
    DialogHost { dialogs: window.shell.dialogs }

    // -- the panels -----------------------------------------------------------------------------------------------

    readonly property var panelItems: ({ device: devicePanel, log: logPanel })
    readonly property var panelModels: ({ device: shell.panels.device, log: shell.panels.log })

    // The panels are built once, in `Dock`s. Each side of the configuration has a `Host` per panel: a split item that
    // shows while its panel is shown at that side (a split ignores what is not visible). A dock goes into its
    // host, into the window of its panel, or is parked: items that come and go would leave a split stale.
    function arrange() {
        for (const name of ["device", "log"]) {
            const model = panelModels[name], item = panelItems[name]
            let target = parking
            if (model.shown) {
                target = model.place === "window" ? (name === "device" ? deviceWindow : logWindow).contentItem : hosts[name + "_" + model.place]
            }
            item.parent = target
        }
    }
    Connections { target: window.panelModels.device; function onChanged() { window.arrange() } }
    Connections { target: window.panelModels.log; function onChanged() { window.arrange() } }

    // what the user dragged the handles to is kept when they let go
    function keepSizes() {
        for (const name of ["device", "log"]) {
            const model = panelModels[name], item = hosts[name + "_" + model.place]
            if (!model.shown || !item) continue
            if (model.place === "top" || model.place === "bottom") model.setSize(Math.round(item.height))
            else model.setSize(Math.round(item.width))
        }
    }

    Item { id: parking; visible: false }

    component Host: Item {
        required property string name
        required property string side
        readonly property var model: window.panelModels[name]
        readonly property bool vertical: side === "top" || side === "bottom"
        visible: model.shown && model.place === side
        SplitView.preferredHeight: model.size
        SplitView.preferredWidth: model.size
        SplitView.minimumHeight: vertical ? (name === "log" ? log.leastHeight : 120) : 0
        SplitView.minimumWidth: vertical ? 0 : 240
        SplitView.fillWidth: false
        SplitView.fillHeight: false
    }

    component Dock: Item {
        anchors.fill: parent
    }

    readonly property var hosts: ({
        device_top: deviceTop, device_bottom: deviceBottom, device_left: deviceLeft, device_right: deviceRight,
        log_top: logTop, log_bottom: logBottom, log_left: logLeft, log_right: logRight
    })

    SplitView {
        id: outer
        objectName: "panes"
        anchors.fill: parent
        orientation: Qt.Vertical
        onResizingChanged: if (!resizing) window.keepSizes()

        Host { id: deviceTop; name: "device"; side: "top" }
        Host { id: logTop; name: "log"; side: "top" }

        Item {
            id: middle
            objectName: "middle"
            SplitView.fillHeight: true
            SplitView.minimumHeight: 200

            SplitView {
                id: inner
                anchors.fill: parent
                orientation: Qt.Horizontal
                onResizingChanged: if (!resizing) window.keepSizes()

                Host { id: deviceLeft; name: "device"; side: "left" }
                Host { id: logLeft; name: "log"; side: "left" }

                Item {
                    id: configuration
                    objectName: "configuration"
                    SplitView.fillWidth: true
                    SplitView.fillHeight: true
                    SplitView.minimumWidth: 400

                    Rail {
                        id: rail
                        app: window.app
                        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                    }

                    ColumnLayout {
                        anchors { left: rail.right; right: parent.right; top: parent.top; bottom: parent.bottom
                                  topMargin: Theme.space.l; leftMargin: Theme.space.m }
                        spacing: Theme.space.s

                        // what the daemon said about the preview, and the file that changed on disk
                        Reveal {
                            objectName: "preview_message"
                            shown: window.shell.bar.message !== undefined && window.shell.bar.message !== ""
                            Layout.fillWidth: true
                            Layout.rightMargin: Theme.space.xl
                            Banner {
                                width: parent.width
                                tone: "bad"
                                text: window.shell.bar.message ? window.shell.bar.message : ""
                            }
                        }
                        Reveal {
                            objectName: "disk_bar"
                            shown: window.shell.diskMessage !== ""
                            Layout.fillWidth: true
                            Layout.rightMargin: Theme.space.xl
                            Banner {
                                width: parent.width
                                text: window.shell.diskMessage
                                Button {
                                    objectName: "disk_reload"
                                    text: "Reload"
                                    icon.source: "image://icon/file-refresh-outline"
                                    property string tip: "Read the file again and drop the changes here (Undo brings them back)"
                                    onClicked: window.shell.reload()
                                }
                                Button {
                                    objectName: "disk_keep"
                                    text: "Keep mine"
                                    property string tip: "Go on with the changes here: Save and apply overwrites the file on disk"
                                    onClicked: window.shell.keepMine()
                                }
                            }
                        }

                        Item {
                            id: pages
                            Layout.fillWidth: true
                            Layout.fillHeight: true

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
                }


                Host { id: deviceRight; name: "device"; side: "right" }
                Host { id: logRight; name: "log"; side: "right" }
            }
        }

        Host { id: deviceBottom; name: "device"; side: "bottom" }
        Host { id: logBottom; name: "log"; side: "bottom" }
    }

    Dock {
        id: devicePanel
        parent: parking
        DevicePanel { objectName: "devicePanel"; anchors.fill: parent; app: window.app }
    }

    Dock {
        id: logPanel
        parent: parking
        LogPanel { id: log; anchors.fill: parent; app: window.app }
    }

    // -- the windows of the panels that went out of the window -----------------------------------------------------

    component PanelWindow: ApplicationWindow {
        required property var model
        title: model.title
        width: 720
        height: Math.max(320, model.size)
        visible: window.visible && model.shown && model.place === "window"
        transientParent: window
        onClosing: model.setShown(false)
    }
    PanelWindow { id: deviceWindow; objectName: "deviceWindow"; model: window.panelModels.device }
    PanelWindow { id: logWindow; objectName: "logWindow"; model: window.panelModels.log }
}
