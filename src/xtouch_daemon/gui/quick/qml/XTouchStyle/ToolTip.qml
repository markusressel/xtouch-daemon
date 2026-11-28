// A tooltip: inside the window, on a raised card, after a short rest of the mouse; it fades in.
import QtQuick
import QtQuick.Templates as T
import XTouch

T.ToolTip {
    id: control
    popupType: T.Popup.Item
    x: parent ? (parent.width - implicitWidth) / 2 : 0
    y: parent ? parent.height + 4 : 0
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding)
    margins: Theme.space.s
    padding: Theme.space.s
    delay: 300
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutsideParent | T.Popup.CloseOnReleaseOutsideParent

    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.fade } }
    exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: Theme.fade } }

    contentItem: Text {
        text: control.text
        font: control.font
        wrapMode: Text.Wrap
        textFormat: Text.StyledText
        color: Theme.colors.text
        linkColor: Theme.colors.accent
    }

    background: Rectangle {
        color: Theme.colors.raised
        border.color: Theme.colors.border
        radius: Theme.radius.medium
    }
}
