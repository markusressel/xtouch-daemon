import QtQuick
import QtQuick.Templates as T
import QtQuick.Controls.impl
import XTouch

T.CheckBox {
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
        implicitWidth: 18
        implicitHeight: 18
        x: control.text ? control.leftPadding : control.leftPadding + (control.availableWidth - width) / 2
        y: control.topPadding + (control.availableHeight - height) / 2
        radius: Theme.radius.small
        color: control.checkState !== Qt.Unchecked ? Theme.colors.accent : Theme.colors.sunken
        border.width: control.visualFocus ? 2 : 1
        border.color: control.checkState !== Qt.Unchecked ? Theme.colors.accent : Theme.colors.control_border
        Behavior on color { ColorAnimation { duration: Theme.fade } }

        ColorImage {
            anchors.centerIn: parent
            width: 14; height: 14
            source: control.checkState === Qt.PartiallyChecked ? "image://icon/minus" : "image://icon/check"
            color: Theme.colors.on_accent
            opacity: control.checkState !== Qt.Unchecked ? 1 : 0
            scale: control.checkState !== Qt.Unchecked ? 1 : 0.6
            Behavior on opacity { NumberAnimation { duration: Theme.fade } }
            Behavior on scale { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutBack } }
        }
    }

    contentItem: CheckLabel {
        leftPadding: control.indicator ? control.indicator.width + control.spacing : 0
        text: control.text
        font: control.font
        color: control.enabled ? Theme.colors.text : Theme.colors.text_muted
    }
}
