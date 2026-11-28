// The card of a slot: its name with the buttons to add and remove a candidate, and its candidates on a rail. A click
// beside the candidates picks the slot alone. A candidate is dragged by its row: the rows around it slide aside to
// make room (the list says by how much, `offsets`), and the row settles where it is dropped, then the model moves.
// Up and Down pick the row above and under, Ctrl+Up and Ctrl+Down move the candidate picked.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Rectangle {
    id: card
    required property QtObject slots
    required property QtObject slotCard
    readonly property int number: slotCard.number
    readonly property int candidates: slotCard.candidates
    readonly property alias list: list
    readonly property real padding: Theme.space.s
    objectName: "card_" + number

    implicitHeight: header.height + list.height + 2 * padding + Theme.space.xs
    height: implicitHeight
    Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
    radius: Theme.radius.large
    color: Theme.colors.raised
    border.width: slotCard.picked || slotCard.problem !== "" ? 2 : 1
    border.color: slotCard.problem !== "" ? Theme.colors.error : slotCard.picked ? Theme.colors.accent : Theme.colors.border
    Behavior on color { ColorAnimation { duration: Theme.fade } }
    Behavior on border.color { ColorAnimation { duration: Theme.fade } }

    HoverHandler { id: hover }
    // the line of a card under the mouse: at once, as the mouse moves (a pick or a problem fades in)
    Rectangle {
        objectName: "hoverLine"
        anchors.fill: parent
        z: 1
        radius: card.radius
        color: "transparent"
        border.width: 1
        border.color: Theme.colors.control_border
        visible: hover.hovered && !slotCard.picked && slotCard.problem === ""
    }
    // a click on the card beside its candidates picks the slot alone
    MouseArea {
        anchors.fill: parent
        z: -1
        onPressed: card.slots.pickSlot(card.number)
    }
    SlotTip { text: card.slotCard.problem; z: -2 }

    Item {
        id: header
        x: card.padding
        y: card.padding
        width: card.width - 2 * card.padding
        height: Theme.controlHeight
        Text {
            anchors.verticalCenter: parent.verticalCenter
            x: Theme.space.xs
            text: "Slot " + card.number
            color: Theme.colors.slot
            font.bold: true
            font.pointSize: Theme.fontSize.body
        }
        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            IconButton {
                objectName: "add_" + card.number
                name: "plus"
                tip: "Add a candidate (at the end; Ctrl+Up moves it up)"
                onClicked: card.slots.add(card.number)
            }
            IconButton {
                objectName: "remove_" + card.number
                name: "delete-outline"
                tip: "Remove the candidate picked (Del)"
                onClicked: card.slots.remove(card.number)
            }
        }
    }

    ListView {
        id: list
        objectName: "list_" + card.number
        x: card.padding
        y: header.y + header.height
        width: card.width - 2 * card.padding
        height: contentHeight
        interactive: false
        activeFocusOnTab: true
        model: card.slotCard.rows
        Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }

        // what is dragged: the row, how far it was moved, where it would land and how far each row moves aside
        property int dragFrom: -1
        property int dragTo: -1
        property real dragDy: 0
        property var offsets: []
        property bool settling: false
        // rows move without sliding (when the model has moved what they showed already)
        property bool instant: false

        onActiveFocusChanged: card.slots.cardFocus(card.number, activeFocus)

        function candidateItems() {
            const found = []
            for (let i = 0; i < card.candidates; i++) {
                const item = itemAtIndex(i)
                if (!item)
                    return []
                found.push(item)
            }
            return found
        }

        // by how much each candidate moves aside when the one at `from` goes to `to`
        function layout(items, from, to) {
            const order = items.map((_, i) => i)
            order.splice(to, 0, order.splice(from, 1)[0])
            const result = items.map(() => 0)
            let top = items.length ? items[0].y : 0
            for (const i of order) {
                result[i] = top - items[i].y
                top += items[i].height
            }
            return result
        }

        function dragStart(index) {
            settling = false
            dragFrom = index
            dragTo = index
            dragDy = 0
            offsets = []
            card.slots.pickRow(card.number, index)
        }

        function dragMove(dy) {
            const items = candidateItems()
            if (dragFrom < 0 || !items.length)
                return
            const item = items[dragFrom]
            const first = items[0].y
            const last = items[items.length - 1].y + items[items.length - 1].height
            dragDy = Math.max(first - item.y, Math.min(last - item.y - item.height, dy))
            const center = item.y + item.height / 2 + dragDy
            let target = dragFrom
            for (let i = 0; i < items.length; i++)
                if (center >= items[i].y && center < items[i].y + items[i].height)
                    target = i
            if (target !== dragTo) {
                dragTo = target
                offsets = layout(items, dragFrom, target)
            }
        }

        function dragEnd() {
            if (dragFrom < 0)
                return
            if (dragTo === dragFrom) {
                // back where it was
                settling = true
                offsets = []
            } else {
                settling = true
            }
            if (Theme.resize === 0)
                commit()
            else
                settle.restart()
        }

        function commit() {
            if (dragFrom < 0)
                return
            const from = dragFrom
            const to = dragTo
            instant = true
            dragFrom = -1
            dragTo = -1
            dragDy = 0
            offsets = []
            settling = false
            if (from !== to)
                card.slots.reorder(card.number, from, to)
            Qt.callLater(() => instant = false)
        }

        Timer {
            id: settle
            interval: Theme.resize + 30
            onTriggered: list.commit()
        }

        Keys.onPressed: event => {
            const up = event.key === Qt.Key_Up
            const down = event.key === Qt.Key_Down
            if (!up && !down)
                return
            event.accepted = true
            if (event.modifiers & Qt.ControlModifier) {
                card.slots.moveCandidate(card.number, up ? -1 : 1)
            } else if (card.slotCard.current >= 0) {
                const row = card.slotCard.current + (up ? -1 : 1)
                if (row >= 0 && row < count)
                    card.slots.pickRow(card.number, row)
            }
        }

        delegate: SlotRow {
            width: ListView.view.width
            height: implicitHeight
            owner: card
            stack: list
            slots: card.slots
            current: card.slotCard.current === index
            Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
        }

        add: Transition {
            enabled: !list.instant
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.resize; easing.type: Easing.OutCubic }
            NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.resize; easing.type: Easing.OutCubic }
        }
        remove: Transition {
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.fade }
        }
        displaced: Transition {
            NumberAnimation { properties: "y"; duration: Theme.resize; easing.type: Easing.OutCubic }
        }
        move: Transition {
            enabled: !list.instant
            NumberAnimation { properties: "y"; duration: Theme.resize; easing.type: Easing.OutCubic }
        }
        moveDisplaced: Transition {
            enabled: !list.instant
            NumberAnimation { properties: "y"; duration: Theme.resize; easing.type: Easing.OutCubic }
        }
    }
}
