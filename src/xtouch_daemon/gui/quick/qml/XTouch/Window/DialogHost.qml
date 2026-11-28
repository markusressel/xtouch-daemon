// The question or the note of the window (`Dialogs` of window/dialogs.py): a card over the dimmed window with a text and
// buttons. Esc is the button that rejects; the one that accepts has the focus and shows in the accent.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch

Popup {
    id: dialog
    required property QtObject dialogs
    objectName: "dialog"

    parent: Overlay.overlay
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape
    anchors.centerIn: parent
    padding: Theme.space.l
    width: Math.min(460, parent ? parent.width - 2 * Theme.space.l : 460)

    visible: dialogs.isOpen
    onVisibleChanged: if (!visible && dialogs.isOpen) dialogs.reject()

    ColumnLayout {
        width: dialog.availableWidth
        spacing: Theme.space.m
        Label {
            objectName: "dialog_title"
            text: dialog.dialogs.title
            font.bold: true
            font.pointSize: Theme.fontSize.section
            Layout.fillWidth: true
        }
        Label {
            objectName: "dialog_text"
            text: dialog.dialogs.text
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
        RowLayout {
            spacing: Theme.space.s
            Item { Layout.fillWidth: true }
            Repeater {
                model: dialog.dialogs.buttons
                Button {
                    required property var modelData
                    objectName: "dialog_" + modelData.id
                    text: modelData.text
                    highlighted: modelData.role === "accept"
                    Component.onCompleted: if (highlighted) forceActiveFocus()
                    onClicked: dialog.dialogs.answer(modelData.id)
                }
            }
        }
    }
}
