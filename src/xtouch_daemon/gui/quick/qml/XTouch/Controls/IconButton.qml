// A button with only an icon (`name`, an mdi icon); `tip` says what it does, as a tooltip and to screen readers.
import QtQuick
import QtQuick.Controls

ToolButton {
    id: button
    property string name
    property string tip
    property color tint: "transparent"
    icon.source: name !== "" ? "image://icon/" + name : ""
    icon.color: tint.a > 0 ? tint : undefined
    display: AbstractButton.IconOnly
    text: tip
    Accessible.name: tip
    ToolTip.visible: hovered && tip !== ""
    ToolTip.text: tip
}
