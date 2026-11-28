// The popover of a pill of the bar: a heading, what the pill means, and rows (a title, how it is doing, what it
// means, buttons and switches). The backend builds them (`device.popover(kind)`): a button calls `device.activate`
// after the popover closed, a switch calls `device.toggle` and the popover stays open.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Popover {
    id: popover
    required property QtObject device
    // `live`, `modes` or `virtual` (see `DevicePanel.popover`)
    property string kind: ""
    property var data: ({ "heading": "", "intro": "", "entries": [] })

    title: data.heading
    preferredWidth: 420
    onAboutToShow: data = device.popover(kind)

    function rich(text) {
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/`([^`]+)`/g, "<b>$1</b>")
    }
    function hue(tone) {
        return tone === "good" ? Theme.colors.tone_good : tone === "warn" ? Theme.colors.tone_warn
            : tone === "bad" ? Theme.colors.tone_bad : Theme.colors.tone_neutral
    }

    HelpText {
        objectName: "popoverIntro"
        visible: popover.data.intro !== ""
        text: popover.rich(popover.data.intro)
        Layout.fillWidth: true
    }

    Repeater {
        model: popover.data.entries

        ColumnLayout {
            id: entry
            required property var modelData
            required property int index
            objectName: "popoverEntry_" + (modelData.title !== "" ? modelData.title : index)
            Layout.fillWidth: true
            spacing: Theme.space.xs

            // a heading between rows
            SectionHeader {
                visible: entry.modelData.group
                text: entry.modelData.title
            }
            HelpText {
                visible: entry.modelData.group && entry.modelData.text !== ""
                text: popover.rich(entry.modelData.text)
                Layout.fillWidth: true
            }

            RowLayout {
                visible: !entry.modelData.group
                spacing: Theme.space.s
                Rectangle {
                    visible: !entry.modelData.group && entry.modelData.title === "" && entry.modelData.tone !== ""
                    implicitWidth: 3
                    Layout.fillHeight: true
                    color: popover.hue(entry.modelData.tone)
                }
                Label {
                    visible: !entry.modelData.group && entry.modelData.title !== ""
                    text: entry.modelData.title
                    font.bold: true
                    color: Theme.colors[entry.modelData.entity] !== undefined ? Theme.colors[entry.modelData.entity]
                        : Theme.colors.text
                }
                Pill {
                    visible: !entry.modelData.group && entry.modelData.statusText !== ""
                    text: entry.modelData.statusText
                    tone: entry.modelData.tone
                }
            }
            HelpText {
                visible: !entry.modelData.group && entry.modelData.text !== ""
                text: popover.rich(entry.modelData.text)
                Layout.fillWidth: true
            }
            Row {
                visible: !entry.modelData.group && entry.modelData.actions.length > 0
                spacing: Theme.space.xs
                Repeater {
                    model: entry.modelData.group ? [] : entry.modelData.actions
                    Button {
                        required property string modelData
                        required property int index
                        objectName: "popoverAction_" + modelData
                        text: modelData
                        // the first button of a problem stands out
                        highlighted: index === 0 && (entry.modelData.tone === "warn" || entry.modelData.tone === "bad")
                        onClicked: {
                            const at = entry.index
                            popover.close()
                            popover.device.activate(at, index)
                        }
                    }
                }
            }
            Flow {
                visible: !entry.modelData.group && entry.modelData.toggles.length > 0
                spacing: Theme.space.xs
                Layout.fillWidth: true
                Repeater {
                    model: entry.modelData.group ? [] : entry.modelData.toggles
                    Button {
                        required property var modelData
                        required property int index
                        objectName: "popoverToggle_" + modelData.text
                        text: modelData.text
                        checked: modelData.on
                        onClicked: {
                            popover.device.toggle(entry.index, index, !modelData.on)
                            popover.data = popover.device.popover(popover.kind)
                        }
                    }
                }
            }
        }
    }
}
