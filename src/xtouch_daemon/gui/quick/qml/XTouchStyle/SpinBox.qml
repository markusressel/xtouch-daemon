// A number: typed in, or stepped with the buttons, the arrow keys or the wheel (only while it has the focus).
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Templates as T
import XTouch

T.SpinBox {
    id: control
    property bool problem: false

    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            contentItem.implicitWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding,
                             up.implicitIndicatorHeight, down.implicitIndicatorHeight)
    leftPadding: Theme.space.s
    rightPadding: up.indicator.width * 2 + Theme.space.xs
    editable: true
    wheelEnabled: activeFocus
    hoverEnabled: true

    validator: IntValidator {
        locale: control.locale.name
        bottom: Math.min(control.from, control.to)
        top: Math.max(control.from, control.to)
    }

    contentItem: TextInput {
        z: 2
        text: control.displayText
        clip: width < implicitWidth
        font: control.font
        color: control.enabled ? Theme.colors.text : Theme.colors.text_muted
        selectionColor: Theme.colors.accent
        selectedTextColor: Theme.colors.on_accent
        verticalAlignment: Qt.AlignVCenter
        readOnly: !control.editable
        validator: control.validator
        inputMethodHints: control.inputMethodHints
        selectByMouse: true
    }

    component Step: Rectangle {
        property bool pressed
        property bool hovered
        property string glyph
        implicitWidth: 24
        implicitHeight: Theme.controlHeight - 4
        y: 2
        radius: Theme.radius.small
        color: pressed ? Theme.tint(Theme.colors.text, 0.16) : hovered ? Theme.tint(Theme.colors.text, 0.08) : "transparent"
        ColorImage {
            anchors.centerIn: parent
            width: 16; height: 16
            source: "image://icon/" + parent.glyph
            color: control.enabled ? Theme.colors.text_muted : Theme.colors.border
        }
    }

    up.indicator: Step {
        x: control.width - width - 2
        pressed: control.up.pressed
        hovered: control.up.hovered
        glyph: "plus"
    }
    down.indicator: Step {
        x: control.width - 2 * width - 2
        pressed: control.down.pressed
        hovered: control.down.hovered
        glyph: "minus"
    }

    background: Rectangle {
        implicitWidth: 120
        implicitHeight: Theme.controlHeight
        radius: Theme.radius.medium
        color: Theme.colors.sunken
        border.width: control.activeFocus || control.problem ? 2 : 1
        border.color: control.problem ? Theme.colors.error
            : control.activeFocus ? Theme.colors.accent : Theme.colors.control_border
        Behavior on border.color { ColorAnimation { duration: Theme.fade } }
    }
}
