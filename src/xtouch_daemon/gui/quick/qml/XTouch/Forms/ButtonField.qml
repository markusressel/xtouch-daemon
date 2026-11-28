// A button of a strip (or of `[controls]`): what a press does, what a hold does and what its LED shows, each a list of
// what it can be, also typed (`mode:gaming`, `run: prog arg`, `service: light.toggle`). Unset, each shows what the strip
// type does (its placeholder). A service of Home Assistant a press calls and an entity an LED shows have their options
// below the list. The texts of the parts are kept here; what they are for the file is decided by the form.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: field
    required property Item row
    readonly property QtObject form: row.form
    readonly property string name: row.spec.name
    property var texts: ({})
    property var kept: ({})
    readonly property var view: form.buttonView(name, texts, kept)

    implicitHeight: column.implicitHeight

    function load() {
        const loaded = form.buttonLoad(name, row.value)
        texts = loaded.texts
        kept = loaded.kept
    }

    function show() {
        // a value that is what the texts make is one of ours: the texts stay as typed
        const made = form.buttonEdit(name, texts, kept)
        if (JSON.stringify(made.value ?? null) !== JSON.stringify(row.value)) load()
    }

    Component.onCompleted: load()
    Connections {
        target: field.row
        function onValueChanged() { field.show() }
    }

    function setText(part, text) {
        const next = Object.assign({}, texts)
        next[part] = text
        texts = next
        send()
    }

    function setTable(part, table) {
        const nextKept = Object.assign({}, kept)
        nextKept[part] = table
        kept = nextKept
        const next = Object.assign({}, texts)
        next[part] = form.tools.programText(table)
        texts = next
        send()
    }

    function send() {
        const made = form.buttonEdit(name, texts, kept)
        kept = made.kept
        row.edit(made.isNone ? null : made.value)
    }

    Column {
        id: column
        width: parent.width
        spacing: Theme.space.xs

        Repeater {
            model: field.view.parts
            Column {
                id: part
                required property var modelData
                required property int index
                width: column.width
                spacing: Theme.space.xs
                Row {
                    spacing: Theme.space.s
                    Label {
                        width: 56
                        height: Theme.controlHeight
                        verticalAlignment: Text.AlignVCenter
                        text: part.modelData.title
                    }
                    TypedChoice {
                        objectName: "button_" + field.name + "_" + part.modelData.name
                        width: Math.max(180, Math.min(320, column.width - 56 - Theme.space.s))
                        items: part.modelData.items
                        typed: part.modelData.editable
                        text: field.texts[part.modelData.name] ?? ""
                        placeholder: part.modelData.placeholder
                        toolTip: part.modelData.tip
                        problem: field.row.problem
                        onEdited: text => field.setText(part.modelData.name, text)
                    }
                }
                Reveal {
                    width: parent.width
                    shown: !!part.modelData.table
                    Item {
                        width: parent.width
                        height: table.height
                        EntityTable {
                            id: table
                            x: 56 + Theme.space.s
                            width: parent.width - x
                            form: field.form
                            columns: field.row.spec.columns[part.index].tableColumns
                            marker: part.modelData.marker
                            sets: field.row.spec.columns[part.index].tableSets
                            value: part.modelData.table ?? {}
                            titleWidth: 80
                            onChanged: table => field.setTable(part.modelData.name, table)
                        }
                    }
                }
            }
        }

        Reveal {
            width: parent.width
            shown: field.view.meaning !== ""
            HelpLabel {
                objectName: "meaning_" + field.name
                width: parent.width
                text: field.form.tools.help(field.view.meaning, Theme.mode, "", "")
            }
        }
    }
}
