// The list of suggestions under a text field, inside the window: the field keeps the focus; Up and Down (and PageUp and
// PageDown) move in the list, Enter and Tab pick the line (with none, they go on to the field), Esc closes it, and a
// click on a line picks it. `provider(text)` gives `{ rows: [{ value, html, tip, forget, ... }], empty }`: the lines for
// what is typed, and what to say without any. The field passes its key presses to `handleKey`.
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Controls
import XTouch
import XTouch.Controls

Popup {
    id: list

    required property Item field
    property var provider: text => ({ rows: [], empty: "" })
    property int maxRows: 8
    property real listWidth: 360
    // lines of entities: the line of the value is current at first, the first line while typing, and Up and Down open it
    property bool entities: false
    property bool typed: false
    property var result: ({ rows: [], empty: "" })
    readonly property alias view: view
    readonly property int count: result.rows.length
    signal picked(string value)
    signal forgotten(string value)

    parent: field
    popupType: Popup.Item
    focus: false
    closePolicy: Popup.CloseOnPressOutsideParent
    padding: Theme.space.xs
    width: Math.max(listWidth, field.width)
    readonly property real below: Overlay.overlay ? field.mapToItem(Overlay.overlay, 0, field.height).y : 0
    readonly property bool downward: !Overlay.overlay || below + height <= Overlay.overlay.height - Theme.space.s
    x: 0
    y: downward ? field.height + 2 : -height - 2
    height: Math.min(view.contentHeight, maxRows * (Theme.controlHeight + Theme.space.s)) + topPadding + bottomPadding

    function refresh(text) {
        result = provider(text)
        const rows = result.rows
        let current = -1
        if (entities && rows.length > 0) {
            current = rows.findIndex(row => row.value === text)
            if (current < 0 && typed && text !== "") current = 0
        }
        view.currentIndex = current
        if (!opened && field.activeFocus) open()
    }

    function move(step) {
        const rows = result.rows
        if (rows.length === 0) return
        const from = view.currentIndex < 0 ? (step > 0 ? -1 : rows.length) : view.currentIndex
        const next = Math.max(0, Math.min(rows.length - 1, from + step))
        view.currentIndex = next
        view.positionViewAtIndex(next, ListView.Contain)
    }

    function pick(index) {
        if (index < 0 || index >= result.rows.length) return false
        const value = result.rows[index].value
        close()
        picked(value)
        return true
    }

    // Whether the key was taken: the field does not see it then.
    function handleKey(event) {
        const key = event.key
        if (!opened) {
            if (entities && (key === Qt.Key_Up || key === Qt.Key_Down)) {
                typed = false
                refresh(field.text)
                return true
            }
            return false
        }
        switch (key) {
        case Qt.Key_Down: move(1); return true
        case Qt.Key_Up: move(-1); return true
        case Qt.Key_PageDown: move(maxRows - 1); return true
        case Qt.Key_PageUp: move(-(maxRows - 1)); return true
        case Qt.Key_Escape: close(); return true
        case Qt.Key_Delete:
            if (view.currentIndex >= 0 && result.rows[view.currentIndex].forget) {
                forgotten(result.rows[view.currentIndex].value)
                return true
            }
            return false
        case Qt.Key_Return:
        case Qt.Key_Enter:
        case Qt.Key_Tab:
            if (view.currentIndex >= 0 && pick(view.currentIndex)) return true
            close()
            return false
        }
        return false
    }

    Connections {
        target: list.field
        function onActiveFocusChanged() { if (!list.field.activeFocus) list.close() }
    }

    contentItem: ListView {
        id: view
        objectName: "suggestions"
        clip: true
        implicitHeight: contentHeight
        model: list.result.rows.length > 0 ? list.result.rows : [{ value: "", html: "", empty: true }]
        highlightMoveDuration: 0
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        delegate: ItemDelegate {
            id: line
            required property var modelData
            required property int index
            objectName: "suggestion_" + (modelData.empty ? "none" : modelData.value)
            width: ListView.view.width
            enabled: !modelData.empty
            focusPolicy: Qt.NoFocus
            hoverEnabled: true
            highlighted: ListView.isCurrentItem
            padding: Theme.space.xs
            contentItem: Row {
                spacing: Theme.space.s
                ColorImage {
                    visible: !!line.modelData.icon
                    width: visible ? 16 : 0
                    height: 16
                    source: line.modelData.icon ? "image://icon/" + line.modelData.icon : ""
                    color: Theme.colors.text_muted
                }
                Text {
                    width: line.width - 2 * line.padding - (line.modelData.icon ? 16 + Theme.space.s : 0)
                    textFormat: Text.RichText
                    wrapMode: Text.Wrap
                    text: line.modelData.empty ? list.result.empty : line.modelData.html
                    color: line.modelData.empty ? Theme.colors.text_muted : Theme.colors.text
                    font: line.font
                }
            }
            onHoveredChanged: if (hovered && enabled) ListView.view.currentIndex = index
            onClicked: list.pick(index)
            ToolTip.visible: hovered && !modelData.empty && (modelData.tip ?? "") !== ""
            ToolTip.text: modelData.tip ?? ""
        }
    }
}
