// A popup inside the window (never a window of its own: it would grab the keyboard and the mouse): a raised card
// that fades and grows in.
import QtQuick
import QtQuick.Templates as T
import XTouch

T.Popup {
    id: control
    popupType: T.Popup.Item
    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            contentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             contentHeight + topPadding + bottomPadding)
    padding: Theme.space.m

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.fade }
        NumberAnimation { property: "scale"; from: 0.95; to: 1; duration: Theme.resize; easing.type: Easing.OutCubic }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; to: 0; duration: Theme.fade }
    }

    background: Rectangle {
        color: Theme.colors.raised
        border.color: Theme.colors.border
        radius: Theme.radius.large
    }

    T.Overlay.modal: Rectangle { color: Theme.tint("black", 0.3) }
    T.Overlay.modeless: Rectangle { color: "transparent" }
}
