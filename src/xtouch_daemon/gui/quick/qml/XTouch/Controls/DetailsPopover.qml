// What a pill means in full, a click away: a heading, an intro, and a row per thing with its status, its explanation and
// its buttons (the QML side of `Details` of details.py). The rows are made when it opens; a button closes it first,
// the buttons next to the heading and the switches of a row leave it open.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import QtQuick.Layouts
import XTouch

Popover {
    id: root
    required property QtObject details
    objectName: "details"
    title: details.heading
    preferredWidth: 440

    onAboutToShow: { details.refresh(); details.isOpen = true }
    onClosed: details.isOpen = false

    function toneColor(tone) {
        return tone === "good" ? Theme.colors.tone_good : tone === "warn" ? Theme.colors.tone_warn
            : tone === "bad" ? Theme.colors.tone_bad : Theme.colors.tone_neutral
    }

    Row {
        visible: root.details.headerActions.length > 0
        spacing: Theme.space.xs
        Repeater {
            model: root.details.headerActions
            Button {
                required property string modelData
                required property int index
                objectName: "details_header_" + index
                text: modelData
                focusPolicy: Qt.TabFocus
                onClicked: root.details.header(index)
            }
        }
    }

    HelpText {
        visible: text !== ""
        text: root.details.intro
        Layout.fillWidth: true
        textFormat: Text.RichText
    }

    Repeater {
        model: root.details.entries
        delegate: Item {
            id: holder
            required property var modelData
            required property int index
            readonly property var row: modelData
            readonly property int at: index
            Layout.fillWidth: true
            implicitHeight: loader.implicitHeight
            Loader {
                id: loader
                width: parent.width
                sourceComponent: holder.row.group ? groupRow : entryRow
            }

        Component {
            id: groupRow
            ColumnLayout {
                spacing: Theme.space.xs
                Label {
                    text: row.title
                    font.bold: true
                    Layout.topMargin: Theme.space.xs
                }
                HelpText {
                    visible: row.text !== ""
                    text: row.text
                    textFormat: Text.RichText
                    Layout.fillWidth: true
                }
            }
        }

        Component {
            id: entryRow
            Rectangle {
                id: entry
                readonly property color hue: root.toneColor(row.tone)
                readonly property bool problem: row.tone === "warn" || row.tone === "bad"
                objectName: "details_row_" + at
                implicitHeight: content.implicitHeight + 2 * Theme.space.s
                radius: Theme.radius.small
                color: problem ? Theme.tint(hue, Theme.tintAlpha) : "transparent"
                Rectangle { width: 3; height: parent.height; color: entry.hue; radius: 1 }

                ColumnLayout {
                    id: content
                    anchors { left: parent.left; right: parent.right; top: parent.top
                              leftMargin: Theme.space.m; rightMargin: Theme.space.s; topMargin: Theme.space.s }
                    spacing: Theme.space.xs

                    RowLayout {
                        spacing: Theme.space.s
                        visible: row.title !== "" || row.status !== "" || row.actions.length > 0
                        ColorImage {
                            visible: row.icon !== ""
                            source: row.icon !== "" ? "image://icon/" + row.icon : ""
                            sourceSize: Qt.size(16, 16)
                            color: Theme.colors.text
                        }
                        Label {
                            visible: row.title !== ""
                            text: row.title
                            font.bold: true
                            color: row.entity !== "" ? Theme.colors[row.entity] : Theme.colors.text
                        }
                        Pill {
                            visible: row.status !== ""
                            text: row.status
                            tone: row.tone
                        }
                        Item { Layout.fillWidth: true }
                        Repeater {
                            model: row.actions
                            Button {
                                required property string modelData
                                required property int index
                                objectName: "details_action_" + at + "_" + index
                                text: modelData
                                highlighted: entry.problem && index === 0
                                onClicked: {
                                    const row = at, action = index
                                    root.close()
                                    root.details.run(row, action)
                                }
                            }
                        }
                    }
                    HelpText {
                        visible: row.text !== ""
                        text: row.text
                        textFormat: Text.RichText
                        Layout.fillWidth: true
                        Layout.maximumWidth: 400
                    }
                    Label {
                        visible: row.path !== ""
                        text: row.path
                        elide: Text.ElideMiddle
                        font.family: "monospace"
                        font.pointSize: Theme.fontSize.caption
                        Layout.fillWidth: true
                        Layout.maximumWidth: 400
                    }
                    Repeater {
                        model: row.items
                        RowLayout {
                            required property var modelData
                            spacing: Theme.space.s
                            Label { text: "•"; color: Theme.colors.text_muted }
                            Label { text: modelData.item; elide: Text.ElideRight; Layout.maximumWidth: 260 }
                            Label {
                                visible: modelData.note !== ""
                                text: modelData.note
                                color: Theme.colors.text_muted
                                font.pointSize: Theme.fontSize.caption
                            }
                        }
                    }
                    Row {
                        visible: row.toggles.length > 0
                        spacing: 0
                        Repeater {
                            model: row.toggles
                            Button {
                                required property var modelData
                                required property int index
                                text: modelData.text
                                checked: modelData.on
                                checkable: true
                                focusPolicy: Qt.NoFocus
                                onClicked: root.details.toggle(at, index, checked)
                            }
                        }
                    }
                }
            }
        }
        }
    }
}
