// A switch: its knob slides, and the track fills with the accent.
import QtQuick
import QtQuick.Templates as T
import QtQuick.Controls.impl
import XTouch

T.Switch {
    id: control

    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding,
                             implicitIndicatorHeight + topPadding + bottomPadding)
    padding: Theme.space.xs
    spacing: Theme.space.s
    hoverEnabled: true

    indicator: Rectangle {
        implicitWidth: 40
        implicitHeight: 22
        x: control.text ? control.leftPadding : control.leftPadding + (control.availableWidth - width) / 2
        y: control.topPadding + (control.availableHeight - height) / 2
        radius: height / 2
        color: control.checked ? Theme.colors.accent : Theme.colors.sunken
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? Theme.colors.accent_hover
            : control.checked ? Theme.colors.accent : Theme.colors.control_border
        opacity: control.enabled ? 1 : 0.5
        Behavior on color { ColorAnimation { duration: Theme.fade } }

        Rectangle {
            readonly property real travel: parent.width - width - 6
            x: 3 + Math.max(0, Math.min(1, control.visualPosition)) * travel
            y: (parent.height - height) / 2
            width: control.down ? 20 : 16
            height: 16
            radius: 8
            color: control.checked ? Theme.colors.on_accent : Theme.colors.control_border
            Behavior on x { enabled: !control.down; NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
            Behavior on width { NumberAnimation { duration: Theme.fade } }
            Behavior on color { ColorAnimation { duration: Theme.fade } }
        }
    }

    contentItem: CheckLabel {
        leftPadding: control.indicator ? control.indicator.width + control.spacing : 0
        text: control.text
        font: control.font
        color: control.enabled ? Theme.colors.text : Theme.colors.text_muted
    }
}
