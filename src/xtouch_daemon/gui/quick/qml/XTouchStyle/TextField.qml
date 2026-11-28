// A field to type in: sunken, its outline in the accent while it has the focus, in the error color for a problem
// (`problem: true`).
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Templates as T
import XTouch

T.TextField {
    id: control
    property bool problem: false

    implicitWidth: implicitBackgroundWidth + leftInset + rightInset
                   || Math.max(contentWidth, placeholder.implicitWidth) + leftPadding + rightPadding
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             contentHeight + topPadding + bottomPadding,
                             placeholder.implicitHeight + topPadding + bottomPadding)
    padding: Theme.space.xs
    leftPadding: Theme.space.s
    rightPadding: Theme.space.s
    color: enabled ? Theme.colors.text : Theme.colors.text_muted
    selectionColor: Theme.colors.accent
    selectedTextColor: Theme.colors.on_accent
    placeholderTextColor: Theme.colors.placeholder
    verticalAlignment: TextInput.AlignVCenter
    selectByMouse: true
    hoverEnabled: true

    PlaceholderText {
        id: placeholder
        x: control.leftPadding
        y: control.topPadding
        width: control.width - (control.leftPadding + control.rightPadding)
        height: control.height - (control.topPadding + control.bottomPadding)
        text: control.placeholderText
        font: control.font
        color: control.placeholderTextColor
        verticalAlignment: control.verticalAlignment
        visible: !control.length && !control.preeditText && (!control.activeFocus || control.horizontalAlignment !== Qt.AlignHCenter)
        elide: Text.ElideRight
        renderType: control.renderType
    }

    background: Rectangle {
        implicitWidth: 160
        implicitHeight: Theme.controlHeight
        radius: Theme.radius.medium
        color: Theme.colors.sunken
        border.width: control.activeFocus || control.problem ? 2 : 1
        border.color: control.problem ? Theme.colors.error
            : control.activeFocus ? Theme.colors.accent
            : control.hovered ? Theme.colors.text_muted : Theme.colors.control_border
        Behavior on border.color { ColorAnimation { duration: Theme.fade } }
    }
}
