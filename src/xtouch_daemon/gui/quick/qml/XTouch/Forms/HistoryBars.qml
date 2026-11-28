// The last day of a state: a bar per quarter of an hour, gray for the time it was off and in the color of the states for
// the time it was on (a dotted floor where no daemon watched), the clock under every sixth hour and "now" at the end.
// `history` is `[[time, on], ...]`, the changes the daemon tells (`StateView.history`).
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: bars
    required property QtObject tools
    property var history: []
    readonly property var spans: tools.historyBars(history)
    readonly property real barHeight: 32

    implicitHeight: barHeight + 2 + label.implicitHeight
    implicitWidth: 480

    Row {
        id: row
        width: parent.width
        Repeater {
            model: bars.spans
            Item {
                id: bar
                required property var modelData
                required property int index
                objectName: "history_bar_" + index
                width: row.width / bars.spans.length
                height: bars.barHeight

                // gray above for what was off, the color of the states below for what was on
                Rectangle {
                    visible: bar.modelData.watched
                    x: 1
                    width: parent.width - 2
                    height: Math.max(bar.modelData.known * bars.barHeight, 2)
                    y: bars.barHeight - height
                    color: Theme.tint(Theme.colors.text_muted, 0.35)
                }
                Rectangle {
                    visible: bar.modelData.on > 0
                    x: 1
                    width: parent.width - 2
                    height: Math.max(bar.modelData.on * bars.barHeight, 1)
                    y: bars.barHeight - height
                    color: Theme.colors.state
                    Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
                }
                Rectangle {
                    visible: !bar.modelData.watched
                    x: 1
                    width: parent.width - 2
                    y: bars.barHeight - 1
                    height: 1
                    color: Theme.colors.border
                }
                Label {
                    visible: bar.modelData.label !== ""
                    x: 0
                    y: bars.barHeight + 2
                    text: bar.modelData.label
                    width: implicitWidth
                    font.pointSize: Theme.fontSize.caption
                    color: Theme.colors.text_muted
                }
                HoverHandler { id: hover }
                ToolTip.visible: hover.hovered
                ToolTip.text: modelData.tip
            }
        }
    }
    Label {
        id: label
        anchors { right: parent.right; top: row.bottom; topMargin: 2 }
        text: "now"
        font.pointSize: Theme.fontSize.caption
        color: Theme.colors.text_muted
    }
}
