// A text of an option (a name, a secret, a file, the data of a service): its placeholder shows the default; the
// suggestions of the sound server, the voice chat or Home Assistant open under it while it has the focus (the field
// keeps it), and a secret hides itself behind an eye, a file has a button to pick it.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: field
    required property Item row
    readonly property var spec: row.spec
    readonly property string kind: spec.kind
    readonly property bool suggests: row.suggestKey !== ""
    readonly property string text: edit.text
    readonly property alias input: edit
    // what is in the file: the default is the placeholder, not the text
    readonly property string shownText: kind === "data" ? row.form.tools.dataText(row.value) : typeof row.value === "string" ? row.value : ""

    implicitHeight: edit.implicitHeight

    TextField {
        id: edit
        objectName: "field_" + field.spec.name
        anchors { left: parent.left; right: buttons.left; rightMargin: buttons.width > 0 ? Theme.space.xs : 0; verticalCenter: parent.verticalCenter }
        placeholderText: field.row.placeholder
        maximumLength: field.spec.maxLength ?? 32767
        echoMode: field.kind === "secret" && !eye.checked ? TextInput.Password : TextInput.Normal
        problem: field.row.problem
        onTextEdited: {
            if (field.suggests) { list.typed = true; list.refresh(text) }
            field.row.edit(field.kind === "data" ? field.row.form.tools.parseData(text) : text)
        }
        onActiveFocusChanged: if (activeFocus && field.suggests && !list.opened) { list.typed = false; list.refresh(text) }
        onPressed: if (field.suggests && !list.opened) { list.typed = false; list.refresh(text) }
        Keys.onPressed: event => { if (field.suggests && list.handleKey(event)) event.accepted = true }
    }

    Binding { target: edit; property: "text"; value: field.shownText; restoreMode: Binding.RestoreNone }

    Row {
        id: buttons
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        spacing: Theme.space.xs
        IconButton {
            id: eye
            visible: field.kind === "secret"
            name: checked ? "eye-off" : "eye"
            tip: "Show it"
            checkable: true
        }
        IconButton {
            visible: field.kind === "path"
            name: "folder-open"
            tip: "Choose the file"
            onClicked: {
                const path = field.row.form.tools.chooseFile("Choose " + field.spec.title.toLowerCase(), edit.text || edit.placeholderText || "~")
                if (path !== "") { edit.text = path; field.row.edit(path) }
            }
        }
    }

    SuggestionList {
        id: list
        field: edit
        entities: field.row.suggestKey.startsWith("@")
        listWidth: entities ? 400 : 360
        provider: text => field.row.form.suggestions(field.row.suggestKey, field.row.suggestLine, text, Theme.mode)
        onPicked: value => {
            edit.text = value
            const extra = field.row.form.picked(field.row.suggestKey, field.row.suggestLine, value)
            field.row.edit(value)
            field.row.picked(value, extra)
        }
        onForgotten: value => {
            field.row.form.forget(field.row.suggestKey, field.row.suggestLine, value)
            refresh(edit.text)
        }
    }
    Connections {
        target: field.row.form.tools
        function onAudioChanged() { if (list.opened) list.refresh(edit.text) }
        function onEntitiesChanged() { if (list.opened) list.refresh(edit.text) }
    }
}
