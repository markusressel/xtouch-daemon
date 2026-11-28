// A menu inside the window (never a popup window), fading and growing in from where it opens.
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Templates as T
import QtQuick.Window
import XTouch

T.Menu {
    id: control
    popupType: T.Popup.Item

    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            contentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             contentHeight + topPadding + bottomPadding)
    margins: 0
    padding: Theme.space.xs
    overlap: 1
    transformOrigin: Item.TopLeft

    delegate: MenuItem { }

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.fade }
        NumberAnimation { property: "scale"; from: 0.95; to: 1; duration: Theme.resize; easing.type: Easing.OutCubic }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; to: 0; duration: Theme.fade }
    }

    contentItem: ListView {
        implicitHeight: contentHeight
        implicitWidth: {
            let widest = 0
            for (let i = 0; i < count; ++i) {
                const item = itemAtIndex(i)
                if (item) widest = Math.max(widest, item.implicitWidth)
            }
            return widest
        }
        model: control.contentModel
        interactive: Window.window ? contentHeight + control.topPadding + control.bottomPadding > control.height : false
        clip: true
        currentIndex: control.currentIndex
        ScrollIndicator.vertical: ScrollIndicator {}
    }

    background: Rectangle {
        implicitWidth: 200
        color: Theme.colors.raised
        border.color: Theme.colors.border
        radius: Theme.radius.large
    }

    T.Overlay.modal: Rectangle { color: Theme.tint("black", 0.3) }
    T.Overlay.modeless: Rectangle { color: "transparent" }
}
