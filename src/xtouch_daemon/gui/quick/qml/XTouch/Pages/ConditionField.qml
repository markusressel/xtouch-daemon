// A field for a condition (`gaming and not present`): its words in the colors of what they are, mistakes underlined,
// and the words it can take offered under it while typing (Ctrl+Space offers them at any time). Enter or leaving the
// field commits (`committed`). It is a `TextEdit` with a highlighter of its document (see `slots_condition.py`).
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Slots

FocusScope {
    id: field
    property string text
    property string placeholder: "always"
    property bool present: true
    property var states: []
    property var targets: []
    readonly property alias problem: helper.problem
    readonly property alias editor: edit
    signal committed(string text)

    implicitHeight: Theme.controlHeight
    implicitWidth: 200
    activeFocusOnTab: true

    function commit() {
        if (edit.text !== field.text)
            field.committed(edit.text)
    }

    onTextChanged: if (!edit.activeFocus && edit.text !== text) edit.text = text
    Component.onCompleted: edit.text = text

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius.medium
        color: Theme.colors.sunken
        border.width: edit.activeFocus || helper.problem !== "" ? 2 : 1
        border.color: helper.problem !== "" ? Theme.colors.error
            : edit.activeFocus ? Theme.colors.accent
            : hover.hovered ? Theme.colors.text_muted : Theme.colors.control_border
        Behavior on border.color { ColorAnimation { duration: Theme.fade } }
    }
    HoverHandler { id: hover }

    TextEdit {
        id: edit
        objectName: "condition_edit"
        x: Theme.space.s
        width: parent.width - 2 * Theme.space.s
        anchors.verticalCenter: parent.verticalCenter
        wrapMode: TextEdit.NoWrap
        color: Theme.colors.text
        selectionColor: Theme.colors.accent
        selectedTextColor: Theme.colors.on_accent
        selectByMouse: true
        clip: true
        font.pointSize: Theme.fontSize.body
        textFormat: TextEdit.PlainText

        Text {
            visible: edit.text === "" && !edit.preeditText
            text: field.placeholder
            color: Theme.colors.placeholder
            font: edit.font
        }

        focus: true
        onActiveFocusChanged: if (!activeFocus) { suggestions.close(); field.commit() }
        onTextChanged: Qt.callLater(() => { if (activeFocus) offer(false) })  // the cursor moves after the text
        // Enter and Tab pick the word offered while the list shows; Escape closes it
        Keys.onPressed: event => {
            const open = suggestions.opened
            if (event.key === Qt.Key_Space && (event.modifiers & Qt.ControlModifier)) {
                offer(true)
                event.accepted = true
            } else if (open && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Tab)) {
                complete(offered.get(list.currentIndex).text)
                event.accepted = true
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                field.commit()
                event.accepted = true
            } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
                field.commit()
                const next = event.key === Qt.Key_Tab ? field.nextItemInFocusChain(true) : field.nextItemInFocusChain(false)
                if (next)
                    next.forceActiveFocus(Qt.TabFocusReason)
                event.accepted = true
            } else if (event.key === Qt.Key_Escape && open) {
                suggestions.close()
                event.accepted = true
            } else if (open && event.key === Qt.Key_Down) {
                list.currentIndex = Math.min(offered.count - 1, list.currentIndex + 1)
                event.accepted = true
            } else if (open && event.key === Qt.Key_Up) {
                list.currentIndex = Math.max(0, list.currentIndex - 1)
                event.accepted = true
            }
        }

        function offer(always) {
            const words = helper.offer(edit.text, edit.cursorPosition, always)
            offered.clear()
            for (const word of words)
                offered.append({ text: word })
            if (words.length > 0) {
                list.currentIndex = 0
                suggestions.open()
            } else {
                suggestions.close()
            }
        }

        // puts `word` in place of the one being typed: selected and typed over, so Ctrl+Z takes it back
        function complete(word) {
            const typed = helper.partialLength(edit.text, edit.cursorPosition)
            const at = edit.cursorPosition
            edit.select(at - typed, at)
            edit.remove(at - typed, at)
            edit.insert(at - typed, word)
            suggestions.close()
        }
    }

    ConditionHelper {
        id: helper
        document: edit.textDocument
        present: field.present
        states: field.states
        targets: field.targets
        colors: Theme.colors
    }

    ListModel { id: offered }

    Popup {
        id: suggestions
        objectName: "suggestions"
        popupType: Popup.Item
        parent: field
        y: field.height + 2
        x: Math.min(edit.cursorRectangle.x, field.width - width)
        width: Math.max(field.width / 2, 200)
        height: Math.min(list.contentHeight, 200) + 2 * padding
        padding: Theme.space.xs
        focus: false
        closePolicy: Popup.NoAutoClose
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.fade } }
        exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.fade } }
        background: Rectangle {
            color: Theme.colors.raised
            border.color: Theme.colors.border
            radius: Theme.radius.large
        }
        contentItem: ListView {
            id: list
            clip: true
            model: offered
            delegate: ItemDelegate {
                id: word
                required property var model
                required property int index
                width: ListView.view.width
                text: model.text
                highlighted: ListView.isCurrentItem
                onClicked: edit.complete(word.model.text)
            }
        }
    }

    ToolTip.visible: hover.hovered && !suggestions.opened
    ToolTip.delay: 500
    ToolTip.text: helper.problem !== "" ? helper.problem : "States and modes with `and`, `or`, `not`, parentheses and `present`"
}
