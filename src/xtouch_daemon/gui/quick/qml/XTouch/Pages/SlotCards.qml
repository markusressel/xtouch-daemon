// The cards of the 8 slots in a column that scrolls with the wheel. A click below the cards picks nothing; picking a
// slot elsewhere (a click on its strip in the drawing) scrolls its card into view.
import QtQuick
import QtQuick.Controls
import XTouch

SlotScroll {
    id: cards
    required property QtObject slots
    objectName: "cards"
    contentHeight: Math.max(height, column.height + 2 * Theme.space.s)

    // below the cards
    MouseArea {
        objectName: "below_cards"
        width: cards.contentWidth
        height: cards.contentHeight
        onPressed: cards.slots.unpick()
    }

    Column {
        id: column
        x: Theme.space.s
        y: Theme.space.s
        width: cards.width - 2 * Theme.space.s - Theme.space.s
        spacing: Theme.space.s

        Repeater {
            id: repeater
            model: cards.slots.cards
            SlotCard {
                required property QtObject modelData
                width: column.width
                slots: cards.slots
                slotCard: modelData
            }
        }
    }

    Connections {
        target: cards.slots
        function onScrollRequested(slot) {
            cards.reveal(repeater.itemAt(slot - 1), Theme.space.s)
        }
        function onFocusRequested(slot) {
            repeater.itemAt(slot - 1).list.forceActiveFocus(Qt.MouseFocusReason)
        }
    }
}
