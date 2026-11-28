// The footer of the window, from the left: the problems, the sound server, the status line (or the tip of what the
// mouse is over), the restart of the service, what the device runs, where the preview shows, undo and redo, revert and
// save. What it shows is `app.shell`; it decides nothing.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Rectangle {
    id: footer
    required property QtObject app
    readonly property QtObject shell: app.shell
    readonly property var bar: shell.bar

    function enabledOf(id) { return shell.disabled.indexOf(id) < 0 }

    objectName: "footer"
    implicitHeight: Theme.controlHeight + 2 * Theme.space.m
    color: Theme.colors.chrome
    Behavior on color { ColorAnimation { duration: Theme.fade } }
    Rectangle { width: parent.width; height: 1; color: Theme.colors.border }

    RowLayout {
        anchors { fill: parent; leftMargin: Theme.space.xl; rightMargin: Theme.space.xl }
        spacing: Theme.space.s

        // the problems of the configuration: a click lists them
        ToolButton {
            id: problems
            objectName: "problems_button"
            readonly property int count: footer.shell.problems.length
            visible: opacity > 0
            opacity: count > 0 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.fade } }
            text: footer.shell.problemsText
            icon.source: "image://icon/alert-circle"
            icon.color: Theme.colors.error
            display: AbstractButton.TextBesideIcon
            contentItem: Row {
                spacing: Theme.space.xs
                ColorImage { source: problems.icon.source; color: Theme.colors.error; sourceSize: Qt.size(18, 18); anchors.verticalCenter: parent.verticalCenter }
                Label { text: problems.text; color: Theme.colors.error; anchors.verticalCenter: parent.verticalCenter }
            }
            property string tip: "The problems of the configuration: a click lists them."
            onClicked: problemsMenu.visible ? problemsMenu.close() : problemsMenu.open()

            Menu {
                id: problemsMenu
                // a press on the button leaves it to the button, which closes it (closed by the press, its click would
                // open it again)
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside | Popup.CloseOnPressOutsideParent
                objectName: "problems_menu"
                y: -height
                Instantiator {
                    model: footer.shell.problems
                    delegate: MenuItem {
                        required property string modelData
                        required property int index
                        objectName: "problem_" + index
                        text: modelData
                        onTriggered: footer.shell.pickProblem(index)
                    }
                    onObjectAdded: (index, object) => problemsMenu.insertItem(index, object)
                    onObjectRemoved: (index, object) => problemsMenu.removeItem(object)
                }
            }
        }

        // the sound server: what the forms suggest
        Pill {
            id: audio
            objectName: "audio_pill"
            clickable: true
            tone: footer.bar.audio ? footer.bar.audio.tone : "neutral"
            text: footer.bar.audio ? footer.bar.audio.text : ""
            property string tip: footer.bar.audio ? footer.bar.audio.tip : ""
            Accessible.name: footer.bar.audio && footer.bar.audio.name ? footer.bar.audio.name : text
            Layout.maximumWidth: Math.max(160, footer.width * 0.3)
            contentItem: Row {
                spacing: Theme.space.s
                FadeText {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, audio.Layout.maximumWidth - 2 * Theme.space.s - partsRow.width)
                    text: audio.text
                    color: audio.hue
                    bold: true
                    elide: Text.ElideRight
                }
                Row {
                    id: partsRow
                    spacing: Theme.space.s
                    Repeater {
                        model: footer.bar.audio && footer.bar.audio.parts ? footer.bar.audio.parts : []
                        Row {
                            required property var modelData
                            spacing: 2
                            ColorImage { source: "image://icon/" + modelData.icon; sourceSize: Qt.size(14, 14); color: audio.hue; anchors.verticalCenter: parent.verticalCenter }
                            Label { text: modelData.count; color: audio.hue; font.pointSize: Theme.fontSize.caption; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
            }
            onClicked: audioPopover.toggle()
            DetailsPopover { id: audioPopover; anchor: audio; details: footer.shell.audioPopover; objectName: "audio_details" }
        }

        // the status line, or the tip of what the mouse is over
        FadeText {
            id: statusLine
            objectName: "status"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: footer.shell.hoverTip !== "" ? footer.shell.hoverTip : footer.shell.statusText
            color: Theme.colors.text_muted
            font.pointSize: Theme.fontSize.caption
            elide: Text.ElideRight
        }

        Button {
            id: restart
            objectName: "restart_button"
            visible: opacity > 0
            opacity: footer.bar.restart ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.fade } }
            text: "Restart the service"
            icon.source: "image://icon/restart"
            property string tip: "Restart the service: the daemon takes the sections a reload does not take."
            onClicked: footer.shell.restart_service()
        }

        Pill {
            id: changes
            objectName: "changes_pill"
            clickable: true
            tone: footer.bar.changes ? footer.bar.changes.tone : "neutral"
            text: footer.bar.changes ? footer.bar.changes.text : ""
            property string tip: footer.bar.changes ? footer.bar.changes.tip : ""
            onClicked: changesPopover.toggle()
            DetailsPopover { id: changesPopover; anchor: changes; details: footer.shell.changesPopover; objectName: "changes_details" }
        }

        // where the changes show before they are saved: only while there is something to show
        Row {
            id: preview
            objectName: "preview"
            visible: opacity > 0
            opacity: footer.bar.previewShown ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.fade } }
            spacing: 0
            Layout.rightMargin: Theme.space.s
            Label {
                text: "Preview"
                color: Theme.colors.text_muted
                font.pointSize: Theme.fontSize.caption
                anchors.verticalCenter: parent.verticalCenter
                rightPadding: Theme.space.s
            }
            Repeater {
                model: footer.bar.places ? footer.bar.places : []
                delegate: Button {
                    required property var modelData
                    objectName: "place_" + modelData.id
                    text: modelData.text
                    checkable: true
                    checked: modelData.checked
                    enabled: modelData.enabled
                    // a key typed into the window must not press it: Enter in a field would send the changes to the device
                    focusPolicy: Qt.NoFocus
                    property string tip: modelData.tip
                    Accessible.name: "Preview: " + modelData.text
                    onClicked: footer.shell.setPlace(modelData.id)
                }
            }
        }

        IconButton {
            objectName: "undo_button"
            name: "undo"
            tip: "Undo (Ctrl+Z)"
            enabled: footer.enabledOf("undo")
            focusPolicy: Qt.NoFocus
            onClicked: footer.shell.undo()
        }
        IconButton {
            objectName: "redo_button"
            name: "redo"
            tip: "Redo (Ctrl+Shift+Z)"
            enabled: footer.enabledOf("redo")
            focusPolicy: Qt.NoFocus
            onClicked: footer.shell.redo()
        }
        Button {
            objectName: "revert_button"
            text: "Revert"
            icon.source: "image://icon/file-undo-outline"
            enabled: footer.enabledOf("revert")
            property string tip: "Drop the changes and read the file again (Undo brings them back)"
            onClicked: footer.shell.revert()
        }
        Button {
            objectName: "save_button"
            text: "Save and apply"
            icon.source: "image://icon/content-save"
            highlighted: true
            enabled: footer.enabledOf("save")
            property string tip: "Write the file and reload the daemon (Ctrl+S)"
            onClicked: footer.shell.save()
        }
    }
}
