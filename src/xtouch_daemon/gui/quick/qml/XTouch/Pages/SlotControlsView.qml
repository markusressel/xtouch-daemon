// The controls of the slot picked (`[controls].<n>`): a box per entry with its When, the parts it sets and a way to
// add one, and a way to add an entry. The fields of the parts are the option rows of the forms (a placeholder here).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Column {
    id: view
    required property QtObject controls
    objectName: "slot_controls"
    spacing: Theme.space.xs

    SectionHeader {
        text: view.controls.title
        topPadding: Theme.space.m
    }
    SlotFadeText {
        width: parent.width
        markup: view.controls.help
        onWidthChanged: {}
    }

    SlotList {
        id: entries
        width: parent.width
        spacing: Theme.space.s
        model: view.controls.entries
        delegate: Rectangle {
            id: box
            required property var row
            required property string key
            objectName: "entry_" + row.index
            width: ListView.view.width
            implicitHeight: inner.implicitHeight + 2 * Theme.space.s
            height: implicitHeight
            Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
            radius: Theme.radius.large
            color: Theme.colors.sunken
            border.width: row.error !== "" ? 2 : 1
            border.color: row.error !== "" ? Theme.colors.error : Theme.colors.border
            Behavior on border.color { ColorAnimation { duration: Theme.fade } }

            ColumnLayout {
                id: inner
                x: Theme.space.m
                y: Theme.space.s
                width: box.width - Theme.space.m - Theme.space.s
                spacing: Theme.space.xs

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space.xs
                    SlotFadeText {
                        Layout.fillWidth: true
                        text: box.row.title
                        color: Theme.colors.text_muted
                        bold: true
                        wrapMode: Text.NoWrap
                        pointSize: Theme.fontSize.caption
                    }
                    IconButton {
                        visible: box.row.many
                        name: "arrow-up"
                        tip: "Move the entry up: it acts before the ones below"
                        enabled: box.row.canUp
                        onClicked: view.controls.moveEntry(box.row.index, -1)
                    }
                    IconButton {
                        visible: box.row.many
                        name: "arrow-down"
                        tip: "Move the entry down"
                        enabled: box.row.canDown
                        onClicked: view.controls.moveEntry(box.row.index, 1)
                    }
                    IconButton {
                        name: "delete-outline"
                        tip: "Remove the entry"
                        onClicked: view.controls.removeEntry(box.row.index)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space.s
                    Label { text: "When" }
                    ConditionField {
                        id: when
                        objectName: "entry_when_" + box.row.index
                        Layout.fillWidth: true
                        text: box.row.when
                        present: false
                        states: view.controls.whenStates
                        targets: view.controls.whenTargets
                        onCommitted: text => view.controls.setWhen(box.row.index, text)
                    }
                }
                SlotFadeText {
                    Layout.fillWidth: true
                    markup: box.row.whenHelp
                }
                Label {
                    visible: box.row.whenError !== ""
                    Layout.fillWidth: true
                    text: box.row.whenError
                    color: Theme.colors.error
                    wrapMode: Text.Wrap
                }
                // the parts the entry sets: the option rows of the forms
                SlotControlParts {
                    Layout.fillWidth: true
                    controls: view.controls
                    entryIndex: box.row.index
                    optionPath: box.row.path
                    parts: box.row.parts
                    hasId: box.row.hasId
                }
                SlotChoice {
                    objectName: "add_part_" + box.row.index
                    visible: box.row.missing.length > 0
                    placeholder: "Add a part"
                    tip: "Claims another part of the slot in this entry"
                    items: box.row.missing
                    onPicked: name => view.controls.addPart(box.row.index, name)
                }
                Label {
                    visible: box.row.error !== ""
                    Layout.fillWidth: true
                    text: box.row.error
                    color: Theme.colors.error
                    wrapMode: Text.Wrap
                }
            }
        }
    }

    SlotChoice {
        objectName: "add_controls"
        placeholder: view.controls.addPlaceholder
        tip: view.controls.addTip
        items: view.controls.addChoices
        onPicked: name => view.controls.addEntry(name)
    }
    Label {
        visible: view.controls.error !== ""
        width: parent.width
        text: view.controls.error
        color: Theme.colors.error
        wrapMode: Text.Wrap
    }
}
