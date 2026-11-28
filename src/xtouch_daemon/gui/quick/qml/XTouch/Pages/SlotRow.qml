// A row of a card: a candidate on the rail (its condition as chips, what it shows, the options of its place), or the
// dark strip at the end of the rail. Everything that changes moves: the node and the dimming animate to their new
// values, a text fades through, a reason grows in under its row. A candidate can be dragged by the card (`body` moves,
// the rows around it slide aside, see `SlotCard.qml`).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls
import XTouch.Slots

Item {
    id: root
    required property var row
    required property string key
    required property int index
    // the card it is in: its list says what is dragged
    required property Item owner
    required property var stack
    required property QtObject slots
    property bool current: false
    property int tipsOver: 0
    readonly property alias body: body
    readonly property bool dragging: root.stack.dragFrom === index

    readonly property real dim: row.state === "passed" ? 0.55 : row.state === "unreached" ? 0.4 : 1.0
    readonly property real rail: 24
    readonly property real band: row.first ? 0 : elseText.implicitHeight + 2 * Theme.space.xs
    readonly property real nodeY: band + (row.first ? Theme.space.xs : 0) + rule.height / 2
    // lists of the row that stay the same objects while their content does
    property var chips: []
    property string chipsKey: ""
    property var swatches: []
    property string swatchesKey: ""

    implicitHeight: band + (row.first ? Theme.space.xs : 0) + rule.height + reasonBox.height + (row.last ? Theme.space.xs : 0)
    z: dragging ? 10 : 0

    onRowChanged: {
        const c = JSON.stringify(row.chips)
        if (c !== chipsKey) { chipsKey = c; chips = row.chips }
        const s = JSON.stringify(row.swatches) + JSON.stringify(row.swatchTips)
        if (s !== swatchesKey) { swatchesKey = s; swatches = row.swatches }
    }
    Component.onCompleted: rowChanged()

    Item {
        id: body
        width: root.width
        height: root.height
        y: root.dragging ? (root.stack.settling ? root.stack.offsets[root.index] || 0 : root.stack.dragDy) : (root.stack.offsets[root.index] || 0)
        Behavior on y {
            enabled: !root.stack.instant && !(root.dragging && !root.stack.settling)
            NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic }
        }

        MouseArea {
            id: click
            objectName: "row_" + root.owner.number + "_" + root.index
            anchors.fill: parent
            onPressed: mouse => {
                root.slots.pickRow(root.owner.number, root.index)
                root.stack.forceActiveFocus(Qt.MouseFocusReason)
            }
        }

        DragHandler {
            id: drag
            objectName: "drag_" + root.owner.number + "_" + root.index
            enabled: root.row.candidate && root.owner.candidates > 1
            target: null
            xAxis.enabled: false
            cursorShape: active ? Qt.ClosedHandCursor : Qt.ArrowCursor
            onActiveChanged: active ? root.stack.dragStart(root.index) : root.stack.dragEnd()
            onActiveTranslationChanged: if (active) root.stack.dragMove(activeTranslation.y)
        }

        // picked
        Rectangle {
            anchors.fill: parent
            anchors.rightMargin: Theme.space.xs
            radius: Theme.radius.pill / 2
            color: Theme.colors.accent_tint
            opacity: root.current ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.fade } }
        }

        // the rail, through the node
        Rectangle {
            x: root.rail / 2 - 1
            width: 2
            y: root.row.first ? root.nodeY : 0
            height: (root.row.last ? root.nodeY : root.height) - y
            color: Theme.colors.control_border
        }
        Rectangle {
            id: node
            objectName: "node"
            readonly property bool on: root.row.state === "shown"
            readonly property int radiusOf: 5
            x: root.rail / 2 - radiusOf
            y: root.nodeY - radiusOf
            width: 2 * radiusOf
            height: width
            radius: radiusOf
            color: on ? Theme.colors.tone_good : Theme.colors.raised
            border.width: 2
            border.color: on ? Theme.colors.tone_good
                : root.row.state === "passed" ? Theme.colors.text_muted : Theme.colors.control_border
            scale: on ? 1.2 : 1.0
            Behavior on color { ColorAnimation { duration: Theme.resize } }
            Behavior on border.color { ColorAnimation { duration: Theme.resize } }
            Behavior on scale { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutBack } }
        }

        Text {
            id: elseText
            visible: !root.row.first
            x: root.rail
            y: Theme.space.xs
            text: "else"
            color: Theme.colors.text_muted
            font.pointSize: Theme.fontSize.body
        }

        RowLayout {
            id: rule
            x: root.rail
            y: root.band + (root.row.first ? Theme.space.xs : 0)
            width: body.width - root.rail - Theme.space.s
            spacing: Theme.space.s
            opacity: root.dim
            Behavior on opacity { NumberAnimation { duration: Theme.resize } }

            Text {
                Layout.preferredWidth: Theme.space.m
                text: root.row.number
                color: Theme.colors.text_muted
                font.pointSize: Theme.fontSize.body
            }
            FadeText {
                visible: text !== ""
                text: root.row.lead
                color: Theme.colors.text_muted
            }
            Repeater {
                model: root.chips
                RowLayout {
                    id: part
                    required property var modelData
                    spacing: Theme.space.s
                    Text {
                        visible: part.modelData.or === true
                        text: "or"
                        color: Theme.colors.text_muted
                        font.pointSize: Theme.fontSize.body
                    }
                    Chip {
                        objectName: "chip"
                        text: part.modelData.text
                        entity: part.modelData.kind === "presence" ? "presence" : "state"
                        SlotTip { text: part.modelData.tip; group: root }
                    }
                }
            }
            Text {
                visible: root.row.candidate
                text: "→"
                color: Theme.colors.text_muted
                font.pointSize: Theme.fontSize.body
            }
            FadeText {
                objectName: "nothing"
                visible: root.row.nothing
                text: root.row.show
                color: Theme.colors.text_muted
            }
            Repeater {
                model: root.row.nothing ? root.swatches : []
                Swatch {
                    id: lcd
                    required property var modelData
                    required property int index
                    color: modelData
                    SlotTip { text: root.row.swatchTips[lcd.index] || ""; group: root }
                }
            }
            Chip {
                objectName: "shows"
                visible: !root.row.nothing
                text: root.row.show
                entity: "channel"
                filled: true
                swatches: root.swatches
                SlotTip { text: root.row.showTip; group: root }
            }
            SoundBadge {
                id: sound
                objectName: "sound"
                visible: root.row.sound !== ""
                channel: root.row.sound
                kind: root.row.soundKind
                hue: Theme.colors.channel
                Layout.preferredWidth: 14
                Layout.preferredHeight: 12
                SlotTip { text: sound.active ? root.row.sound + " has sound now" : ""; group: root }
            }
            Text {
                id: options
                objectName: "options"
                visible: root.row.options !== ""
                Layout.fillWidth: true
                text: root.row.options
                elide: Text.ElideRight
                color: Theme.colors.text_muted
                font.pointSize: Theme.fontSize.body
                SlotTip { text: root.row.optionsTip; group: root }
            }
            Item { Layout.fillWidth: root.row.options === "" }
        }

        // why it did not win: grows in under the rule, and shrinks away
        Item {
            id: reasonBox
            x: root.rail + Theme.space.m + Theme.space.s
            y: rule.y + rule.height
            width: Math.min(reason.implicitWidth, body.width - x - Theme.space.s)
            clip: true
            property string last: ""
            readonly property bool open: root.row.reason !== ""
            height: open ? reason.implicitHeight : 0
            Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
            Text {
                id: reason
                width: reasonBox.width
                elide: Text.ElideRight
                // keeps the old text while it shrinks away
                text: "✗ " + (root.row.reason !== "" ? root.row.reason : reasonBox.last)
                color: Theme.colors.text_muted
                font.pointSize: Theme.fontSize.body
                opacity: reasonBox.open ? root.dim : 0
                Behavior on opacity { NumberAnimation { duration: Theme.resize } }
                onTextChanged: if (root.row.reason !== "") reasonBox.last = root.row.reason
            }
        }

        SlotTip { text: root.tipsOver === 0 ? root.row.tip : ""; z: -1 }
    }
}
