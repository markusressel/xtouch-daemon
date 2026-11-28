// A list of names as chips that wrap like text, and a field to add one: Enter (or a pick from the suggestions) adds
// it, the cross on a chip removes it. A preset (`@browsers`) is a chip with an outline only and tells what it stands for.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: field
    required property Item row
    readonly property var values: row.shown && row.shown.length !== undefined ? Array.from(row.shown) : []
    readonly property bool suggests: row.suggestKey !== ""
    readonly property string preset: row.spec.presets ?? ""

    implicitHeight: flow.implicitHeight

    function add(text) {
        const value = text.trim()
        if (value === "" || values.indexOf(value) >= 0) return
        row.edit([...values, value])
    }

    function remove(index) {
        row.edit(values.filter((_, at) => at !== index))
    }

    Flow {
        id: flow
        width: parent.width
        spacing: Theme.space.xs

        add: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.fade }
            NumberAnimation { property: "scale"; from: 0.8; to: 1; duration: Theme.resize; easing.type: Easing.OutCubic }
        }
        move: Transition { NumberAnimation { properties: "x,y"; duration: Theme.resize; easing.type: Easing.OutCubic } }

        Repeater {
            model: field.values
            Rectangle {
                id: chip
                required property string modelData
                required property int index
                objectName: "chip_" + modelData
                readonly property string tip: field.preset !== "" ? field.row.form.presetTip(field.row.spec.name, modelData) : ""
                readonly property bool isPreset: tip !== ""
                height: Theme.controlHeight - 6
                width: label.implicitWidth + remove.width + 2 * Theme.space.s
                radius: Theme.radius.pill
                color: isPreset ? "transparent" : Theme.tint(Theme.colors.accent, 2 * Theme.tintAlpha)
                border.width: 1
                border.color: isPreset ? Theme.colors.accent : Theme.colors.control_border
                Behavior on color { ColorAnimation { duration: Theme.fade } }
                Label {
                    id: label
                    x: Theme.space.s
                    anchors.verticalCenter: parent.verticalCenter
                    text: chip.modelData
                    color: Theme.colors.text
                }
                IconButton {
                    id: remove
                    objectName: "chip_remove_" + chip.modelData
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    width: 22
                    height: 22
                    name: "close"
                    tip: "Remove '" + chip.modelData + "'"
                    icon.width: 14
                    icon.height: 14
                    onClicked: field.remove(chip.index)
                }
                HoverHandler { id: hover }
                ToolTip.visible: hover.hovered && chip.tip !== ""
                ToolTip.text: chip.tip
            }
        }

        TextField {
            id: edit
            objectName: "add_" + field.row.spec.name
            width: Math.max(140, Math.min(field.width, 220))
            placeholderText: field.values.length === 0 ? "Add… (" + (field.row.placeholder || "") + ")" : "Add…"
            onAccepted: {
                field.add(text)
                text = ""
            }
            onTextEdited: if (field.suggests) { list.typed = true; list.refresh(text) }
            onActiveFocusChanged: if (activeFocus && field.suggests) { list.typed = false; list.refresh(text) }
            onPressed: if (field.suggests && !list.opened) { list.typed = false; list.refresh(text) }
            Keys.onPressed: event => { if (field.suggests && list.handleKey(event)) event.accepted = true }
        }
    }

    SuggestionList {
        id: list
        field: edit
        provider: text => field.row.form.suggestions(field.row.suggestKey, field.row.suggestLine, text, Theme.mode)
        onPicked: value => {
            field.add(value)
            edit.text = ""
            // the list wrote its value after the pick: once more when it is through
            Qt.callLater(() => edit.text = "")
        }
    }
}
