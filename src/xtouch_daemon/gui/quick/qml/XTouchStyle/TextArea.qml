// Several lines to type in, as a field.
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Templates as T
import XTouch

T.TextArea {
    id: control
    property bool problem: false

    implicitWidth: Math.max(contentWidth + leftPadding + rightPadding,
                            implicitBackgroundWidth + leftInset + rightInset,
                            placeholder.implicitWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(contentHeight + topPadding + bottomPadding,
                             implicitBackgroundHeight + topInset + bottomInset,
                             placeholder.implicitHeight + topPadding + bottomPadding)
    padding: Theme.space.s
    color: enabled ? Theme.colors.text : Theme.colors.text_muted
    selectionColor: Theme.colors.accent
    selectedTextColor: Theme.colors.on_accent
    placeholderTextColor: Theme.colors.placeholder
    selectByMouse: true
    wrapMode: TextEdit.Wrap

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
        visible: !control.length && !control.preeditText
        elide: Text.ElideRight
        renderType: control.renderType
    }

    background: Rectangle {
        implicitWidth: 200
        implicitHeight: Theme.controlHeight * 2
        radius: Theme.radius.medium
        color: Theme.colors.sunken
        border.width: control.activeFocus || control.problem ? 2 : 1
        border.color: control.problem ? Theme.colors.error
            : control.activeFocus ? Theme.colors.accent : Theme.colors.control_border
        Behavior on border.color { ColorAnimation { duration: Theme.fade } }
    }
}
