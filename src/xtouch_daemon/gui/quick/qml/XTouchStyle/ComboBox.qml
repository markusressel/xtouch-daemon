// A drop-down list (`Choice` in the forms): its list opens inside the window, never as a popup window.
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Templates as T
import XTouch

T.ComboBox {
    id: control
    property bool problem: false

    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding,
                             implicitIndicatorHeight + topPadding + bottomPadding)
    leftPadding: Theme.space.s
    rightPadding: Theme.space.s + indicator.width + spacing
    spacing: Theme.space.xs
    hoverEnabled: true

    delegate: ItemDelegate {
        required property var model
        required property int index
        width: ListView.view.width
        text: control.textRole ? model[control.textRole] : model.modelData
        font.weight: control.currentIndex === index ? Font.DemiBold : Font.Normal
        highlighted: control.highlightedIndex === index
        hoverEnabled: control.hoverEnabled
    }

    indicator: ColorImage {
        x: control.width - width - Theme.space.s
        y: control.topPadding + (control.availableHeight - height) / 2
        width: 16; height: 16
        source: "image://icon/chevron-down"
        color: Theme.colors.text_muted
        rotation: control.popup.visible ? 180 : 0
        Behavior on rotation { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
    }

    contentItem: T.TextField {
        text: control.editable ? control.editText : control.displayText
        enabled: control.editable
        autoScroll: control.editable
        readOnly: control.down
        inputMethodHints: control.inputMethodHints
        validator: control.validator
        selectByMouse: control.selectTextByMouse
        color: control.enabled ? Theme.colors.text : Theme.colors.text_muted
        selectionColor: Theme.colors.accent
        selectedTextColor: Theme.colors.on_accent
        verticalAlignment: Text.AlignVCenter
        font: control.font
    }

    background: Rectangle {
        implicitWidth: 140
        implicitHeight: Theme.controlHeight
        radius: Theme.radius.medium
        color: control.editable ? Theme.colors.sunken : control.down ? Theme.tint(Theme.colors.text, 0.12)
            : control.hovered ? Theme.tint(Theme.colors.text, 0.06) : Theme.colors.raised
        border.width: control.visualFocus || control.activeFocus && control.editable || control.problem ? 2 : 1
        border.color: control.problem ? Theme.colors.error
            : control.visualFocus || control.activeFocus && control.editable ? Theme.colors.accent
            : Theme.colors.control_border
        Behavior on color { ColorAnimation { duration: Theme.fade } }
    }

    popup: T.Popup {
        popupType: T.Popup.Item
        y: control.height + 2
        width: Math.max(control.width, contentItem.implicitWidth)
        height: Math.min(contentItem.implicitHeight + topPadding + bottomPadding,
                         control.Window.height - topMargin - bottomMargin)
        topMargin: Theme.space.s
        bottomMargin: Theme.space.s
        padding: Theme.space.xs
        font: control.font
        transformOrigin: Item.Top

        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.fade }
            NumberAnimation { property: "scale"; from: 0.95; to: 1; duration: Theme.resize; easing.type: Easing.OutCubic }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; to: 0; duration: Theme.fade }
        }

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            implicitWidth: contentItem.childrenRect.width
            model: control.delegateModel
            currentIndex: control.highlightedIndex
            highlightMoveDuration: 0
            boundsBehavior: Flickable.StopAtBounds
            T.ScrollIndicator.vertical: ScrollIndicator { }
        }

        background: Rectangle {
            color: Theme.colors.raised
            border.color: Theme.colors.border
            radius: Theme.radius.large
        }
    }
}
