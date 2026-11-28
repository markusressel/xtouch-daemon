// A part of a strip that can be bound: its words as without bindings (a choice, a switch or colors), and a button that
// binds it to Home Assistant, to one of its entities, to a program of your own or to a custom channel. Bound to a
// program or an entity, the options of that show below the field, each a row of its own.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: field
    required property Item row
    readonly property QtObject form: row.form
    readonly property var spec: row.spec
    readonly property string mode: row.info.mode ?? "words"
    readonly property bool inWords: row.info.inWords ?? true
    // the options of the program and of the entity as they were last: binding to one again brings them back
    property var kept: ({ program: {}, entity: { entity: "" } })
    readonly property var table: row.value !== null && typeof row.value === "object" ? row.value : ({})

    implicitHeight: column.implicitHeight

    function remember() {
        if (mode === "program") kept = Object.assign({}, kept, { program: table })
        else if (mode === "entity") kept = Object.assign({}, kept, { entity: table })
    }
    Component.onCompleted: remember()
    Connections {
        target: field.row
        function onValueChanged() { field.remember() }
    }

    function bind(next) {
        row.edit(form.bindValue(spec.name, next, kept))
    }

    function put(name, value) {
        const next = Object.assign({}, table)
        if (value === null) delete next[name]
        else next[name] = value
        row.edit(next)
    }

    Column {
        id: column
        width: parent.width
        spacing: Theme.space.xs

        Row {
            spacing: Theme.space.xs
            height: Theme.controlHeight

            ChoiceField {
                id: words
                visible: field.spec.base === "choice" && field.inWords
                row: field.row
                current: typeof field.row.value === "string" ? field.row.value : (field.row.value === null ? field.spec.default : null)
                placeholder: field.row.placeholder
                onChosen: value => field.row.edit(value)
            }
            Item {
                visible: field.spec.base === "switch" && field.inWords
                width: wordSwitch.implicitWidth
                height: Theme.controlHeight
                Switch {
                    id: wordSwitch
                    anchors.verticalCenter: parent.verticalCenter
                    objectName: "switch_" + field.spec.name
                    onToggled: field.row.edit(checked)
                }
                Binding { target: wordSwitch; property: "checked"; value: field.row.value === null ? field.spec.default === true : field.row.value === true; restoreMode: Binding.RestoreNone }
            }
            ColorField {
                visible: field.spec.base === "color" && field.inWords
                width: 300
                row: field.row
                current: typeof field.row.value === "string" ? field.row.value : field.spec.default
                onChosen: value => field.row.edit(value)
            }
            Label {
                visible: field.spec.base === "" && field.inWords
                anchors.verticalCenter: parent.verticalCenter
                text: field.row.value === null ? "not bound" : ""
                color: Theme.colors.text_muted
            }
            TypedChoice {
                id: channel
                visible: field.mode === "channel"
                width: 180
                objectName: "channel_" + field.spec.name
                items: (field.row.info.channels ?? []).map(name => ({ text: name, meaning: "" }))
                text: field.mode === "channel" ? (field.table.channel ?? "") : ""
                placeholder: "a custom channel"
                toolTip: "The `custom` channel whose value it sets"
                commitOnFinish: true
                onEdited: text => { if (field.mode === "channel" && text.trim() !== (field.table.channel ?? "")) field.row.edit({ channel: text.trim() }) }
                onPickedItem: text => field.row.edit({ channel: text })
            }
            ToolButton {
                id: bind
                objectName: "bind_" + field.spec.name
                visible: field.spec.modes.length > 1
                icon.source: "image://icon/link-variant"
                text: field.row.info.bindTitle ?? ""
                display: text !== "" ? AbstractButton.TextBesideIcon : AbstractButton.IconOnly
                ToolTip.visible: hovered
                ToolTip.text: field.row.info.bindTip ?? ""
                onClicked: menu.popup(0, bind.height)
                Menu {
                    id: menu
                    Repeater {
                        model: field.spec.modes
                        MenuItem {
                            required property var modelData
                            objectName: "bind_to_" + modelData.mode
                            text: modelData.title
                            checkable: true
                            checked: field.mode === modelData.mode
                            // "Not bound" shows while there is something to unbind
                            visible: modelData.mode !== "words" || field.row.value !== null
                            height: visible ? implicitHeight : 0
                            onTriggered: field.bind(modelData.mode)
                        }
                    }
                }
            }
        }

        Reveal {
            width: parent.width
            shown: field.mode === "program"
            Column {
                x: Theme.space.m
                width: parent.width - x
                HelpLabel { width: parent.width; text: field.spec.binding; bottomPadding: Theme.space.xs }
                Repeater {
                    model: field.spec.columns
                    OptionRow {
                        id: nested
                        required property var modelData
                        width: parent.width
                        form: field.form
                        nested: true
                        spec: modelData
                        titleWidth: 88
                        start: () => field.form.programStart(modelData.name, field.table)
                        info: ({
                            value: field.table[modelData.name] === undefined ? null : field.table[modelData.name],
                            placeholder: modelData.required ? "" : (field.spec.columnPlaceholders[modelData.name] ?? ""),
                            problems: (field.row.info.nested[modelData.name] ?? []).join("\n"),
                            resettable: false,
                        })
                        onValueEdited: value => field.put(modelData.name, value)
                    }
                }
            }
        }

        Reveal {
            width: parent.width
            shown: field.mode === "entity"
            Item {
                width: parent.width
                height: entity.height
                EntityTable {
                    id: entity
                    x: Theme.space.m
                    width: parent.width - x
                    form: field.form
                    columns: field.spec.tableColumns
                    marker: field.spec.tableMarker
                    sets: field.spec.tableSets
                    intro: field.spec.tableHelp
                    value: field.mode === "entity" ? field.table : field.kept.entity
                    problems: field.row.info.nested ?? ({})
                    titleWidth: 88
                    onChanged: table => field.row.edit(table)
                }
            }
        }
    }
}
