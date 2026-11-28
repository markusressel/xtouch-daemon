// A choice from a list that opens inside the window; each line says what it means while the mouse rests on it. While
// none is chosen, the field shows what is taken then (the placeholder) in gray.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: field
    required property Item row
    // the words of the choices and what each means; the owner of a bound part gives its own
    property var choices: row.spec.choices
    property var meanings: row.spec.meanings
    property var current: row.shown
    property string placeholder: row.placeholder
    property bool problem: row.problem
    signal chosen(string value)
    readonly property alias combo: combo

    implicitHeight: combo.implicitHeight
    implicitWidth: combo.implicitWidth

    ComboBox {
        id: combo
        objectName: "choice_" + field.row.spec.name
        width: Math.max(160, implicitWidth)
        model: field.choices
        problem: field.problem
        displayText: currentIndex < 0 ? field.placeholder : currentText
        onActivated: index => field.chosen(field.choices[index])

        contentItem: Text {
            leftPadding: 0
            text: combo.displayText
            font: combo.font
            color: combo.currentIndex < 0 ? Theme.colors.placeholder : Theme.colors.text
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        delegate: ItemDelegate {
            id: item
            required property var modelData
            required property int index
            objectName: "choice_item_" + modelData
            width: ListView.view.width
            text: modelData
            font.weight: combo.currentIndex === index ? Font.DemiBold : Font.Normal
            highlighted: combo.highlightedIndex === index
            ToolTip.visible: hovered && (field.meanings[modelData] ?? "") !== ""
            ToolTip.text: field.meanings[modelData] ?? ""
            ToolTip.delay: 400
        }
    }

    Binding {
        target: combo
        property: "currentIndex"
        value: field.choices.indexOf(field.current)
        restoreMode: Binding.RestoreNone
    }
}
