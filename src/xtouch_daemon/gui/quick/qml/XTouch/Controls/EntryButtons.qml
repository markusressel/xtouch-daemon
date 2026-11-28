// The buttons under a list of entries: Add (which opens a menu the page shows), Duplicate and Remove (in the error
// color). A page that cannot duplicate or remove the entry picked disables them.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import XTouch

Row {
    id: buttons
    property bool canDuplicate: true
    property bool canRemove: true
    property string duplicateTip: "Add a copy, with an id after its own (Ctrl+D)"
    property string removeTip: "Remove the entry (Del)"
    readonly property alias addButton: add
    signal addClicked()
    signal duplicateClicked()
    signal removeClicked()

    spacing: Theme.space.s

    Button {
        id: add
        objectName: "entry_add"
        text: "Add"
        icon.source: "image://icon/plus"
        onClicked: buttons.addClicked()
    }
    Button {
        objectName: "entry_duplicate"
        text: "Duplicate"
        icon.source: "image://icon/content-copy"
        enabled: buttons.canDuplicate
        onClicked: buttons.duplicateClicked()
        ToolTip.visible: hovered
        ToolTip.text: buttons.duplicateTip
    }
    Button {
        id: remove
        objectName: "entry_remove"
        text: "Remove"
        icon.source: "image://icon/delete-outline"
        enabled: buttons.canRemove
        onClicked: buttons.removeClicked()
        ToolTip.visible: hovered
        ToolTip.text: buttons.removeTip
        readonly property color danger: enabled ? Theme.colors.error : Theme.colors.text_muted
        contentItem: IconLabel {
            spacing: remove.spacing
            display: remove.display
            icon: remove.icon
            text: remove.text
            font: remove.font
            color: remove.danger
            defaultIconColor: remove.danger
        }
    }
}
