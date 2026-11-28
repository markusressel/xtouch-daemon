// The menus of the window (File, Edit, View, Help; window/menus.py), the icon of the project before them and the
// service after them. A menu opens inside the window under its title: Alt and its letter opens it, the mouse over
// another title while one is open switches, Left and Right go to the next menu.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Rectangle {
    id: bar
    required property QtObject app
    readonly property QtObject shell: app.shell
    /// the index of the menu that is open, -1 for none
    property int open: -1
    /// the menus, by the index of their title
    property var menuItems: []

    objectName: "menuBar"
    implicitHeight: Theme.controlHeight + Theme.space.s
    color: Theme.colors.chrome
    Behavior on color { ColorAnimation { duration: Theme.fade } }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.colors.border }

    function toggle(index, byKey, wasOpen) {
        // a click on the title of the menu that is open closes it
        if (open === index || wasOpen) {
            menuItems[index].close()
            return
        }
        show(index, byKey)
    }
    function show(index, byKey) {
        if (open >= 0 && open !== index) menuItems[open].close()
        open = index
        menuItems[index].open()
        if (byKey) menuItems[index].currentIndex = 0
    }
    function step(by) {
        const next = (open + by + menuItems.length) % menuItems.length
        show(next, true)
    }

    RowLayout {
        anchors { fill: parent; leftMargin: Theme.space.s; rightMargin: Theme.space.s; bottomMargin: 1 }
        spacing: 0

        Image {
            source: bar.shell.logo
            sourceSize: Qt.size(20, 20)
            Layout.rightMargin: Theme.space.s
        }

        Repeater {
            model: bar.shell.menus
            delegate: ToolButton {
                id: title
                required property var modelData
                required property int index
                objectName: "menubar_" + modelData.id
                text: modelData.text.replace("&", "")
                focusPolicy: Qt.NoFocus
                checked: bar.open === index
                // the menu closes when the mouse is let go outside of it, also on its own title: it must not open again
                property bool wasOpen: false
                onPressed: wasOpen = bar.open === index
                onClicked: bar.toggle(index, false, wasOpen)
                onHoveredChanged: if (hovered && bar.open >= 0 && bar.open !== index) bar.show(index, false)
                Accessible.name: text

                AppMenu {
                    id: menuOfTitle
                    shell: bar.shell
                    entries: title.modelData.entries
                    y: title.height
                    objectName: "menu_" + title.modelData.id
                    onClosed: if (bar.open === title.index) bar.open = -1
                    Component.onCompleted: bar.registerMenu(title.index, menuOfTitle)
                }
            }
        }

        Item { Layout.fillWidth: true }

        Label { text: "Service"; color: Theme.colors.text_muted; font.pointSize: Theme.fontSize.caption }
        Pill {
            id: servicePill
            objectName: "service_pill"
            Layout.leftMargin: Theme.space.s
            clickable: true
            text: bar.shell.serviceControls.pillText
            tone: bar.shell.serviceControls.pillTone
            property string tip: bar.shell.serviceControls.pillTip
            onClicked: servicePopover.open()
            DetailsPopover { id: servicePopover; anchor: servicePill; details: bar.shell.serviceControls.popover; objectName: "service_details" }
        }
        Button {
            objectName: "service_button"
            visible: bar.shell.serviceControls.buttonShown
            text: bar.shell.serviceControls.buttonLabel
            highlighted: bar.shell.serviceControls.buttonPrimary
            property string tip: bar.shell.serviceControls.buttonHint
            focusPolicy: Qt.NoFocus
            Layout.leftMargin: Theme.space.s
            onClicked: bar.shell.serviceControls.act()
        }
    }

    function registerMenu(index, menu) {
        const found = menuItems.slice()
        found[index] = menu
        menuItems = found
    }

    // Alt and the letter of a title opens its menu
    Repeater {
        model: bar.shell.menus
        delegate: Item {
            required property var modelData
            required property int index
            Shortcut {
                sequence: "Alt+" + modelData.text.charAt(modelData.text.indexOf("&") + 1)
                context: Qt.ApplicationShortcut
                onActivated: bar.toggle(index, true)
            }
        }
    }
    // Left and Right go to the neighbouring menu, unless a submenu is open: it takes them
    Shortcut {
        sequence: "Left"
        enabled: bar.open >= 0 && !bar.menuItems[bar.open].subOpen
        context: Qt.ApplicationShortcut
        onActivated: bar.step(-1)
    }
    Shortcut {
        sequence: "Right"
        enabled: bar.open >= 0 && !bar.menuItems[bar.open].subOpen
        context: Qt.ApplicationShortcut
        onActivated: bar.step(1)
    }
}
