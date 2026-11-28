// The options of a table with an entity of Home Assistant, a row each: of a part bound to an entity (`entity`,
// `attribute`, `min`, ...) or of a press that calls a service (`service`, `entity`, `data`). The entity and its
// attribute suggest what Home Assistant has; an unset option says what it does by the domain of the entity. The
// `marker` (`entity` or `service`) stays in the table while empty.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Column {
    id: table
    required property QtObject form
    property var columns: []
    property string marker: "entity"
    property bool sets: false
    property string intro: ""
    property var value: ({})
    property var problems: ({})
    property real titleWidth: 96
    signal changed(var table)

    spacing: 0
    property string hint: ""
    function look() { hint = form.tools.entityHint() }
    Component.onCompleted: { form.tools.wantEntities(); look() }
    Connections {
        target: table.form.tools
        function onEntitiesChanged() { table.look() }
    }

    HelpLabel {
        visible: table.intro !== ""
        width: parent.width
        text: table.intro
        bottomPadding: Theme.space.xs
    }

    Repeater {
        model: table.columns
        OptionRow {
            id: nested
            required property var modelData
            width: table.width
            form: table.form
            nested: true
            spec: modelData
            titleWidth: table.titleWidth
            suggestKey: modelData.name === "entity" ? "@entity" : modelData.name === "attribute" ? "@attribute" : ""
            suggestLine: table.value
            start: () => table.form.entityStart(modelData.name, table.sets, table.value)
            hint: modelData.name === "entity" ? table.hint : ""
            onSettings: table.form.tools.showSettingsOfHomeAssistant()
            info: ({
                value: table.value[modelData.name] === undefined ? null : table.value[modelData.name],
                set: table.value[modelData.name] !== undefined && table.value[modelData.name] !== null,
                placeholder: table.form.entityPlaceholder(modelData.name, modelData.default, table.marker, table.sets, table.value),
                problems: (table.problems[modelData.name] ?? []).join("\n"),
                visible: true,
                resettable: false,
            })
            onValueEdited: value => table.changed(table.form.tools.entityPut(table.value, modelData.name, value, table.marker))
        }
    }
}
