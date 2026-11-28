// The slot cards of the page Slots in Qt Quick: a prototype (see cards.py). Everything that changes moves: the
// node and the dimming of a row animate to their new values, a text that changes fades through, a reason grows in
// under its row, rows that come or go fade and grow while the rows below slide along, and a card grows with them.
import QtQuick
import QtQuick.Controls

Item {
    id: root

    readonly property int fade: theme.fade
    readonly property int resize: theme.resize

    function tinted(color, alpha) {
        const c = Qt.color(color)
        return Qt.rgba(c.r, c.g, c.b, alpha)
    }

    // A text that fades through when it changes: the old one out, then the new one in.
    component FadeText: Item {
        id: fadeText
        property string text
        property color color: theme.text
        property bool bold: false
        implicitWidth: shown.implicitWidth
        implicitHeight: shown.implicitHeight
        Behavior on implicitWidth { NumberAnimation { duration: root.resize; easing.type: Easing.OutCubic } }

        Text {
            id: old
            color: fadeText.color
            font.bold: fadeText.bold
            opacity: 0
        }
        Text {
            id: shown
            text: fadeText.text
            color: fadeText.color
            font.bold: fadeText.bold
        }
        property string previous: text
        onTextChanged: {
            if (root.fade > 0 && previous !== "" && previous !== text) {
                old.text = previous
                through.restart()
            }
            previous = text
        }
        SequentialAnimation {
            id: through
            ParallelAnimation {
                NumberAnimation { target: old; property: "opacity"; from: 1; to: 0; duration: root.fade * 0.5 }
                NumberAnimation { target: shown; property: "opacity"; from: 0; to: 0; duration: root.fade * 0.5 }
            }
            NumberAnimation { target: shown; property: "opacity"; from: 0; to: 1; duration: root.fade }
        }
    }

    // A part of a condition (outlined) or what a candidate shows (filled), in the color of its kind.
    component Chip: Rectangle {
        id: chip
        property string text
        property color hue: theme.channel
        property bool filled: false
        property var swatches: []
        radius: theme.pill
        color: filled ? root.tinted(hue, theme.tint) : "transparent"
        border.color: hue
        border.width: 1
        implicitHeight: label.implicitHeight + 4
        implicitWidth: content.implicitWidth + 2 * theme.s
        Behavior on color { ColorAnimation { duration: root.fade } }
        Behavior on border.color { ColorAnimation { duration: root.fade } }

        Row {
            id: content
            anchors.centerIn: parent
            spacing: theme.xs
            Repeater {
                model: chip.swatches
                Rectangle {
                    width: 10; height: 10; radius: 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: modelData
                    border.color: theme.control_border
                }
            }
            FadeText {
                id: label
                text: chip.text
                color: chip.filled ? theme.text : chip.hue
            }
        }
    }

    // A row of a card: a candidate on the rail, or the dark strip at its end.
    component CandidateRow: Item {
        id: candidateRow
        required property var row
        property bool current: false
        readonly property real dim: row.state === "passed" ? 0.55 : row.state === "unreached" ? 0.4 : 1.0
        readonly property real band: row.first ? 0 : elseText.implicitHeight + 2 * theme.xs
        readonly property real nodeY: band + (row.first ? theme.xs : 0) + rule.height / 2

        implicitHeight: band + (row.first ? theme.xs : 0) + rule.height + reasonBox.height + (row.last ? theme.xs : 0)

        Rectangle {
            // picked
            anchors.fill: parent
            anchors.rightMargin: theme.xs
            radius: theme.pill / 2
            color: theme.accent_tint
            opacity: candidateRow.current ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: root.fade } }
        }

        // the rail, through the node
        Rectangle {
            x: 12 - 1
            width: 2
            y: candidateRow.row.first ? candidateRow.nodeY : 0
            height: (candidateRow.row.last ? candidateRow.nodeY : candidateRow.height) - y
            color: theme.control_border
        }
        Rectangle {
            id: node
            readonly property bool on: candidateRow.row.state === "shown"
            x: 12 - theme.node
            y: candidateRow.nodeY - theme.node
            width: 2 * theme.node; height: width; radius: theme.node
            color: on ? theme.tone_good : theme.raised
            border.width: 2
            border.color: on ? theme.tone_good : candidateRow.row.state === "passed" ? theme.text_muted : theme.control_border
            scale: on ? 1.2 : 1.0
            Behavior on color { ColorAnimation { duration: root.resize } }
            Behavior on border.color { ColorAnimation { duration: root.resize } }
            Behavior on scale { NumberAnimation { duration: root.resize; easing.type: Easing.OutBack } }
        }

        Text {
            id: elseText
            visible: !candidateRow.row.first
            x: 24
            y: theme.xs
            text: "else"
            color: theme.text_muted
        }

        Row {
            id: rule
            x: 24
            y: candidateRow.band + (candidateRow.row.first ? theme.xs : 0)
            spacing: theme.s
            opacity: candidateRow.dim
            Behavior on opacity { NumberAnimation { duration: root.resize } }

            Text {
                width: theme.m
                anchors.verticalCenter: parent.verticalCenter
                text: candidateRow.row.number
                color: theme.text_muted
            }
            FadeText {
                anchors.verticalCenter: parent.verticalCenter
                visible: text !== ""
                text: candidateRow.row.lead
                color: theme.text_muted
            }
            Repeater {
                model: candidateRow.row.chips
                Row {
                    spacing: theme.s
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        visible: modelData.or === true
                        anchors.verticalCenter: parent.verticalCenter
                        text: "or"
                        color: theme.text_muted
                    }
                    Chip {
                        text: modelData.text
                        hue: modelData.kind === "presence" ? theme.presence : theme.state
                        ToolTip.visible: chipMouse.containsMouse
                        ToolTip.text: "In the file: " + modelData.tip
                        MouseArea { id: chipMouse; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                    }
                }
            }
            Text {
                visible: !candidateRow.row.end
                anchors.verticalCenter: parent.verticalCenter
                text: "→"
                color: theme.text_muted
            }
            FadeText {
                visible: candidateRow.row.nothing
                anchors.verticalCenter: parent.verticalCenter
                text: candidateRow.row.show
                color: theme.text_muted
            }
            Repeater {
                model: candidateRow.row.nothing ? candidateRow.row.swatches : []
                Rectangle {
                    width: 10; height: 10; radius: 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: modelData
                    border.color: theme.control_border
                }
            }
            Chip {
                visible: !candidateRow.row.nothing
                anchors.verticalCenter: parent.verticalCenter
                text: candidateRow.row.show
                hue: theme.channel
                filled: true
                swatches: candidateRow.row.swatches
            }
            Text {
                visible: candidateRow.row.options !== ""
                anchors.verticalCenter: parent.verticalCenter
                text: candidateRow.row.options
                color: theme.text_muted
            }
        }

        // why it did not win: grows in under the rule, and shrinks away
        Item {
            id: reasonBox
            x: 24 + theme.m + theme.s
            y: rule.y + rule.height
            width: reason.implicitWidth
            clip: true
            property string last: ""
            readonly property bool open: candidateRow.row.reason !== ""
            height: open ? reason.implicitHeight : 0
            Behavior on height { NumberAnimation { duration: root.resize; easing.type: Easing.OutCubic } }
            Text {
                id: reason
                // keeps the old text while it shrinks away
                text: "✗ " + (candidateRow.row.reason !== "" ? candidateRow.row.reason : reasonBox.last)
                color: theme.text_muted
                opacity: reasonBox.open ? candidateRow.dim : 0
                Behavior on opacity { NumberAnimation { duration: root.resize } }
                onTextChanged: if (candidateRow.row.reason !== "") reasonBox.last = candidateRow.row.reason
            }
        }
    }

    ScrollView {
        id: scroll
        anchors.fill: parent
        contentWidth: availableWidth

        Column {
            width: scroll.availableWidth
            spacing: theme.s

            Repeater {
                model: cards.cards

                Rectangle {
                    id: card
                    required property var modelData
                    readonly property var slotCard: modelData
                    width: parent.width
                    clip: true
                    radius: theme.radius
                    color: theme.raised
                    border.width: slotCard.picked ? 2 : 1
                    border.color: slotCard.problem !== "" ? theme.error : slotCard.picked ? theme.accent : theme.border
                    Behavior on border.color { ColorAnimation { duration: root.fade } }
                    implicitHeight: header.height + list.height + 2 * theme.s + theme.xs
                    height: implicitHeight

                    MouseArea {
                        anchors.fill: parent
                        onClicked: cards.pickSlot(card.slotCard.number)
                    }

                    Text {
                        id: header
                        x: theme.m
                        y: theme.s
                        text: "Slot " + card.slotCard.number
                        color: theme.slot
                        font.bold: true
                    }

                    ListView {
                        id: list
                        x: theme.m
                        y: header.y + header.height + theme.xs
                        width: card.width - 2 * theme.m
                        interactive: false
                        model: card.slotCard.rows
                        height: contentHeight
                        Behavior on height { NumberAnimation { duration: root.resize; easing.type: Easing.OutCubic } }

                        delegate: CandidateRow {
                            id: delegateRow
                            required property int index
                            width: ListView.view.width
                            height: implicitHeight
                            Behavior on height { NumberAnimation { duration: root.resize; easing.type: Easing.OutCubic } }
                            current: card.slotCard.current === index
                            MouseArea {
                                anchors.fill: parent
                                onClicked: cards.pick(card.slotCard.number, delegateRow.index)
                            }
                        }

                        add: Transition {
                            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: root.resize; easing.type: Easing.OutCubic }
                            NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: root.resize; easing.type: Easing.OutCubic }
                        }
                        remove: Transition {
                            NumberAnimation { property: "opacity"; to: 0; duration: root.fade }
                        }
                        displaced: Transition {
                            NumberAnimation { properties: "y"; duration: root.resize; easing.type: Easing.OutCubic }
                        }
                    }
                }
            }
        }
    }
}
