import QtQuick
import QtQuick.Controls.impl
import QtQuick.Templates as T
import XTouch

T.TabButton {
    id: control
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding)
    padding: Theme.space.s
    spacing: Theme.space.xs
    icon.width: 18
    icon.height: 18
    hoverEnabled: true

    contentItem: IconLabel {
        spacing: control.spacing
        mirrored: control.mirrored
        display: control.display
        icon: control.icon
        text: control.text
        font: control.font
        color: control.checked ? Theme.colors.accent : control.hovered ? Theme.colors.text : Theme.colors.text_muted
        defaultIconColor: control.checked ? Theme.colors.accent : control.hovered ? Theme.colors.text : Theme.colors.text_muted
        Behavior on color { ColorAnimation { duration: Theme.fade } }
    }

    background: Rectangle {
        implicitHeight: Theme.controlHeight
        color: control.hovered && !control.checked ? Theme.tint(Theme.colors.text, 0.05) : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.fade } }
    }
}
