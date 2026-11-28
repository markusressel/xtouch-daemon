// The names `auto` strips show for applications: a row each (the application as the sound server reports it, and the
// label of up to 7 characters), added and removed in place. A name that is empty or twice is marked.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls
import XTouch.Forms

Flickable {
    id: pane
    required property QtObject app
    readonly property QtObject aliases: app.settings.aliases
    readonly property QtObject tools: app.settings.sections.device.form.tools

    contentWidth: width
    contentHeight: body.height + 2 * Theme.space.xl
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar {}

    Column {
        id: body
        x: Theme.space.xl
        y: Theme.space.xl
        width: Math.min(pane.width - 2 * Theme.space.xl, 900)
        spacing: Theme.space.m

        Row {
            spacing: Theme.space.m
            Label {
                text: "Aliases"
                font.pointSize: Theme.fontSize.title
                font.bold: true
                color: Theme.colors.text
                anchors.verticalCenter: parent.verticalCenter
            }
            Label { text: "[aliases]"; color: Theme.colors.text_muted; anchors.verticalCenter: parent.verticalCenter }
        }
        HelpLabel { width: parent.width; text: pane.tools.help(pane.aliases.help, Theme.mode, pane.aliases.link, "") }

        Card {
            width: parent.width
            Row {
                width: parent.width
                spacing: Theme.space.s
                Label { width: (parent.width - 40 - 2 * parent.spacing) * 0.6; text: "Application, as the sound server reports it"; color: Theme.colors.text_muted; font.pointSize: Theme.fontSize.caption; wrapMode: Text.Wrap }
                Label { width: (parent.width - 40 - 2 * parent.spacing) * 0.4; text: "Label (up to " + pane.aliases.labelWidth + " characters)"; color: Theme.colors.text_muted; font.pointSize: Theme.fontSize.caption; wrapMode: Text.Wrap }
            }

            ListView {
                id: list
                objectName: "alias_list"
                width: parent.width
                height: contentHeight
                interactive: false
                spacing: Theme.space.xs
                model: pane.aliases.rows

                add: Transition {
                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.fade }
                    NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.resize; easing.type: Easing.OutCubic }
                }
                remove: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.fade } }
                displaced: Transition { NumberAnimation { property: "y"; duration: Theme.resize; easing.type: Easing.OutCubic } }

                delegate: Item {
                    id: line
                    required property string key
                    required property var row
                    objectName: "alias_" + key
                    width: ListView.view.width
                    height: Theme.controlHeight

                    Row {
                        width: parent.width
                        spacing: Theme.space.s
                        TextField {
                            id: name
                            objectName: "alias_name_" + line.key
                            width: (parent.width - 40 - 2 * parent.spacing) * 0.6
                            placeholderText: "e.g. WEBRTC VoiceEngine"
                            problem: line.row.nameProblem
                            onTextEdited: { pane.aliases.setName(line.key, text); suggestions.refresh(text) }
                            onActiveFocusChanged: if (activeFocus) suggestions.refresh(text)
                            onPressed: if (!suggestions.opened) suggestions.refresh(text)
                            Keys.onPressed: event => { if (suggestions.handleKey(event)) event.accepted = true }
                            SuggestionList {
                                id: suggestions
                                field: name
                                provider: text => pane.aliases.suggestions(text, Theme.mode)
                                onPicked: value => { name.text = value; pane.aliases.setName(line.key, value) }
                            }
                        }
                        TextField {
                            id: alias
                            objectName: "alias_alias_" + line.key
                            width: (parent.width - 40 - 2 * parent.spacing) * 0.4
                            maximumLength: pane.aliases.labelWidth
                            placeholderText: "e.g. Discord"
                            problem: line.row.aliasProblem
                            onTextEdited: pane.aliases.setAlias(line.key, text)
                        }
                        IconButton {
                            objectName: "alias_remove_" + line.key
                            anchors.verticalCenter: parent.verticalCenter
                            name: "delete-outline"
                            tip: "Remove the alias"
                            onClicked: pane.aliases.remove(line.key)
                        }
                    }
                    // only the texts that differ are set: typing is not disturbed
                    Binding { target: name; property: "text"; value: line.row.name; restoreMode: Binding.RestoreNone }
                    Binding { target: alias; property: "text"; value: line.row.alias; restoreMode: Binding.RestoreNone }
                }
            }

            Reveal {
                width: parent.width
                shown: pane.aliases.rest.length > 0
                Label {
                    objectName: "alias_problems"
                    width: parent.width
                    text: pane.aliases.rest.join("\n")
                    wrapMode: Text.Wrap
                    color: Theme.colors.error
                    font.pointSize: Theme.fontSize.caption
                }
            }

            Button {
                objectName: "alias_add"
                icon.source: "image://icon/plus"
                text: "Add alias"
                onClicked: {
                    const key = pane.aliases.add()
                    Qt.callLater(() => {
                        const item = list.itemAtIndex(list.count - 1)
                        if (item) item.children[0].children[0].forceActiveFocus()
                    })
                }
            }
        }
    }
}
