// A menu made from the data of window/menus.py (`entries`): entries with their shortcut and the line under them,
// separators, and submenus (made the same way). What an entry does and whether it is on or off the shell says.
import QtQuick
import QtQuick.Controls
import XTouch

Menu {
    id: menu
    required property QtObject shell
    // closed by a click outside of it when the mouse is let go (a press on its title would close and open it again)
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnReleaseOutside
    property var entries: []
    /// whether a submenu of this menu shows (the keys Left and Right then belong to it)
    readonly property bool subOpen: {
        for (let i = 0; i < count; ++i) {
            const sub = menuAt(i)
            if (sub && sub.visible) return true
        }
        return false
    }

    component EntryItem: MenuItem {
        required property var entry
        objectName: "menu_" + entry.id
        text: entry.text.replace("&", "")
        description: entry.description
        shortcutText: entry.shortcut
        checkable: entry.checkable
        checked: entry.checkable && menu.shell.checked.indexOf(entry.id) >= 0
        enabled: menu.shell.disabled.indexOf(entry.id) < 0
        // a checkable entry is a switch of the shell, which says if it is on: the item doesn't flip itself
        onTriggered: {
            if (entry.checkable) checked = Qt.binding(() => entry.checkable && menu.shell.checked.indexOf(entry.id) >= 0)
            menu.shell.trigger(entry.id)
        }
    }

    // the entries the menu made: a menu (no item) can't be their parent, and without a reference the garbage collector
    // of JavaScript would take them (e.g. while a large page loads)
    property var made: []

    Component.onCompleted: {
        const submenu = Qt.createComponent("AppMenu.qml")
        for (const entry of entries) {
            if (entry.id === "-")
                menu.addItem(keep(separator.createObject(null)))
            else if (entry.entries) {
                const sub = submenu.createObject(menu, {shell: menu.shell, entries: entry.entries,
                                                        title: entry.text.replace("&", ""), objectName: "menu_" + entry.text.replace("&", "")})
                menu.addMenu(sub)
            }
            else
                menu.addItem(keep(item.createObject(null, {entry: entry})))
        }
    }

    function keep(object) {
        made.push(object)
        return object
    }

    Component { id: separator; MenuSeparator {} }
    Component { id: item; EntryItem {} }
}
