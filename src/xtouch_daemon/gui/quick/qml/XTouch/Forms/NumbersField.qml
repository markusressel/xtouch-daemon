// A list of whole numbers picked with toggle buttons, from the minimum to the maximum of the option (e.g. which faders).
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: field
    required property Item row
    readonly property var values: row.shown && row.shown.length !== undefined ? Array.from(row.shown) : []
    readonly property int low: row.spec.minimum ?? 0
    readonly property int high: row.spec.maximum ?? 0

    implicitHeight: flow.implicitHeight

    function toggle(number) {
        const next = values.indexOf(number) >= 0 ? values.filter(each => each !== number) : [...values, number]
        row.edit(next.sort((a, b) => a - b))
    }

    Flow {
        id: flow
        width: parent.width
        spacing: Theme.space.xs
        Repeater {
            model: Math.max(0, field.high - field.low + 1)
            Button {
                required property int index
                readonly property int number: field.low + index
                objectName: "number_" + number
                text: String(number)
                highlighted: field.values.indexOf(number) >= 0
                implicitWidth: Theme.controlHeight
                horizontalPadding: 0
                onClicked: field.toggle(number)
            }
        }
    }
}
