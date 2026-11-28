// One table of a list (see `TablesField`): what it is in a line, and what it needs and its range below; open, its options
// (a row per column). The card and the profile of a device fold away behind a button until one of them is set.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Rectangle {
    id: card
    required property var field
    required property int position
    required property var entry
    readonly property QtObject form: field.form
    readonly property var columns: field.spec.columns
    readonly property bool open: field.opened === position
    readonly property var summary: form.entrySummary(field.spec.name, entry)
    readonly property bool folds: field.spec.folds === true
    property bool unfolded: false
    readonly property bool wantsUnfolded: unfolded || (entry.card ?? "") !== "" || (entry.profile ?? "") !== ""
    readonly property real titleWidth: 96

    objectName: "entry_" + field.spec.name + "_" + position
    implicitHeight: body.implicitHeight + 2 * Theme.space.s
    height: implicitHeight
    radius: Theme.radius.medium
    color: Theme.colors.sunken
    border.width: card.activeFocus || open ? 2 : 1
    border.color: card.activeFocus || open ? Theme.colors.accent : Theme.colors.border
    Behavior on border.color { ColorAnimation { duration: Theme.fade } }
    Behavior on implicitHeight { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
    activeFocusOnTab: true
    clip: true

    function toggle() { field.opened = open ? -1 : position }
    function setOpen(shown) { field.opened = shown ? position : (open ? -1 : field.opened) }

    Keys.onPressed: event => {
        if (event.modifiers & Qt.ControlModifier && event.key === Qt.Key_Up) { field.move(position, -1); event.accepted = true }
        else if (event.modifiers & Qt.ControlModifier && event.key === Qt.Key_Down) { field.move(position, 1); event.accepted = true }
        else if (event.key === Qt.Key_Escape && open) { setOpen(false); card.forceActiveFocus(); event.accepted = true }
    }
    TapHandler { onTapped: card.forceActiveFocus(); onDoubleTapped: card.toggle(); gesturePolicy: TapHandler.ReleaseWithinBounds }

    // where a dragged entry would land
    Rectangle {
        visible: field.dropAt === position
        width: parent.width
        height: 3
        y: -Theme.space.xs / 2 - 2
        color: Theme.colors.accent
    }

    Column {
        id: body
        x: Theme.space.s
        y: Theme.space.s
        width: parent.width - 2 * Theme.space.s
        spacing: Theme.space.s

        Row {
            id: head
            width: parent.width
            spacing: Theme.space.s

            Label {
                id: handle
                objectName: "handle_" + card.position
                text: "⠿"
                color: Theme.colors.text_muted
                width: 16
                HoverHandler { id: handleHover; cursorShape: Qt.OpenHandCursor }
                ToolTip.visible: handleHover.hovered
                ToolTip.text: "Drag to move it (or Ctrl+Up/Down): the order is the order they are picked in"
                DragHandler {
                    id: drag
                    target: null
                    yAxis.enabled: true
                    xAxis.enabled: false
                    onActiveChanged: {
                        if (active) return
                        const before = card.field.dropAt
                        card.field.dropAt = -1
                        if (before >= 0 && before !== card.position && before !== card.position + 1) card.field.drop(card.position, before)
                    }
                    onTranslationChanged: {
                        if (!active) return
                        // the first entry whose middle is below the grip
                        const list = card.field.row
                        const y = card.y + handle.y + translation.y + handle.height / 2
                        let at = card.ListView.view.count
                        for (let i = 0; i < card.ListView.view.count; i++) {
                            const other = card.ListView.view.itemAtIndex(i)
                            if (other && other.y + other.height / 2 > y) { at = i; break }
                        }
                        card.field.dropAt = at
                    }
                }
            }

            Column {
                width: parent.width - handle.width - actions.width - 2 * parent.spacing
                Label {
                    width: parent.width
                    text: card.summary.title
                    font.bold: true
                    wrapMode: Text.Wrap
                    color: Theme.colors.text
                }
                Repeater {
                    model: card.summary.lines
                    Label {
                        required property string modelData
                        width: parent.width
                        text: modelData
                        wrapMode: Text.Wrap
                        font.pointSize: Theme.fontSize.caption
                        color: Theme.colors.text_muted
                    }
                }
            }

            Row {
                id: actions
                IconButton {
                    objectName: "edit_" + card.position
                    name: "pencil"
                    tip: "Edit it (or a double click)"
                    checkable: true
                    checked: card.open
                    onClicked: card.setOpen(!card.open)
                }
                IconButton {
                    objectName: "remove_" + card.position
                    name: "delete-outline"
                    tip: "Remove it"
                    onClicked: card.field.remove(card.position)
                }
            }
        }

        Reveal {
            width: parent.width
            shown: card.open
            Column {
                width: parent.width
                Repeater {
                    model: card.open ? card.columns : []
                    Column {
                        id: cell
                        required property var modelData
                        readonly property bool folded: card.folds && (modelData.name === "card" || modelData.name === "profile")
                        width: parent.width
                        Button {
                            visible: cell.folded && cell.modelData.name === "card"
                            height: visible ? implicitHeight : 0
                            flat: true
                            icon.source: "image://icon/" + (card.wantsUnfolded ? "chevron-down" : "chevron-right")
                            text: "Switch the sound card first"
                            ToolTip.visible: hovered
                            ToolTip.text: "A digital output (e.g. HDMI) of a card that plays analog now is a profile of its card: the daemon switches the card to it first."
                            onClicked: card.unfolded = !card.unfolded
                        }
                        Reveal {
                            width: parent.width
                            shown: !cell.folded || card.wantsUnfolded
                            OptionRow {
                                x: cell.folded ? Theme.space.l : 0
                                width: parent.width - x
                                form: card.form
                                nested: true
                                spec: cell.modelData
                                titleWidth: card.titleWidth - (cell.folded ? Theme.space.l : 0)
                                suggestKey: card.suggests(cell.modelData.name)
                                suggestLine: card.entry
                                info: card.infoOf(cell.modelData)
                                onValueEdited: value => card.field.put(card.position, cell.modelData.name, value)
                                onPicked: (value, extra) => card.picked(cell.modelData.name, extra)
                            }
                        }
                    }
                }
            }
        }
    }

    function suggests(name) {
        return field.spec.suggestColumns.indexOf(name) >= 0 ? field.spec.name + "." + name : ""
    }

    function infoOf(column) {
        const value = entry[column.name]
        return {
            value: value === undefined ? null : value,
            placeholder: (field.spec.columnPlaceholders[column.name] ?? ""),
            problems: "",
            resettable: false,
        }
    }

    // a device that is there only in another profile of its card brings the card and the profile
    function picked(name, extra) {
        if (name !== "device" || !extra || !extra.card) return
        let next = form.tools.tablePut(field.entries, position, "card", extra.card)
        if (extra.profile) next = form.tools.tablePut(next, position, "profile", extra.profile)
        field.commit(next)
        unfolded = true
    }
}
