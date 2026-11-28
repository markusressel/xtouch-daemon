// A button with an icon (and maybe a text) in a bar or on a card: plain until hovered.
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Templates as T
import XTouch

T.ToolButton {
    id: control

    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding)
    padding: Theme.space.xs
    horizontalPadding: text !== "" && display !== T.AbstractButton.IconOnly ? Theme.space.s : Theme.space.xs
    spacing: Theme.space.xs
    icon.width: 18
    icon.height: 18
    hoverEnabled: true
    flat: true

    contentItem: IconLabel {
        spacing: control.spacing
        mirrored: control.mirrored
        display: control.display
        icon: control.icon
        text: control.text
        font: control.font
        color: !control.enabled ? Theme.colors.text_muted : control.checked ? Theme.colors.accent : Theme.colors.text
        defaultIconColor: !control.enabled ? Theme.colors.text_muted : control.checked ? Theme.colors.accent : Theme.colors.text
    }

    background: Rectangle {
        implicitWidth: Theme.controlHeight
        implicitHeight: Theme.controlHeight
        radius: Theme.radius.small
        color: control.down ? Theme.tint(Theme.colors.text, 0.16)
            : control.checked ? Theme.colors.accent_tint
            : control.hovered ? Theme.tint(Theme.colors.text, 0.08) : "transparent"
        border.width: control.visualFocus ? 2 : 0
        border.color: Theme.colors.accent
        Behavior on color { ColorAnimation { duration: Theme.fade } }
    }
}
