// What a state in the bar says: its value and why, its override (real, with ways to change it) and what Simulate
// does with it. An action closes the popover.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Popover {
    id: popover
    required property QtObject slots
    property var info: ({ name: "", unknown: true, entries: [] })

    title: info.name
    preferredWidth: 380

    Label {
        visible: popover.info.unknown
        Layout.fillWidth: true
        text: "The daemon doesn't tell this state yet."
        color: Theme.colors.text_muted
        wrapMode: Text.Wrap
    }
    Repeater {
        model: popover.info.entries
        ColumnLayout {
            id: entry
            required property var modelData
            Layout.fillWidth: true
            spacing: Theme.space.xs
            RowLayout {
                spacing: Theme.space.s
                Label {
                    visible: entry.modelData.title !== ""
                    text: entry.modelData.title
                    font.bold: true
                }
                Pill {
                    visible: entry.modelData.status !== ""
                    text: entry.modelData.status
                    tone: entry.modelData.tone
                }
            }
            SlotFadeText {
                Layout.fillWidth: true
                markup: entry.modelData.text.indexOf("<") >= 0 ? entry.modelData.text : ""
                text: entry.modelData.text
            }
            Flow {
                Layout.fillWidth: true
                spacing: Theme.space.xs
                Repeater {
                    model: entry.modelData.actions
                    Button {
                        required property var modelData
                        objectName: "state_action_" + modelData.id
                        text: modelData.text
                        onClicked: {
                            popover.slots.stateAction(modelData.id)
                            popover.close()
                        }
                    }
                }
            }
        }
    }
}
