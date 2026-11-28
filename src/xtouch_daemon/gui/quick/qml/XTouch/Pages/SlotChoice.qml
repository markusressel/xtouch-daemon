// A drop-down that picks nothing to stay: it shows a placeholder, and choosing an item of `items` (`text`, `name`,
// `tip`) says its name (`picked`) and goes back to the placeholder. The list opens inside the window.
import QtQuick
import QtQuick.Controls
import XTouch

ComboBox {
    id: choice
    property string placeholder
    property string tip
    property var items: []
    signal picked(string name)

    model: items
    textRole: "text"
    currentIndex: -1
    displayText: placeholder
    implicitWidth: 200
    ToolTip.visible: hovered && !popup.visible && tip !== ""
    ToolTip.delay: 400
    ToolTip.text: tip.replace(/`/g, "")

    delegate: ItemDelegate {
        id: entry
        required property var modelData
        required property int index
        width: ListView.view.width
        text: modelData.text
        highlighted: choice.highlightedIndex === index
        ToolTip.visible: hovered && modelData.tip !== undefined && modelData.tip !== ""
        ToolTip.delay: 400
        ToolTip.text: modelData.tip || ""
    }

    onActivated: index => {
        picked(items[index].name)
        currentIndex = -1
    }
}
