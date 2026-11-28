// The colors of the LEDs and LCDs as swatches in a row: a click picks one (its name and what it means show as the tip);
// the one in use has the accent around it.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: field
    required property Item row
    property var choices: row.spec.choices
    property var meanings: row.spec.meanings
    property var current: row.shown
    signal chosen(string value)

    implicitHeight: flow.implicitHeight
    implicitWidth: flow.implicitWidth

    Flow {
        id: flow
        width: parent.width
        spacing: Theme.space.xs
        Repeater {
            model: field.choices
            Rectangle {
                id: swatch
                required property string modelData
                objectName: "color_" + modelData
                readonly property bool picked: field.current === modelData
                width: 26
                height: 26
                radius: 6
                color: Theme.lcd[modelData] ?? Theme.colors.sunken
                border.width: picked ? 3 : 1
                border.color: picked ? Theme.colors.accent : Theme.colors.control_border
                scale: tap.pressed ? 0.92 : hover.hovered ? 1.08 : 1
                Behavior on scale { NumberAnimation { duration: Theme.fade; easing.type: Easing.OutCubic } }
                Behavior on border.color { ColorAnimation { duration: Theme.fade } }
                Behavior on border.width { NumberAnimation { duration: Theme.fade } }
                Accessible.role: Accessible.RadioButton
                Accessible.name: modelData
                Accessible.checked: picked
                activeFocusOnTab: true
                Keys.onSpacePressed: field.chosen(modelData)
                Keys.onReturnPressed: field.chosen(modelData)
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: -3
                    radius: 8
                    color: "transparent"
                    border.width: 2
                    border.color: Theme.colors.accent
                    visible: swatch.activeFocus
                }
                HoverHandler { id: hover }
                TapHandler { id: tap; onTapped: field.chosen(swatch.modelData) }
                ToolTip.visible: hover.hovered
                ToolTip.text: modelData + ((field.meanings[modelData] ?? "") !== "" ? ": " + field.meanings[modelData] : "")
            }
        }
    }
}
