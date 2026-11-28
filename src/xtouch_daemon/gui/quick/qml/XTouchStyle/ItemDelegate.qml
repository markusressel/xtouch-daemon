// A row of a list: tinted under the mouse, in the accent tint while it is the one picked.
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Templates as T
import XTouch

T.ItemDelegate {
    id: control
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding,
                             implicitIndicatorHeight + topPadding + bottomPadding)
    padding: Theme.space.xs
    horizontalPadding: Theme.space.s
    spacing: Theme.space.s
    icon.width: 18
    icon.height: 18
    hoverEnabled: true

    contentItem: IconLabel {
        spacing: control.spacing
        mirrored: control.mirrored
        display: control.display
        alignment: control.display === IconLabel.IconOnly || control.display === IconLabel.TextUnderIcon ? Qt.AlignCenter : Qt.AlignLeft
        icon: control.icon
        text: control.text
        font: control.font
        color: control.enabled ? Theme.colors.text : Theme.colors.text_muted
        defaultIconColor: control.enabled ? Theme.colors.text : Theme.colors.text_muted
    }

    background: Rectangle {
        implicitWidth: 100
        implicitHeight: Theme.controlHeight - 4
        radius: Theme.radius.small
        color: control.down ? Theme.tint(Theme.colors.text, 0.16)
            : control.highlighted ? Theme.colors.accent_tint
            : control.hovered ? Theme.tint(Theme.colors.text, 0.07) : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.fade } }
    }
}
