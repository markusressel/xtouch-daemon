// A button: outlined on the card, filled in the accent when `highlighted` (the one to press), plain when `flat`.
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Templates as T
import XTouch

T.Button {
    id: control

    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding)
    padding: Theme.space.xs
    horizontalPadding: Theme.space.m
    spacing: Theme.space.xs
    icon.width: 18
    icon.height: 18
    hoverEnabled: true

    readonly property color ink: !enabled ? Theme.colors.text_muted
        : highlighted ? Theme.colors.on_accent : flat ? Theme.colors.accent : Theme.colors.text

    contentItem: IconLabel {
        spacing: control.spacing
        mirrored: control.mirrored
        display: control.display
        icon: control.icon
        text: control.text
        font: control.font
        color: control.ink
        defaultIconColor: control.ink
    }

    background: Rectangle {
        implicitWidth: 64
        implicitHeight: Theme.controlHeight
        radius: Theme.radius.medium
        color: control.highlighted
            ? (control.down || control.hovered ? Theme.colors.accent_hover : Theme.colors.accent)
            : control.down ? Theme.tint(Theme.colors.text, 0.16)
            : control.hovered || control.checked ? Theme.tint(Theme.colors.text, 0.08)
            : control.flat ? "transparent" : Theme.colors.raised
        border.width: control.visualFocus ? 2 : control.flat || control.highlighted ? 0 : 1
        border.color: control.visualFocus ? Theme.colors.accent : Theme.colors.control_border
        opacity: control.enabled ? 1 : 0.6
        Behavior on color { ColorAnimation { duration: Theme.fade } }
    }
}
