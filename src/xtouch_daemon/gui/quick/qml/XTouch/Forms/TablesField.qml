// A list of tables (the devices of a strip, its profiles): a card per entry that says what it is and opens into its
// options (one open at a time); a grip to move it (drag, or Ctrl+Up and Ctrl+Down), a pencil to open it (or a double
// click) and a trash can to remove it. "Add" adds an entry that is in the file only once it has something in it.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: tables
    required property Item row
    readonly property QtObject form: row.form
    readonly property var spec: row.spec
    // entries the file does not have yet: new ones with nothing in them
    property int blank: 0
    property int opened: -1
    property int dropAt: -1
    readonly property var entries: {
        const found = row.shown && row.shown.length !== undefined ? Array.from(row.shown) : []
        for (let i = 0; i < blank; i++) found.push({})
        return found
    }
    readonly property int count: entries.length

    implicitHeight: column.implicitHeight

    function commit(list) {
        const written = form.tools.tableCommitted(list)
        blank = Math.max(0, list.length - written.length)
        row.edit(written.length === 0 ? null : written)
    }

    function put(index, name, value) {
        commit(form.tools.tablePut(entries, index, name, value))
    }

    function add() {
        blank += 1
        opened = entries.length - 1
    }

    function remove(index) {
        commit(form.tools.tableRemove(entries, index))
        if (opened === index) opened = -1
        else if (opened > index) opened -= 1
    }

    function move(index, delta) {
        const moved = form.tools.tableMove(entries, index, delta)
        if (moved.index === index) return
        if (opened === index) opened = moved.index
        commit(moved.entries)
        Qt.callLater(() => { const entry = list.itemAtIndex(moved.index); if (entry) entry.forceActiveFocus() })
    }

    function drop(index, before) {
        const moved = form.tools.tableDrop(entries, index, before)
        if (opened === index) opened = moved.index
        commit(moved.entries)
    }

    Column {
        id: column
        width: parent.width
        spacing: Theme.space.xs

        ListView {
            id: list
            width: parent.width
            height: contentHeight
            interactive: false
            spacing: Theme.space.xs
            model: tables.count
            reuseItems: false

            add: Transition {
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.fade }
                NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.resize; easing.type: Easing.OutCubic }
            }
            remove: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.fade } }
            displaced: Transition { NumberAnimation { property: "y"; duration: Theme.resize; easing.type: Easing.OutCubic } }

            delegate: TableEntry {
                required property int index
                width: ListView.view.width
                field: tables
                position: index
                entry: tables.entries[index] ?? ({})
            }
        }

        Button {
            objectName: "add_" + tables.spec.name
            icon.source: "image://icon/plus"
            text: "Add"
            onClicked: tables.add()
        }
    }
}
