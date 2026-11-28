// A text that can be picked from a list (what a press does: `launch`, `mode:gaming`, `run: ...`) or, with `typed` off,
// only picked. The list opens inside the window and says what each line means; typing narrows nothing: it lists all.
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: field
    property var items: []                   // [{ text, meaning }]
    property string text
    property string placeholder
    property bool typed: true
    property bool problem: false
    property bool commitOnFinish: false
    property string toolTip: ""
    property alias input: edit
    signal edited(string text)
    signal pickedItem(string text)

    implicitHeight: edit.implicitHeight
    implicitWidth: 180

    function rows(text) {
        const found = items.map(item => ({
            value: item.text,
            html: "<code>" + item.text + "</code>" + (item.meaning ? "<br><span style=\"color: " + Theme.colors.text_muted + "\">" + item.meaning.replace(/`([^`]*)`/g, "<code>$1</code>") + "</span>" : ""),
            tip: "", forget: false
        }))
        return { rows: found, empty: "Nothing to pick" }
    }

    TextField {
        id: edit
        objectName: field.objectName !== "" ? field.objectName + "_text" : ""
        anchors.fill: parent
        rightPadding: chevron.width + Theme.space.s
        readOnly: !field.typed
        placeholderText: field.placeholder
        problem: field.problem
        ToolTip.visible: hovered && field.toolTip !== ""
        ToolTip.text: field.toolTip
        onTextEdited: if (!field.commitOnFinish) field.edited(text)
        onEditingFinished: if (field.commitOnFinish) field.edited(text)
        onPressed: { forceActiveFocus(); if (!list.opened) list.refresh(text) }
        Keys.onPressed: event => {
            if (event.key === Qt.Key_Down && !list.opened) { list.refresh(text); event.accepted = true }
            else if (list.handleKey(event)) event.accepted = true
        }
        ColorImage {
            id: chevron
            anchors { right: parent.right; rightMargin: Theme.space.s; verticalCenter: parent.verticalCenter }
            width: 16; height: 16
            source: "image://icon/chevron-down"
            color: Theme.colors.text_muted
            rotation: list.opened ? 180 : 0
            Behavior on rotation { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
        }
    }
    Binding { target: edit; property: "text"; value: field.text; restoreMode: Binding.RestoreNone }

    SuggestionList {
        id: list
        field: edit
        provider: text => field.rows(text)
        onPicked: value => {
            edit.text = value
            field.pickedItem(value)
            field.edited(value)
        }
    }
}
